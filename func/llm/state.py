# -*- coding: utf-8 -*-
# func/llm/state.py
# LLM 运行时状态单例：消息队列、就绪标志与打断代际

import queue
import threading

from func.tools.singleton_mode import singleton


@singleton
class LLmState:
    """LLM 运行态数据：跨线程共享的消息队列与流式状态标志"""

    # 待处理问题队列（元素：{"traceid","prompt","uid"}）
    QuestionList = queue.Queue()

    # AI 回复队列（元素：TTS 所需的分段 JSON）
    AnswerList = queue.Queue()

    # AI 是否就绪（True 表示可接收下一条消息）
    is_ai_ready = True

    # 打断代际：用户开口/新消息到达时 +1，正在生成的回答看到代际变了就收手
    abort_epoch = 0
    abort_lock = threading.Lock()

    def bump_abort(self) -> int:
        """打断当前生成（用户开口/新消息到达），返回新代际"""
        with self.abort_lock:
            LLmState.abort_epoch += 1
            return LLmState.abort_epoch

    def abort_token(self) -> int:
        """取当前代际（生成开始前记下它）"""
        return LLmState.abort_epoch

    def aborted(self, token: int) -> bool:
        """这一轮是否已被打断"""
        return LLmState.abort_epoch != token
