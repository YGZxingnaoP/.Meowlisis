# -*- coding: utf-8 -*-
# func/toolbox/napcat/message/emote_choose.py
# 表情选择：开启深度思考，根据场景从 EmoteLab 选择合适表情

import os
import json
import random
from typing import List, Optional

from func.log.default_log import DefaultLog
from func.llm.config import LLMConfig
from func.toolbox.napcat.config import TBNapCatConfig


class TBEmoteChoose:
    """深度思考选择表情（复用 func/llm 配置，通过 toolbox port 非流式调用）"""

    TOOL_NAME = "choose_emote"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.llm_cfg = LLMConfig()
        self.napcat_cfg = TBNapCatConfig()
        self.emote_dir = self.napcat_cfg.emote_dir
        self.scenes_path = os.path.join(".NapCat", "emote_scenes.json")

    def _list_emotes(self) -> List[str]:
        """列出 EmoteLab 下可用表情名（去 .gif 后缀）"""
        if not os.path.isdir(self.emote_dir):
            return []
        result = []
        for fn in os.listdir(self.emote_dir):
            if fn.lower().endswith(".gif"):
                result.append(fn[:-4])
        return sorted(result)

    def _load_scenes(self) -> dict:
        try:
            with open(self.scenes_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _build_scene_lines(self, scenes: dict, emotes: List[str]) -> str:
        """构建可用表情场景说明（重复场景描述随机保留一个表情）"""
        # 按场景描述分组：scene -> [表情1, 表情2, ...]
        grouped = {}
        for k, v in scenes.items():
            if k not in emotes:
                continue
            grouped.setdefault(str(v).strip(), []).append(k)
        lines = []
        for scene, names in grouped.items():
            # 场景描述重复时，随机挑一个表情代表该场景
            name = random.choice(names) if names else ""
            lines.append(f"- {name}：{scene}")
        return "\n".join(lines)

    def build_tools(self) -> List[dict]:
        """构建表情选择工具 schema"""
        emotes = self._list_emotes()
        emote_schema = {"type": "string", "enum": emotes} if emotes else {"type": "string"}
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "从可用表情中选择一个最适合当前场景的表情发送",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "emote_name": {
                            **emote_schema,
                            "description": "要发送的表情名称（必须从可用表情列表中选择，且只能选一个）",
                        },
                    },
                    "required": ["emote_name"],
                },
            },
        }]

    def choose(self, username: str, text: str, reply_text: str, chat_record: List[dict]) -> str:
        """深度思考选择表情，返回表情名（不含 .gif），失败返回空串"""
        emotes = self._list_emotes()
        self.log.info(f"[表情] 可用表情数量: {len(emotes)}")
        if not emotes:
            self.log.warning("[表情] EmoteLab 下没有找到表情文件")
            return ""
        scenes = self._load_scenes()
        scene_lines = self._build_scene_lines(scenes, emotes)

        persona = self._persona(username, text)
        chat_lines = "\n".join(f"{'用户' if m.get('role') == 'user' else 'AI'}：{m.get('content', '')}"
                               for m in (chat_record or [])[-20:])
        messages = [
            {"role": "system", "content": (
                f"{persona}\n\n"
                f"你需要根据当前对话，从下面的可用表情中选择一个最合适的动画表情发送。\n\n"
                f"【可用表情及使用场景】\n{scene_lines}"
            )},
            {"role": "user", "content": (
                f"最近聊天记录：\n{chat_lines}\n\n"
                f"用户刚说：{text}\n你的回复：{reply_text}\n\n"
                f"请调用 choose_emote 工具，从可用表情中选择一个最合适的表情。"
            )},
        ]
        resp = self._call(messages)
        if not resp or not resp.choices:
            self.log.warning("[表情] LLM 无响应")
            return ""
        try:
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []
            if not tool_calls:
                content = msg.content or ""
                self.log.warning(f"[表情] 模型未调用工具，直接输出: {content[:60]}")
                return ""
            for tc in tool_calls:
                if tc.function.name == self.TOOL_NAME:
                    args = json.loads(tc.function.arguments)
                    raw = args.get("emote_name", "")
                    # 严格限制：即使 AI 返回列表，也只取第一个
                    if isinstance(raw, list):
                        raw = raw[0] if raw else ""
                    name = str(raw or "").strip()
                    if name in emotes:
                        return name
                    self.log.warning(f"[表情] 返回的表情名不在列表: {name}")
        except Exception:
            self.log.exception("解析表情选择工具调用失败")
        return ""

    def _persona(self, username: str, current_message: str) -> str:
        """获取完整系统提示词（角色人设 + 价值观 + 记忆），保证选表情决策受角色约束"""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            return TBoxGetPrompt().get_system_prompt(username, current_message) or ""
        except Exception:
            return ""

    def _call(self, messages):
        """用 toolbox port 深度思考调用（复用 func/llm 配置）

        工具调用需要足够的 max_tokens，避免 arguments 被截断导致 JSON 解析失败。
        """
        if self.llm_cfg.local_llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            llm = TBoxAliyunLLM(self.llm_cfg)
        else:
            from func.toolbox.port.deepseek import TBoxDeepSeekLLM
            llm = TBoxDeepSeekLLM(self.llm_cfg)
        if not llm.client:
            return None
        # 工具调用 + 深度思考：留足 token 空间，防止 arguments 被截断
        old_max = getattr(llm, "max_tokens", None)
        try:
            llm.max_tokens = max(512, int(old_max or 0) + 384)
            return llm.chat(messages, tools=self.build_tools(), enable_thinking=True)
        finally:
            if old_max is not None:
                llm.max_tokens = old_max
