# -*- coding: utf-8 -*-
# func/llm/llm_core.py
# LLM 编排入口 + 队列调度

import uuid
from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.gobal.data import LLmData

from func.llm.config import LLMConfig
from func.llm.port.deepseek import DeepSeekLLM
from func.llm.port.aliyun import AliyunLLM
from func.llm.message_get import MessageGet
from func.llm.prompt_get import PromptGet
from func.llm.message_builder import MessageBuilder
from func.llm.output import Output
from func.llm.emotion_controller import EmotionController


@singleton
class LLmCore:
    """LLM 核心编排：接收消息、构建上下文、调用模型、流式输出、表情控制"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = LLMConfig()
        self.local_llm_type = self.config.local_llm_type
        self.llmData = LLmData()

        # 选择流式 LLM 客户端
        self.llm = self._create_llm()

        # 输入清洗、提示词获取、短期记忆（持久复用）
        self.message_get = MessageGet(self.config)
        self.prompt_get = PromptGet()
        self.message_builder = MessageBuilder(self.config.short_term_rounds)

    def _create_llm(self):
        """根据配置创建流式 LLM 客户端"""
        if self.config.local_llm_type == "aliyun":
            return AliyunLLM(self.config)
        else:
            if self.config.local_llm_type != "deepseek":
                self.log.warning(f"未知 LLM 类型 {self.config.local_llm_type}，默认使用 deepseek")
            return DeepSeekLLM(self.config)

    def msg_deal(self, traceid: str, text: str, uid, username: str):
        """外部消息入口：正则清洗后放入问题队列"""
        cleaned = self.message_get.clean(text)
        if not cleaned:
            return
        llm_json = {"traceid": traceid, "prompt": cleaned, "uid": uid, "username": username}
        self.llmData.QuestionList.put(llm_json)
        self.log.info(f"[{traceid}] 消息入队: {cleaned}")

    def add_system_message(self, text: str, username: str = "主人", uid=0):
        """系统主动消息入口：直接放入问题队列"""
        traceid = str(uuid.uuid4())
        llm_json = {"traceid": traceid, "prompt": text, "uid": uid, "username": username}
        self.llmData.QuestionList.put(llm_json)
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
        """核心处理流程：取消息 → 构建 → 调 LLM → 流式输出与表情控制"""
        question_data = self.llmData.QuestionList.get()
        traceid = question_data["traceid"]
        prompt = question_data["prompt"]
        uid = str(question_data.get("uid", 0))
        username = question_data.get("username", "用户")

        # 获取系统提示词（来自 catbrain，暂未实现）
        system_prompt = self.prompt_get.get_system_prompt()

        # 构建完整消息：系统提示词 + 短期记忆（历史）+ 当前消息
        messages = self.message_builder.build_messages(uid, system_prompt, prompt)

        # 记录用户消息到短期记忆（供下一轮使用）
        self.message_builder.add_user_message(uid, prompt)

        # 每次对话新建带流式状态的处理器
        output = Output(self.config, self.llmData)
        emotion_controller = EmotionController()
        tools = emotion_controller.build_tools()

        # 调用 LLM 流式
        stream = self.llm.chat_stream(messages, tools=tools)

        # 逐块处理：文本走 output，tool_calls 走 emotion_controller
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                output.process_chunk(delta.content, traceid, prompt)
            if delta.tool_calls:
                emotion_controller.handle_stream_tool_calls(delta.tool_calls)

        # 结束流式，获取清理后的完整回复
        final_text = output.finalize(traceid, prompt)

        # 处理完整 tool_calls，传递情绪到 pipeline
        emotion_controller.finalize()

        # 记录助手回复到短期记忆
        if final_text:
            self.message_builder.add_assistant_message(uid, final_text)

        self.log.info(f"[{traceid}][AI回复]{final_text}")
        self.llmData.is_ai_ready = True
