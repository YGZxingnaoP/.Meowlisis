# -*- coding: utf-8 -*-
# func/toolbox/napcat/llm/napcat_group_llm.py
# NapCat 群聊独立 LLM 回复链路：复用私聊过滤/切分，群聊提示词 + pass 决策 + ask_group_bot 工具

import json
from typing import List, Optional, Callable

from func.log.default_log import DefaultLog
from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM


class TBNapCatGroupLLM(TBNapCatLLM):
    """群聊回复 LLM：继承私聊的流式过滤与短句切分，使用群聊提示词与 pass 决策。

    本类不直接发送消息；短句通过 on_segment 回调回传，由上层统一发送到群。
    """

    def __init__(self):
        super().__init__()
        self.log = DefaultLog().getLogger()

    @classmethod
    def split_segments(cls, text: str) -> List[str]:
        """对完整回复文本做与 message 一致的分段：按逗号/句号/问号切分并忽略标点，感叹号保留不切分"""
        if not text:
            return []
        segs = []
        out = ""
        for ch in text:
            if ch in cls.SPLIT_IGNORE:
                if out.strip():
                    segs.append(out.strip())
                out = ""
            else:
                out += ch
        if out.strip():
            segs.append(out.strip())
        return segs

    def _system_prompt(self, username, group_name, group_info_text, current_message,
                       decide: bool = False, with_bot_tool: bool = False) -> str:
        """获取群聊系统提示词；decide=True 时追加回复决策指令"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            prompt = SystemPromptBridge().get_napcat_group_prompt(
                username=username, group_name=group_name,
                group_info_text=group_info_text, current_message=current_message,
            )
            if decide:
                if with_bot_tool:
                    prompt = (
                        f"{prompt}\n\n"
                        f"【回复决策】当前群聊没有明显话题时，你可以选择：\n"
                        f"1. 如果满足条件（群机器人之前发过言），调用 ask_group_bot 工具向群机器人发指令活跃气氛；\n"
                        f"2. 如果觉得需要直接插话，输出你的回复内容；\n"
                        f"3. 如果不需要任何动作，只输出一个词：pass。"
                    )
                else:
                    prompt = (
                        f"{prompt}\n\n"
                        f"【回复决策】请判断当前群聊是否值得你插话回复。"
                        f"如果你觉得不需要回复，只输出一个词：pass；"
                        f"如果需要回复，请直接输出你要回复的内容。"
                    )
            return prompt
        except Exception:
            self.log.exception("获取 napcat 群聊系统提示词失败")
            return ""

    def _messages(self, username, group_name, group_info_text, text, short_memory, decide,
                  with_bot_tool: bool = False):
        system_prompt = self._system_prompt(username, group_name, group_info_text, text,
                                           decide, with_bot_tool)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in short_memory or []:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": text})
        return messages

    def reply(self, username: Optional[str], group_id: str, group_name: str, text: str,
              short_memory: List[dict], group_info_text: str = "",
              on_segment: Optional[Callable[[str], None]] = None) -> str:
        """@ 触发或强制回复：流式生成并回传短句，返回完整回复"""
        return self._run(username, group_name, group_info_text, text, short_memory,
                         decide=False, on_segment=on_segment)

    def decide(self, username: Optional[str], group_id: str, group_name: str, text: str,
               short_memory: List[dict], group_info_text: str = "",
               ask_bot_tools: Optional[List[dict]] = None) -> str:
        """阈值触发：判断是否插话 / 是否调用 ask_group_bot / 输出 pass。

        - 若模型调用 ask_group_bot 工具，返回 "ASK_BOT:结果"（上层不再文本回复）；
        - 若输出 pass，返回 "pass"；
        - 否则返回完整回复内容。
        """
        # 带 ask_group_bot 工具时用非流式（可稳定拿到 tool_calls）
        if ask_bot_tools:
            return self._decide_with_tools(
                username, group_name, group_info_text, text, short_memory, ask_bot_tools
            )
        return self._run(username, group_name, group_info_text, text, short_memory,
                         decide=True, on_segment=None)

    def _decide_with_tools(self, username, group_name, group_info_text, text,
                           short_memory, ask_bot_tools) -> str:
        """非流式 decide：支持 ask_group_bot 工具调用"""
        llm, base_max_tokens = self._llm()
        if llm is None or not llm.client:
            self.log.error("NapCat 群聊回复 LLM 不可用")
            return ""
        messages = self._messages(username, group_name, group_info_text, text, short_memory,
                                  decide=True, with_bot_tool=True)
        old_max = getattr(llm, "max_tokens", None)
        try:
            llm.max_tokens = max(512, int(base_max_tokens) + 256)
            resp = llm.chat(messages, tools=ask_bot_tools, enable_thinking=False)
        finally:
            if old_max is not None:
                llm.max_tokens = old_max
        if not resp or not resp.choices:
            return ""
        msg = resp.choices[0].message
        # 工具调用：ask_group_bot
        for tc in (msg.tool_calls or []):
            if tc.function.name == "ask_group_bot":
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                from func.toolbox.napcat.groupchat.ask_group_bot import TBAskGroupBot
                result = TBAskGroupBot().dispatch("ask_group_bot", args)
                self.log.info(f"[NapCat群聊] ask_group_bot 结果: {result}")
                return f"ASK_BOT:{result}"
        content = (msg.content or "").strip()
        return self.remove_analysis(content).strip()

    def _run(self, username, group_name, group_info_text, text, short_memory,
             decide: bool, on_segment) -> str:
        llm, base_max_tokens = self._llm()
        if llm is None or not llm.client:
            self.log.error("NapCat 群聊回复 LLM 不可用")
            return ""
        if self._max_tokens is None:
            self._max_tokens = max(8, int(base_max_tokens) + 128)
        self._reset_filter()

        messages = self._messages(username, group_name, group_info_text, text, short_memory, decide)
        stream = llm.chat_stream(
            messages,
            options={"max_tokens": self._max_tokens},
            thinking_level=self.napcat_cfg.thinking_level,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not delta.content:
                continue
            for ch in delta.content:
                self._feed(ch)
            for seg in self._split():
                if on_segment:
                    on_segment(seg)
        if self._tag:
            self._flush_tag()
        if self._temp.strip():
            seg = self._temp.strip()
            self._temp = ""
            if on_segment:
                on_segment(seg)

        final = self.remove_analysis(self._filtered).strip()
        self.log.info(f"[NapCat群聊] 回复 {group_name}: {final[:50]}...")
        return final
