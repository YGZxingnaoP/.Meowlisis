# -*- coding: utf-8 -*-
# func/toolbox/napcat/reply/emote.py
# QQ 表情发送与情绪更新（自 func/toolbox/qq_response.py 原样拆出，行为不变）


class EmoteReplyMixin:
    """QQ 表情发送与情绪更新"""
    def _maybe_send_emote(self, username: str, user_id: str, text: str,
                          final_text: str, short_memory: list):
        """私聊表情触发（由 toolbox_core 统一调度，napcat 内部模块不直接碰发送）"""
        try:
            from func.toolbox.napcat.message.emote_sender import TBEmoteSender
            TBEmoteSender().maybe_send(username, user_id, text, final_text, short_memory, target_type="friend")
        except Exception:
            self.log.exception("表情触发异常")

    def _maybe_send_group_emote(self, parsed: dict, text: str, final_text: str, short_memory: list):
        """群聊表情触发（复用 message 表情系统，仅发送目标为群）

        - @ 触发：概率 = 配置概率 + 好感度（与私聊一致）；
        - 非 @ 触发：概率固定 = 配置概率（不叠加好感度）。
        """
        try:
            from func.toolbox.napcat.message.emote_sender import TBEmoteSender
            group_id = str(parsed.get("group_id", ""))
            username = str(parsed.get("username", "") or "")
            at_self = bool(parsed.get("at_self"))
            TBEmoteSender().maybe_send(
                username, group_id, text, final_text, short_memory,
                target_type="group", with_affinity=at_self,
            )
        except Exception:
            self.log.exception("群聊表情触发异常")

    def _update_emotion_async(self, prompt: str, reply_text: str):
        """后置情绪更新：复用 TBEmoteController，用 toolbox port 流式调用更新在线情绪"""
        try:
            from func.toolbox.napcat.emote_controller import TBEmoteController
            from func.llm.config import LLMConfig
            ec = TBEmoteController()
            tools = ec.build_tools()
            tool_choice = ec.build_tool_choice()
            update_messages = [
                {"role": "system", "content": (
                    "根据本轮对话判断角色此刻的情绪、强度与性格。情绪是此刻的瞬时表情，"
                    "会随每轮对话自然变化：默认 happy，只有本轮确实发生了对应情绪才选；"
                    "angry 需要有明确理由，普通吐槽、玩笑、傲娇、"
                    "被安排做事不算生气；情绪不激烈时用低强度表达，不要动辄切到极端情绪。"
                )},
                {"role": "user", "content": f"用户说：{prompt}\n角色回复：{reply_text}"}
            ]
            cfg = LLMConfig()
            # ⚠ 这里必须是 if/elif 一整条链：以前 meowllm 那支写成独立的 if，
            # 紧跟一个新开的 if/elif/else，结果 meowllm 建完立刻被 else 覆盖成
            # deepseek —— 配置写 meowllm 却一直在用 deepseek，且没有任何日志。
            if cfg.local_llm_type == "meowllm":
                from func.toolbox.port.meowllm import TBoxMeowLLM
                llm = TBoxMeowLLM(cfg)
            elif cfg.local_llm_type == "gemini":
                from func.toolbox.port.gemini import TBoxGeminiLLM
                llm = TBoxGeminiLLM(cfg)
            elif cfg.local_llm_type == "aliyun":
                from func.toolbox.port.aliyun import TBoxAliyunLLM
                llm = TBoxAliyunLLM(cfg)
            else:
                from func.toolbox.port.deepseek import TBoxDeepSeekLLM
                llm = TBoxDeepSeekLLM(cfg)
            if not llm.client:
                return
            stream = llm.chat_stream(
                update_messages, tools=tools, tool_choice=tool_choice, thinking_level="off"
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.tool_calls:
                    ec.handle_stream_tool_calls(delta.tool_calls)
            if ec.tool_calls:
                ec.finalize()
        except Exception:
            self.log.exception("napcat 后置情绪更新异常")
