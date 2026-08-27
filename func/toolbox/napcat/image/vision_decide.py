# -*- coding: utf-8 -*-
# func/toolbox/napcat/image/vision_decide.py
# 视觉决策：深度思考判断当前话题是否与图片强相关，是否需要看图片

import json
from typing import List, Optional

from func.log.default_log import DefaultLog


class TBVisionDecide:
    """决策是否需要调用视觉工具看图片（视觉由 meowvision 模块处理）"""

    TOOL_NAME = "decide_view"

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def should_view(self, text: str, images: List[dict], chat_record: Optional[List[dict]] = None,
                    username: str = "") -> bool:
        """深度思考判断是否需要看图片（受完整角色提示词约束）。

        - 若消息含图片且当前话题与图片强相关，返回 True（上层转 meowvision 看图）；
        - 否则 False。
        """
        if not images:
            return False
        llm = self._llm()
        if llm is None or not llm.client:
            self.log.warning("[视觉决策] LLM 不可用，默认不看图")
            return False
        persona = self._persona(username, text)
        chat_lines = "\n".join(
            f"{'用户' if m.get('role') == 'user' else 'AI'}：{m.get('content', '')}"
            for m in (chat_record or [])[-20:]
        )
        img_desc = "\n".join(
            f"- 图片{i + 1}: {img.get('url') or img.get('file')}" for i, img in enumerate(images)
        )
        messages = [
            {"role": "system", "content": (
                f"{persona}\n\n"
                f"【默认操作是不看图】没有极强需求绝对不触发。\n"
                f"用户发来了一张图片。你需要深度思考，判断当前话题是否与图片强相关、"
                f"是否需要调用视觉工具查看图片内容。调用 decide_view 工具输出判断。"
            )},
            {"role": "user", "content": (
                f"最近聊天记录：\n{chat_lines}\n\n"
                f"用户刚说：{text}\n\n"
                f"图片信息：\n{img_desc}\n\n"
                f"请判断是否需要查看图片内容。"
            )},
        ]
        # 工具调用时关闭深度思考（thinking 与 function calling 冲突，避免 JSON 截断）
        resp = llm.chat(messages, tools=self.build_tools(), tool_choice=self.build_tool_choice(),
                        enable_thinking=False)
        if not resp or not resp.choices:
            return False
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == self.TOOL_NAME:
                    args = json.loads(tc.function.arguments or "{}")
                    return bool(args.get("need_view"))
        except Exception:
            self.log.exception("解析视觉决策工具调用失败")
        return False

    def build_tools(self) -> List[dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "判断是否需要调用视觉工具查看图片内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "need_view": {"type": "boolean", "description": "是否需要查看图片"},
                        "reason": {"type": "string", "description": "判断理由"},
                    },
                    "required": ["need_view"],
                },
            },
        }]

    def build_tool_choice(self) -> dict:
        return {"type": "function", "function": {"name": self.TOOL_NAME}}

    def _persona(self, username: str, current_message: str) -> str:
        """获取完整系统提示词（角色人设 + 价值观 + 记忆），保证视觉决策受角色约束"""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            return TBoxGetPrompt().get_system_prompt(username, current_message) or ""
        except Exception:
            return ""

    def _llm(self):
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
