# -*- coding: utf-8 -*-
# func/llm/llm_core.py
# LLM 编排入口 + 队列调度

import uuid
from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.llm.state import LLmState
from func.config.app_config import AppConfig

from func.llm.config import LLMConfig
from func.llm.port.deepseek import DeepSeekLLM
from func.llm.port.aliyun import AliyunLLM
from func.llm.message_get import MessageGet
from func.llm.prompt_get import PromptGet
from func.llm.message_builder import MessageBuilder
from func.llm.output import Output
from func.llm.emotion_controller import EmotionController
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.pipeline.short_memory import ShortMemory


@singleton
class LLmCore:
    """LLM 核心编排：接收消息、构建上下文、调用模型、流式输出、表情控制"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = LLMConfig()
        self.local_llm_type = self.config.local_llm_type
        self.llmData = LLmState()

        # 选择流式 LLM 客户端
        self.llm = self._create_llm()

        # 输入清洗、提示词获取、短期记忆（持久复用）
        self.message_get = MessageGet(self.config)
        self.prompt_get = PromptGet()
        self.message_builder = MessageBuilder(self.config.short_term_rounds)

        # 长期记忆桥接（记录用户消息与 AI 回复）
        self.ltmem = MeowLLMLtMemBridge()

    def _create_llm(self):
        """根据配置创建流式 LLM 客户端"""
        if self.config.local_llm_type == "gemini":
            from func.llm.port.gemini import GeminiLLM
            return GeminiLLM(self.config)
        if self.config.local_llm_type == "aliyun":
            return AliyunLLM(self.config)
        else:
            if self.config.local_llm_type != "deepseek":
                self.log.warning(f"未知 LLM 类型 {self.config.local_llm_type}，默认使用 deepseek")
            return DeepSeekLLM(self.config)

    def msg_deal(self, traceid: str, text: str, username: str, source: str = "llm",
                 preamble_text: str = "", multi_user: bool = False,
                 memory_config: dict = None):
        """外部消息入口：正则清洗后放入问题队列

        :param source: 来源标记（llm / danmaku），danmaku 走弹幕专用提示词
        :param preamble_text: 朗读前置段（弹幕朗读），回复前先送 TTS 朗读
        :param multi_user: 是否多用户弹幕（后置词用「挑选一些回复」）
        :param memory_config: 弹幕专属记忆配置（仅弹幕传，与其它模块隔离）
        """
        cleaned = self.message_get.clean(text)
        if not cleaned:
            return
        # 静默状态：只记用户消息，不生成回复
        from func.pipeline.silence_state import SilenceState
        if SilenceState().muted:
            self._record_silent(cleaned, username, source, memory_config)
            return
        llm_json = {
            "traceid": traceid,
            "prompt": cleaned,
            "username": username,
            "source": source,
            "preamble_text": preamble_text,
            "multi_user": multi_user,
            "memory_config": memory_config,
        }
        self.llmData.QuestionList.put(llm_json)
        # 通知主动回复模块：llm 收到用户消息
        from func.pipeline.llm_timer import LLMTimerBridge
        LLMTimerBridge().notify_user_message()
        self.log.info(f"[{traceid}] 消息入队: {cleaned}")

    def _record_silent(self, text: str, username: str, source: str = "llm",
                       memory_config: dict = None):
        """静默期间：仅记录用户消息（短期+长期+用户档案），不生成回复、不更新情绪。

        与 _ai_response 的记忆写入规则对齐：弹幕走弹幕记忆配置，其余走主链路记忆。
        """
        try:
            is_danmaku = (source == "danmaku")
            mc = memory_config or {}
            if is_danmaku:
                # 弹幕：长期记忆开关控制是否写长期+摘要+用户档案
                if mc.get("record_ltmem", True):
                    self.ltmem.record_user_message(username, text)
                else:
                    self.ltmem.record_user_profile(username, text)
                # 弹幕短期记忆（独立 type，按条裁剪）
                short_type = mc.get("short_type", "danmaku_response")
                short_mode = mc.get("short_mode", "items")
                short_limit = int(mc.get("short_limit", self.config.short_term_rounds))
                from func.pipeline.short_memory import ShortMemory
                ShortMemory().save(
                    {"role": "user", "content": text, "type": short_type},
                    short_limit, trim_mode=short_mode,
                )
            else:
                # 非弹幕：长期记忆/摘要/用户档案 + 短期记忆（other_talks 直写 JSON）
                self.ltmem.record_user_message(username, text)
                from func.pipeline.short_memory import ShortMemory
                formatted = self.message_builder.format_user_content(username, text)
                ShortMemory().save(
                    {"role": "user", "content": formatted, "type": "other_talks"},
                    50, trim_mode="items",
                )
            self.log.info(f"[静默] 已记录用户消息（不回复）: {text[:30]}")
        except Exception:
            self.log.exception("静默记录用户消息异常")

    def add_system_message(self, text: str, username: str = "主人"):
        """系统主动消息入口：直接放入问题队列"""
        traceid = str(uuid.uuid4())
        llm_json = {"traceid": traceid, "prompt": text, "username": username}
        self.llmData.QuestionList.put(llm_json)
        # 通知主动回复模块：llm 收到用户消息
        from func.pipeline.llm_timer import LLMTimerBridge
        LLMTimerBridge().notify_user_message()
        self.log.info(f"[{traceid}] 系统主动消息: {text}")

    def check_answer(self):
        """定时轮询：从问题队列取消息并异步处理"""
        if not self.llmData.QuestionList.empty() and self.llmData.is_ai_ready:
            self.llmData.is_ai_ready = False
            Thread(target=self._ai_response_safe).start()

    def _ai_response_safe(self):
        """安全包装处理，异常时恢复就绪状态"""
        try:
            self._ai_response()
        except Exception:
            self.log.exception("【ai_response】异常：")
            self.llmData.is_ai_ready = True

    def _ai_response(self):
        """核心处理流程：取消息 → 记录长期记忆 → 流式生成正文 → 后置情绪/性格工具更新 → 输出"""
        question_data = self.llmData.QuestionList.get()
        traceid = question_data["traceid"]
        prompt = question_data["prompt"]
        username = question_data.get("username") or "用户"
        source = question_data.get("source", "llm")
        preamble_text = question_data.get("preamble_text", "") or ""
        multi_user = bool(question_data.get("multi_user", False))

        # 弹幕专属记忆配置（仅弹幕传，其它模块完全隔离，不影响现有逻辑）
        mc = question_data.get("memory_config") or {}
        is_danmaku = (source == "danmaku")
        record_ltmem = bool(mc.get("record_ltmem", True))
        assistant_only = bool(mc.get("assistant_only", False))
        short_type = mc.get("short_type", "llm_fast_response")
        short_mode = mc.get("short_mode", "rounds")
        short_limit = int(mc.get("short_limit", self.config.short_term_rounds))

        # ===== 用户侧记忆（长期记忆 / 用户记忆） =====
        if is_danmaku:
            if not assistant_only:
                if record_ltmem:
                    self.ltmem.record_user_message(username, prompt)   # 长期+摘要+用户记忆
                else:
                    self.ltmem.record_user_profile(username, prompt)   # 仅用户记忆
        else:
            # 非弹幕：原有逻辑不变
            self.ltmem.record_user_message(username, prompt)

        # 获取系统提示词（弹幕来源走弹幕专用提示词，否则走主链路提示词）
        if is_danmaku:
            system_prompt = self.prompt_get.get_danmaku_prompt(username, prompt, multi_user)
        else:
            # 主线程破甲审查：命中色情则写 msg_rulebreak 桥接，构建提示词时注入原则词
            try:
                from func.catbrain.rules_break.rules_break import TBRulesBreak
                TBRulesBreak().check_and_store_msg(username, prompt, ShortMemory().load())
            except Exception:
                self.log.exception("主线程破甲审查异常")
            system_prompt = self.prompt_get.get_system_prompt(username, prompt)

        # 构建完整消息：系统提示词 + 短期记忆（历史）+ 当前消息
        messages = self.message_builder.build_messages(username, system_prompt, prompt)

        # ===== 用户侧短期记忆 =====
        if is_danmaku:
            # 弹幕短期记忆：独立 type，按条裁剪，直接写 json
            if not assistant_only:
                ShortMemory().save(
                    {"role": "user", "content": prompt, "type": short_type},
                    short_limit, trim_mode=short_mode,
                )
        else:
            self.message_builder.add_user_message(username, prompt)

        # 每次对话新建带流式状态的处理器（source 透传到 TTS：phone 语音不本地播放）
        output = Output(self.config, self.llmData, source=source)

        # 弹幕朗读前置段：先送 TTS 朗读（与回复共享 traceid，连续不插入）
        if preamble_text:
            output.send_preamble(preamble_text, traceid)

        # 第一阶段：直接流式生成正文（不再前置强制工具调用，降低首字延迟）
        stream = self.llm.chat_stream(messages)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                output.process_chunk(delta.content, traceid)

        # 结束流式，获取清理后的完整回复
        final_text = output.finalize(traceid)

        # 后置：异步调用工具更新情绪与性格（供下一轮 system prompt 使用，性格滞后一轮生效）
        if final_text:
            Thread(target=self._update_emotion_async, args=(prompt, final_text), daemon=True).start()

        # ===== 助手侧记忆（短期记忆 / 长期记忆 / 用户记忆） =====
        if is_danmaku:
            if final_text:
                # 弹幕短期记忆 assistant（按条裁剪）
                ShortMemory().save(
                    {"role": "assistant", "content": final_text, "type": short_type},
                    short_limit, trim_mode=short_mode,
                )
                if record_ltmem:
                    if assistant_only:
                        # 多弹幕统一回复：只记长期+摘要，不记用户记忆
                        self.ltmem.record_ltmem_only(AppConfig().ai_name, final_text)
                    else:
                        self.ltmem.record_ai_message(username, AppConfig().ai_name, final_text)
                else:
                    if not assistant_only:
                        # 长期记忆关闭，但用户记忆仍记录 assistant
                        self.ltmem.record_ai_profile(username, AppConfig().ai_name, final_text)
        else:
            if final_text:
                self.message_builder.add_assistant_message(username, final_text, AppConfig().ai_name)
            if final_text:
                self.ltmem.record_ai_message(username, AppConfig().ai_name, final_text)

        self.log.info(f"[{traceid}][AI回复]{final_text}")
        self.llmData.is_ai_ready = True
        # 通知主动回复模块：llm 完成回复
        from func.pipeline.llm_timer import LLMTimerBridge
        LLMTimerBridge().notify_ai_reply()

    def _update_emotion_async(self, prompt: str, reply_text: str):
        """后置情绪/性格更新：正文生成后单独调用工具，更新 latest_emotion.json"""
        try:
            emotion_controller = EmotionController()
            tools = emotion_controller.build_tools()
            tool_choice = emotion_controller.build_tool_choice()

            # 简短更新消息：仅本轮用户输入 + 角色回复
            update_messages = [
                {"role": "system", "content": "根据本轮对话，判断角色当前情绪、强度与性格。"},
                {"role": "user", "content": f"用户说：{prompt}\n角色回复：{reply_text}"}
            ]

            stream = self.llm.chat_stream(update_messages, tools=tools, tool_choice=tool_choice,
                                          enable_thinking=False)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.tool_calls:
                    emotion_controller.handle_stream_tool_calls(delta.tool_calls)

            if emotion_controller.tool_calls:
                emotion_controller.finalize()
        except Exception:
            self.log.exception("后置情绪更新异常")
