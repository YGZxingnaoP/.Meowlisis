# -*- coding: utf-8 -*-
# func/toolbox/analysis.py
# 父级 toolcalls：注册触发型工具，由 AI 决策参数与 start

import json
from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig


class TBoxAnalysis:
    """父级 toolcalls 分析类：维护模块入口注册表，AI 决策选择并开启模块"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self.llm = None
        self._tools = {}
        # 当前用户名（decide 时注入，供模块使用）
        self.current_username = ""
        self._register_modules()

    def _register_modules(self):
        """注册父级「模块入口」（只暴露模块级工具，不暴露模块内部子工具）

        目前仅两个模块：
        - napcat 主动发送模块（TBNapcatActiveModule，入口 napcat_send）
        - 视觉模块触发（TBVisionCore，入口 use_vision）

        模块内部的底层子工具（send_qq_message / search_file / capture_screen / crop_image 等）
        只在模块内部完整流程中被调用，不暴露给父级。
        """
        # NapCat 主动发送模块
        try:
            from func.toolbox.napcat.active_sender.module import TBNapcatActiveModule
            napcat = TBNapcatActiveModule()
            for tool_schema in napcat.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, napcat)
        except Exception:
            self.log.exception("注册 NapCat 主动发送模块失败")

        # 视觉模块触发
        try:
            from func.toolbox.meowvision.vision_core import TBVisionCore
            vision = TBVisionCore()
            for tool_schema in vision.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, vision)
        except Exception:
            self.log.exception("注册视觉模块失败")

    def _ensure_llm(self):
        """懒加载 toolbox 独立 LLM 客户端"""
        if self.llm is None:
            if self.config.llm_type == "aliyun":
                from func.toolbox.port.aliyun import TBoxAliyunLLM
                self.llm = TBoxAliyunLLM()
            else:
                from func.toolbox.port.deepseek import TBoxDeepSeekLLM
                self.llm = TBoxDeepSeekLLM()
        return self.llm

    def register(self, name: str, tool):
        """注册一个触发型工具到父级 toolcalls 注册表"""
        self._tools[name] = tool

    def build_tools(self) -> List[Dict]:
        """构建父级模块入口的工具定义（只暴露模块级入口，不暴露模块内部子工具）"""
        schemas = []
        seen_tools = set()
        for tool in self._tools.values():
            if id(tool) in seen_tools:
                continue
            seen_tools.add(id(tool))
            if hasattr(tool, "build_tools"):
                schemas.extend(tool.build_tools())
        return schemas

    def _intent_tool(self) -> List[Dict]:
        """意图判断工具：先判断用户消息是否包含需要调用某个模块的操作意图"""
        return [{
            "type": "function",
            "function": {
                "name": "decide_intent",
                "description": "判断用户消息是否包含需要调用工具箱模块的操作意图",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "is_action": {
                            "type": "boolean",
                            "description": (
                                "是否包含操作意图。操作意图包括："
                                "qq/发消息/发文件/发链接（QQ发送）；"
                                "看屏幕/截图/看图片/看我在做什么/看我打游戏（视觉）。"
                                "普通闲聊、询问、讨论填 false。"
                            ),
                        },
                    },
                    "required": ["is_action"],
                },
            },
        }]

    def decide(self, text: str, username: str, suppress_fast_reply: bool = False):
        """接收输入内容，由 AI 决策调用哪个工具并执行。"""
        self.current_username = username
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("父级 toolcalls LLM 不可用")
            return

        from func.toolbox.get_prompt import TBoxGetPrompt
        base_prompt = TBoxGetPrompt().get_tool_prompt(username, text) or ""
        history_messages = self._load_short_memory()

        # ============ 阶段1：意图预判（无工具，强制调用 decide_intent） ============
        intent_prompt = (
            f"{base_prompt}\n\n"
            f"【意图判断】请判断用户这条消息是否是在要求你执行某个实际操作。\n"
            f"操作包括：QQ发消息/发文件/发链接；看屏幕/截图/看图片/看我在做什么/陪我打游戏/陪我玩。\n"
            f"如果是操作请求，is_action 填 true；如果只是普通闲聊、询问、讨论，is_action 填 false。"
        )
        intent_messages = [{"role": "system", "content": intent_prompt}]
        intent_messages.extend(history_messages)
        intent_messages.append({"role": "user", "content": text})

        intent_resp = llm.chat(
            intent_messages,
            tools=self._intent_tool(),
            tool_choice={"type": "function", "function": {"name": "decide_intent"}},
        )
        is_action = self._parse_intent(intent_resp)
        if not is_action:
            # 闲聊/非操作意图
            if suppress_fast_reply:
                self.log.info("父级 toolcalls 意图判断为非操作，且已由主链路回复，静默")
            else:
                content = self._extract_content(intent_resp)
                if content.strip():
                    from func.pipeline.toolbox_llm import ToolboxLLMBridge
                    ToolboxLLMBridge().send_to_llm(content, username)
            return

        # ============ 阶段2：强制工具调用（意图已确认，必须选一个模块执行） ============
        self.log.info("父级 toolcalls 判定为操作意图，进入强制工具调用")
        action_prompt = (
            f"{base_prompt}\n\n"
            f"【工具调用】用户已经明确表达了操作意图，你必须调用一个工具来完成，禁止只输出文字。"
        )
        action_messages = [{"role": "system", "content": action_prompt}]
        action_messages.extend(history_messages)
        action_messages.append({"role": "user", "content": text})

        resp = llm.chat(action_messages, tools=self.build_tools(), tool_choice="required")
        if not resp or not resp.choices:
            self.log.warning("父级 toolcalls 强制工具调用无响应")
            return
        msg = resp.choices[0].message
        if not msg.tool_calls:
            self.log.warning("父级 toolcalls 判定为操作意图，但未调用工具")
            return
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                self.log.exception(f"解析工具参数失败: {name}")
                args = {}
            result = self.dispatch(name, args, username)
            self.log.info(f"父级工具 {name} 执行结果: {result}")

    def _parse_intent(self, resp) -> bool:
        """解析意图判断结果，返回 is_action 布尔值"""
        if not resp or not resp.choices:
            return False
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == "decide_intent":
                    args = json.loads(tc.function.arguments or "{}")
                    return bool(args.get("is_action"))
        except Exception:
            self.log.exception("解析意图判断失败")
        return False

    @staticmethod
    def _extract_content(resp) -> str:
        """从响应中提取 content 文本（用于非操作意图时的快速回复）"""
        if not resp or not resp.choices:
            return ""
        try:
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            return ""

    def _load_short_memory(self, limit: int = 6) -> List[Dict]:
        """加载最近短期记忆（供工具分析理解上下文），返回 OpenAI messages 列表"""
        try:
            from func.pipeline.short_memory import ShortMemory
            records = ShortMemory().load()
            # 去掉 type 后只剩 role/content，取最近 limit 条
            return [{"role": m["role"], "content": m["content"]} for m in records[-limit:]]
        except Exception:
            self.log.exception("工具分析加载短期记忆失败")
            return []

    def dispatch(self, tool_name: str, arguments: Dict, username: str = None):
        """按模块入口名与参数执行对应模块"""
        tool = self._tools.get(tool_name)
        if not tool:
            return f"错误：未知模块入口 {tool_name}"
        if username and hasattr(tool, "set_username"):
            try:
                tool.set_username(username)
            except Exception:
                pass
        if hasattr(tool, "dispatch"):
            return tool.dispatch(tool_name, arguments or {})
        return None
