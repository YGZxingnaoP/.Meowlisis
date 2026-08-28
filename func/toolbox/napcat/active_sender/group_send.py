# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/group_send.py
# 群发：AI 从群列表选目标群、拟定消息，必要时发送链接/文件

import json
from typing import List, Dict, Optional

from func.log.default_log import DefaultLog
from func.toolbox.napcat.active_sender.sender import TBSender
from func.toolbox.napcat.active_sender.get_grouplist import TBGetGroupList


class TBGroupSend:
    """群聊主动发送编排：群列表 → LLM 选目标群并拟稿 → 发送

    excuse 触发策略：
    - AI 信息充足时直接果断发送，不做每次发送前确认；
    - 仅当 AI 判定「信息极度不全面」（need_clarify=true）时，才角色口吻询问用户。
    """

    TOOL_NAME = "send_to_groups"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.sender = TBSender()
        self.get_grouplist = TBGetGroupList()
        self._username = ""

    def set_username(self, username: str):
        """注入当前用户（供 excuse 询问时使用，由 analysis.dispatch 调用）"""
        self._username = username or ""

    def build_tools(self) -> List[Dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "根据需求，从 QQ 群列表中选定一个或多个群并拟定消息发送（可带链接/文件）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string", "description": "发送需求，例如：在某个群发一条活动通知"},
                    },
                    "required": ["request"],
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        if name == self.TOOL_NAME:
            return self.execute(arguments.get("request", ""), self._username)
        return f"错误：未知工具 {name}"

    def execute(self, request: str, username: str = "") -> str:
        if not request:
            return "发送失败：缺少需求描述"
        # 主动发送开关 + 冷却检查
        err = self.sender.check_active_send()
        if err:
            return err
        groups = self.get_grouplist.get()
        if not groups:
            return "未获取到群列表，无法发送"

        plan = self._plan(request, groups, username)

        # AI 判定信息极度不全面 → 角色口吻询问补充需求后重试一次
        if plan and plan.get("need_clarify"):
            from func.toolbox.excuse import TBExcuse
            question = plan.get("clarify_question") or \
                "我想帮你群发消息，但没太明白要发到哪个群、发什么内容，能再说清楚一点吗？"
            clarify = TBExcuse().ask(question, username=username)
            if clarify:
                plan = self._plan(f"{request}；用户补充：{clarify}", groups, username)

        if not plan:
            return "AI 未能确定发送目标与内容"

        # 信息充足：果断发送，不再每次确认
        results = []
        for target in plan.get("targets", []):
            group_id = str(target.get("group_id", "") or "").strip()
            text = str(target.get("text", "") or "").strip()
            if not group_id:
                continue
            if text:
                results.append(self.sender.send_text("group", group_id, text))
            file_path = str(target.get("file_path", "") or "").strip()
            if file_path:
                results.append(self.sender.send_file("group", group_id, file_path))
            url = str(target.get("url", "") or "").strip()
            if url:
                results.append(self.sender.send_link("group", group_id, url))
        self.sender.mark_active_send()
        return "；".join(results) if results else "未执行发送"

    def _plan(self, request: str, groups: List[dict], username: str = "") -> Optional[dict]:
        llm = self._llm()
        if llm is None or not llm.client:
            return None
        group_lines = "\n".join(
            f"- group_id={g.get('group_id')} 群名={g.get('group_name') or ''}" for g in groups
        )
        # 完整系统提示词（角色人设 + 价值观 + 记忆），保证决策受角色约束
        system_prompt = self._system_prompt(username, request)
        resp = llm.chat([
            {"role": "system", "content": (
                f"{system_prompt}\n\n"
                f"根据群列表与用户需求，选定发送目标群并拟定消息。"
                f"如需求涉及文件或链接，可填写文件路径或链接。调用 send_to_groups_plan 工具输出计划。"
                f"只有在信息极度不全面、无法确定发到哪个群或发什么时，才把 need_clarify 设为 true 并给出询问问题；"
                f"信息足够时果断输出计划，need_clarify 设为 false。"
            )},
            {"role": "user", "content": f"群列表：\n{group_lines}\n\n需求：{request}"},
        ], tools=self._plan_tools(), tool_choice={"type": "function", "function": {"name": "send_to_groups_plan"}})
        if not resp or not resp.choices:
            return None
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == "send_to_groups_plan":
                    return json.loads(tc.function.arguments or "{}")
        except Exception:
            self.log.exception("解析群发送计划失败")
        return None

    def _plan_tools(self) -> List[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "send_to_groups_plan",
                "description": "输出群发送计划，或在信息极度不全面时请求澄清",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "need_clarify": {
                            "type": "boolean",
                            "description": "信息是否极度不全面，无法确定目标群或内容",
                        },
                        "clarify_question": {
                            "type": "string",
                            "description": "需要询问用户的问题（need_clarify=true 时必填）",
                        },
                        "targets": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "group_id": {"type": "string"},
                                    "text": {"type": "string"},
                                    "file_path": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                                "required": ["group_id", "text"],
                            },
                        },
                    },
                    "required": ["need_clarify", "targets"],
                },
            },
        }]

    def _system_prompt(self, username: str, current_message: str) -> str:
        """获取决策用角色人设提示词（前置词+角色卡+价值观+后置词，无用户记忆、无「和谁说话」）"""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            return TBoxGetPrompt().get_tool_prompt(username, current_message) or ""
        except Exception:
            return ""

    def _llm(self):
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(cfg)
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
