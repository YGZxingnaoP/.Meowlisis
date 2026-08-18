# -*- coding: utf-8 -*-
# func/llm/state.py
# LLM 运行时状态单例：消息队列与就绪标志

import queue

from func.tools.singleton_mode import singleton


@singleton
class LLmState:
    """LLM 运行态数据：跨线程共享的消息队列与流式状态标志"""

    # 待处理问题队列（元素：{"traceid","prompt","username"}）
    QuestionList = queue.Queue()

    # AI 回复队列（元素：TTS 所需的分段 JSON）
    AnswerList = queue.Queue()

    # AI 是否就绪（True 表示可接收下一条消息）
    is_ai_ready = True
