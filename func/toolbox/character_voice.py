# -*- coding: utf-8 -*-
# func/toolbox/character_voice.py
# 角色口吻生成：把「程序内部要说的事」交给角色本人口播（toolbox 各模块复用）

import re

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.config import TBoxConfig

_BRACKETS = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")
_QUOTES = "\"'“”‘’「」『』"


def clean_line(text: str, max_chars: int = 60) -> str:
    """去掉括号旁白/引号/多余空白，截成一句口语的长度"""
    body = _BRACKETS.sub("", str(text or "")).replace("　", " ")
    body = " ".join(body.split()).strip(_QUOTES).strip()
    if max_chars and len(body) > max_chars:
        body = body[:max_chars].rstrip("，,、；;：: ")
    return body


@singleton
class TBoxCharacterVoice:
    """以角色本人身份说话：拼完整人设提示词，交给 toolbox 独立端口生成一句话

    - system_prompt：角色人设提示词（前置词 + 角色卡 + 价值观 + 后置词），保证是本人语气；
    - line：内部需求 → 一句角色口语，失败返回空串（由调用方决定兜底，绝不写死台词）；
    - chat：给需要结构化结果的调用方用的底层非流式入口。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self._llm = None

    def llm(self):
        """懒加载 toolbox 端口（与父级 toolcalls 同一套配置）"""
        if self._llm is None:
            from func.toolbox.port import create_toolbox_llm
            self._llm = create_toolbox_llm(self.config)
        return self._llm

    def system_prompt(self, meowid: str = "", current_message: str = "") -> str:
        """角色人设提示词（前置词+角色卡+价值观+后置词）

        用决策型提示词而不是对话型：后者会顺手消费破甲标记、启动心理线程，
        与主链路并发时会串台；口吻只取决于人设，决策型已经够用。
        """
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            return TBoxGetPrompt().get_tool_prompt(meowid, current_message) or ""
        except Exception:
            self.log.exception("[角色口吻] 读取系统提示词失败")
            return ""

    def chat(self, messages) -> str:
        """一次非流式生成，返回正文（端口不可用/异常返回空串）"""
        llm = self.llm()
        if llm is None or not getattr(llm, "client", None):
            return ""
        try:
            resp = llm.chat(messages, tools=None, enable_thinking=False)
        except Exception:
            self.log.exception("[角色口吻] 端口调用失败")
            return ""
        if not resp or not getattr(resp, "choices", None):
            return ""
        return str(getattr(resp.choices[0].message, "content", "") or "").strip()

    def line(self, need: str, meowid: str = "", history=None,
             max_chars: int = 60, avoid=()) -> str:
        """内部需求 → 一句角色口语；avoid 为最近说过的句子（强制换说法）"""
        system_prompt = self.system_prompt(meowid, need)
        if not system_prompt:
            return ""
        try:
            from func.pipeline.id_signup import display_name
            who = display_name(meowid) or "对方"
        except Exception:
            who = "对方"
        messages = [{"role": "system", "content": system_prompt}]
        for msg in (history or [])[-6:]:
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        parts = [f"（这是你自己的内部提示，不是{who}说的话）{need}",
                 f"用你自己的身份和平时说话的口气，把这件事对{who}说出口，只说一句。"]
        said = [str(s).strip() for s in (avoid or []) if str(s).strip()]
        if said:
            parts.append("你最近说过的：" + " / ".join(said[-6:]) + "。这次必须换个说法，不许重复。")
        parts.append(f"口语、自然、不超过{int(max_chars)}字；"
                     "不要括号旁白、不要表情符号、不要复述这段提示。")
        messages.append({"role": "user", "content": "\n".join(parts)})
        return clean_line(self.chat(messages), max_chars)
