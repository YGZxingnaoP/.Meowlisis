# -*- coding: utf-8 -*-
# func/toolbox/napcat/message/emote_choose.py
# 表情选择：开启深度思考，根据场景从 EmoteLab 选择合适表情

import os
import json
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
                            "description": "要发送的表情名称（必须从可用表情列表中选择）",
                        },
                    },
                    "required": ["emote_name"],
                },
            },
        }]

    def choose(self, username: str, text: str, reply_text: str, chat_record: List[dict]) -> str:
        """深度思考选择表情，返回表情名（不含 .gif），失败返回空串"""
        emotes = self._list_emotes()
        if not emotes:
            return ""
        scenes = self._load_scenes()
        scene_lines = "\n".join(f"- {k}：{v}" for k, v in scenes.items() if k in emotes)

        persona = self._persona()
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
            return ""
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == self.TOOL_NAME:
                    args = json.loads(tc.function.arguments)
                    name = str(args.get("emote_name", "") or "").strip()
                    if name in emotes:
                        return name
        except Exception:
            self.log.exception("解析表情选择工具调用失败")
        return ""

    def _persona(self) -> str:
        """获取角色卡提示词"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_character_prompt() or ""
        except Exception:
            return ""

    def _call(self, messages):
        """用 toolbox port 深度思考调用（复用 func/llm 配置）"""
        if self.llm_cfg.local_llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            llm = TBoxAliyunLLM(self.llm_cfg)
        else:
            from func.toolbox.port.deepseek import TBoxDeepSeekLLM
            llm = TBoxDeepSeekLLM(self.llm_cfg)
        if not llm.client:
            return None
        return llm.chat(messages, tools=self.build_tools(), enable_thinking=True)
