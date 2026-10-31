# -*- coding: utf-8 -*-
# func/toolbox/napcat/llm/napcat_group_llm.py
# NapCat 群聊独立 LLM 回复链路：复用私聊过滤/切分，群聊提示词 + pass 决策 + ask_group_bot 工具

import json
from typing import List, Optional, Callable

from func.log.default_log import DefaultLog
from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM
from func.toolbox.napcat.message.time_split import is_marker


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
                cleaned = cls._clean_segment(out)
                if cleaned:
                    segs.append(cleaned)
                out = ""
            else:
                out += ch
        cleaned = cls._clean_segment(out)
        if cleaned:
            segs.append(cleaned)
        return segs

    def _system_prompt(self, username, group_name, group_info_text, current_message,
                       group_id: str = "", decide: bool = False, with_bot_tool: bool = False,
                       with_director: bool = False, extra_context: str = "") -> str:
        """获取群聊系统提示词；decide=True 时追加回复决策指令

        with_director=True 时附上 QQ 导演走向块（只在 @ / 续聊回复时传，冒泡 decide 永远不传）。
        """
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            prompt = SystemPromptBridge().get_napcat_group_prompt(
                uid=username, group_name=group_name,
                group_info_text=group_info_text, current_message=current_message,
                group_id=group_id,
            )
            block = str(extra_context or "").strip()
            if block:
                prompt = (
                    f"{prompt}\n\n【插件资料·仅作参考】\n{block}\n【资料结束】\n"
                    "只把资料当参考，不要照念、不要提“插件/资料”，不要逐条复述。"
                )
            if decide:
                if with_bot_tool:
                    prompt = (
                        f"{prompt}\n\n"
                        f"【回复决策】你的默认动作是不说话（输出 pass）。\n"
                        f"1. 如果满足条件（群机器人之前发过言），调用 ask_group_bot 工具向群机器人发指令活跃气氛；\n"
                        f"2. 如果觉得需要直接插话，输出你的回复内容；\n"
                        f"3. 如果不需要任何动作，只输出一个词：pass。"
                    )
                else:
                    prompt = (
                        f"{prompt}\n\n"
                        f"【回复决策】你的默认动作是不说话（输出 pass）。"
                        f"如果你觉得不需要回复，只输出一个词：pass；"
                        f"如果需要回复，请直接输出你要回复的内容。"
                    )
            if with_director and not decide and group_id:
                try:
                    from func.toolbox.napcat.director.block import attach_block
                    prompt = attach_block(prompt, f"qq_group:{group_id}")
                except Exception:
                    self.log.exception("注入 QQ 导演块失败（群聊）")
            return prompt
        except Exception:
            self.log.exception("获取 napcat 群聊系统提示词失败")
            return ""

    def _messages(self, username, group_name, group_info_text, text, short_memory, decide,
                  group_id: str = "", with_bot_tool: bool = False, quote: Optional[str] = None,
                  with_director: bool = False, extra_context: str = ""):
        system_prompt = self._system_prompt(username, group_name, group_info_text, text,
                                           group_id, decide, with_bot_tool, with_director,
                                           extra_context=extra_context)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        # 群记录里也含“当前这条”，再当当前输入传一遍会变成说两遍（模型会回“你重复两遍”）
        for m in TBNapCatLLM._drop_current_from_history(short_memory, text):
            if (m.get("role") in ("user", "assistant") or is_marker(m)) and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        if quote:
            messages.append({"role": "user", "content": (
                f"【TA引用了你的这句话】{quote}\n【TA接着说】{text}\n"
                f"TA 是在接着你上面那句话说的，直接回应，不要重复那句话。"
            )})
        else:
            messages.append({"role": "user", "content": text})
        return messages

    def _at_tools(self) -> List[dict]:
        try:
            from func.toolbox.napcat.groupchat.group_at import TBGroupAt
            return TBGroupAt().build_tools()
        except Exception:
            self.log.exception("构建 group_at 工具失败")
            return []

    def _generate_with_tools(self, messages: List[dict], group_id: str,
                             tools: List[dict]):
        llm, _ = self._llm()
        if llm is None or not llm.client:
            self.log.error("NapCat 群聊回复 LLM 不可用")
            return "", None
        try:
            resp = llm.chat(messages, tools=tools, tool_choice="auto", enable_thinking=False)
        except Exception:
            self.log.exception("群聊带工具回复失败，回退流式回复")
            return self._generate(messages), None
        if not resp or not resp.choices:
            self.log.warning("群聊带工具回复为空，回退流式回复")
            return self._generate(messages), None
        msg = resp.choices[0].message
        target = None
        for tc in (msg.tool_calls or []):
            if tc.function.name != "group_at":
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            from func.toolbox.napcat.groupchat.group_at import TBGroupAt
            target = TBGroupAt().resolve(group_id, args.get("member", ""))
            if target is None:
                self.log.warning(f"[群聊@] 未找到成员 {args.get('member')!r}，按普通消息发送")
            break
        return self.remove_analysis(msg.content or "").strip(), target

    def reply(self, username: Optional[str], group_id: str, group_name: str, text: str,
              short_memory: List[dict], group_info_text: str = "",
              on_segment: Optional[Callable[[str], None]] = None,
              nsfw: bool = False, quote: Optional[str] = None,
              with_director: bool = False, extra_context: str = "") -> str:
        """@ 触发或强制回复：生成并回传短句，返回完整回复

        nsfw=True 时切割减小（不按逗号切），一段容纳更多内容。
        with_director=True 时把 QQ 导演走向块附到 system 提示词（只用于 @ / 续聊）。
        """
        self._nsfw_split = bool(nsfw)
        try:
            tools = self._at_tools()
            messages = self._messages(username, group_name, group_info_text, text, short_memory,
                                      decide=False, group_id=group_id, quote=quote,
                                      with_director=with_director, extra_context=extra_context)
            if tools and messages and messages[0].get("role") == "system":
                messages[0]["content"] += (
                    "\ngroup_at 是可选的：默认不要 @ 人，大多数回复直接说就行；"
                    "只有确实要单独对某个群成员说话、需要他看到时才调用（member 填他的群名片或 QQ 号）")
            if tools:
                raw, target = self._generate_with_tools(messages, group_id, tools)
            else:
                raw, target = self._generate(messages), None
            final = self._clean_reply(raw)
            final = self._rewrite_if_too_long(messages, final,
                                              self.napcat_cfg.word_count_for("group"), channel="group")
            segments = self.split_segments(final)
            if target and on_segment:
                from func.toolbox.napcat.groupchat.group_at import TBGroupAt
                TBGroupAt().send(group_id, target, segments[0] if segments else "")
                segments = segments[1:]
            for seg in segments:
                if on_segment and seg:
                    on_segment(seg)
            self.log.info(f"[NapCat群聊] 回复 {group_name}: {final[:50]}...")
            return final
        finally:
            self._nsfw_split = False

    def decide(self, username: Optional[str], group_id: str, group_name: str, text: str,
               short_memory: List[dict], group_info_text: str = "",
               ask_bot_tools: Optional[List[dict]] = None, extra_context: str = "") -> str:
        """阈值触发：判断是否插话 / 是否调用 ask_group_bot / 输出 pass。

        - 若模型调用 ask_group_bot 工具，返回 "ASK_BOT:结果"（上层不再文本回复）；
        - 若输出 pass，返回 "pass"；
        - 否则返回完整回复内容。
        """
        if ask_bot_tools:
            return self._decide_with_tools(
                username, group_name, group_info_text, text, short_memory, group_id, ask_bot_tools,
                extra_context=extra_context
            )
        return self._run(username, group_name, group_info_text, text, short_memory,
                         group_id=group_id, decide=True, on_segment=None,
                         extra_context=extra_context)

    def _decide_with_tools(self, username, group_name, group_info_text, text,
                           short_memory, group_id: str = "", ask_bot_tools=None,
                           extra_context: str = "") -> str:
        """非流式 decide：支持 ask_group_bot 工具调用"""
        llm, base_max_tokens = self._llm()
        if llm is None or not llm.client:
            self.log.error("NapCat 群聊回复 LLM 不可用")
            return ""
        messages = self._messages(username, group_name, group_info_text, text, short_memory,
                                  decide=True, group_id=group_id, with_bot_tool=True,
                                  extra_context=extra_context)
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
             decide: bool, on_segment, group_id: str = "", extra_context: str = "") -> str:
        messages = self._messages(username, group_name, group_info_text, text, short_memory,
                                  decide, group_id=group_id, extra_context=extra_context)
        final = self._clean_reply(self._generate(messages))
        if final and final.strip().lower() != "pass" and not final.startswith("ASK_BOT:"):
            final = self._rewrite_if_too_long(messages, final,
                                              self.napcat_cfg.word_count_for("group"), channel="group")
        for seg in self.split_segments(final):
            if on_segment and seg:
                on_segment(seg)
        self.log.info(f"[NapCat群聊] 回复 {group_name}: {final[:50]}...")
        return final
