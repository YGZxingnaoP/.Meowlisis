# -*- coding: utf-8 -*-
# func/tts/state.py
# TTS 运行时状态单例：锁、回复队列与任务队列

import queue
import threading

from func.tools.singleton_mode import singleton


@singleton
class TTsState:
    """TTS 运行态数据：跨线程共享的锁、回复队列与任务队列"""

    # 回复文本队列（供前端轮询）
    ReplyTextList = queue.Queue()

    # ============ TTS 任务队列（按 traceid 分组串行） ============
    # 任务自增 ID 与锁
    task_lock = threading.Lock()
    task_counter = 0
    # 待处理任务队列（FIFO），元素为 {"task_id","traceid","source","segments","generation"}
    task_queue = queue.Queue()
    # 任务代际：打断/暂停时 +1，用于丢弃已过时的任务
    generation = 0
