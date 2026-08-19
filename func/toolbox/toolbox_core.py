# -*- coding: utf-8 -*-
# func/toolbox/toolbox_core.py
# Toolbox 核心调度：整合 pipeline 桥接，统一分发输入与输出

from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.config import TBoxConfig
from func.toolbox.analysis import TBoxAnalysis
from func.toolbox.get_prompt import TBoxGetPrompt
from func.pipeline.sensevoice_toolbox import SenseVoiceToolboxBridge
from func.pipeline.toolbox_tts import ToolboxTtsBridge
from func.pipeline.toolbox_ltmem import ToolboxLtMemBridge
from func.pipeline.toolbox_llm import ToolboxLLMBridge
from func.pipeline.napcat_llm import NapcatLLMBridge
from func.pipeline.napcat_ltmem import NapcatLtMemBridge
from func.pipeline.short_memory import ShortMemory
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.napcat_core import TBNapCatCore


@singleton
class TBoxCore:
    """Toolbox 总入口：持有各 pipeline 桥接与父级分析器，统一分发"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self.analysis = TBoxAnalysis()
        self.get_prompt = TBoxGetPrompt()
        self.sensevoice_toolbox = SenseVoiceToolboxBridge()
        self.toolbox_tts = ToolboxTtsBridge()
        self.toolbox_ltmem = ToolboxLtMemBridge()
        self.toolbox_llm = ToolboxLLMBridge()
        self.napcat_llm = NapcatLLMBridge()
        self.napcat_ltmem = NapcatLtMemBridge()
        self.short_memory = ShortMemory()
        self.napcat_config = TBNapCatConfig()
        self.napcat_core = TBNapCatCore()

    def receive(self, text: str, username: str):
        """接收输入内容（来自 pipeline），交给 analysis 决策调用工具"""
        self.analysis.decide(text, username)

    def receive_qq(self, username: str, user_id: str, text: str, short_memory: list):
        """接收 QQ 私聊消息：记录记忆 → napcat 独立 LLM 回复 → 回发 QQ

        回复短句由本方法提供回调发送到 NapCat，napcat/llm 不直接操作发送，
        保证 napcat 只通过 toolbox_core 与 pipeline 与项目核心交互。
        """
        # 1. 记录用户消息短期记忆（qq_response，加前缀）
        if self.napcat_config.short_mem_enabled:
            self.short_memory.save({
                "role": "user",
                "content": f"【来自QQ的消息】{text}",
                "type": "qq_response",
            }, self.napcat_config.short_mem_rounds)
        # 2. 记录用户消息长期记忆（默认关闭）
        self.napcat_ltmem.record_user(username, text)
        # 3. napcat 独立 LLM 回复（流式短句回传发送）
        final_text = self.napcat_llm.send_to_llm(
            username, user_id, text, short_memory,
            on_segment=lambda seg: self.napcat_core.send_private_text(user_id, seg),
        )
        # 4. 记录 AI 回复短期记忆
        if final_text and self.napcat_config.short_mem_enabled:
            self.short_memory.save({
                "role": "assistant",
                "content": f"【来自QQ的消息】{final_text}",
                "type": "qq_response",
            }, self.napcat_config.short_mem_rounds)
        # 5. 记录 AI 回复长期记忆（默认关闭）
        if final_text:
            self.napcat_ltmem.record_ai(username, final_text)
        # 6. 表情触发（概率 = 配置概率 + 好感度）
        if final_text:
            self._maybe_send_emote(username, user_id, text, final_text, short_memory)
        # 7. 后置情绪更新（异步，与主链路一致，更新最新情绪/性格）
        if final_text:
            Thread(target=self._update_emotion_async, args=(text, final_text), daemon=True).start()

    def _maybe_send_emote(self, username: str, user_id: str, text: str,
                          final_text: str, short_memory: list):
        """表情触发（由 toolbox_core 统一调度，napcat 内部模块不直接碰发送）"""
        try:
            from func.toolbox.napcat.message.emote_sender import TBEmoteSender
            TBEmoteSender().maybe_send(username, user_id, text, final_text, short_memory)
        except Exception:
            self.log.exception("表情触发异常")

    def _update_emotion_async(self, prompt: str, reply_text: str):
        """后置情绪更新：复用 TBEmoteController，用 toolbox port 流式调用更新在线情绪"""
        try:
            from func.toolbox.napcat.emote_controller import TBEmoteController
            from func.llm.config import LLMConfig
            ec = TBEmoteController()
            tools = ec.build_tools()
            tool_choice = ec.build_tool_choice()
            update_messages = [
                {"role": "system", "content": "根据本轮对话，判断角色当前情绪、强度与性格。"},
                {"role": "user", "content": f"用户说：{prompt}\n角色回复：{reply_text}"}
            ]
            cfg = LLMConfig()
            if cfg.local_llm_type == "aliyun":
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
