# -*- coding: utf-8 -*-
# func/tts/state.py
# TTS 运行时状态单例：合成计数、锁、回复队列与任务队列

import queue
import threading

from func.tools.singleton_mode import singleton


@singleton
class TTsState:
    """TTS 运行态数据：跨线程共享的合成计数、锁、回复队列与任务队列"""

    # 语音合成计数（用于生成唯一文件名）
    SayCount = 0

    # 合成计数锁
    say_lock = threading.Lock()

    # 回复文本队列（供前端轮询）
    ReplyTextList = queue.Queue()

    # 语音是否生成完成标志
    is_tts_ready = True

    # ============ TTS 任务队列（按 traceid 分组串行） ============
    # 任务自增 ID 与锁
    task_lock = threading.Lock()
    task_counter = 0
    # 正在接收中的句子缓冲：traceid -> task（同一 traceid 的分段归到同一任务）
    pending_tasks = {}
    # 待处理任务队列（FIFO），元素为 {"task_id","traceid","source","segments","generation"}
    task_queue = queue.Queue()
    # 任务代际：打断/暂停时 +1，用于丢弃已过时的任务
    generation = 0
