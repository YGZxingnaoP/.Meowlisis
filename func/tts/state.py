# -*- coding: utf-8 -*-
# func/tts/state.py
# TTS 运行时状态单例：合成计数与回复文本队列

import queue
import threading

from func.tools.singleton_mode import singleton


@singleton
class TTsState:
    """TTS 运行态数据：跨线程共享的合成计数、锁与回复队列"""

    # 语音合成计数（用于生成唯一文件名）
    SayCount = 0

    # 合成计数锁
    say_lock = threading.Lock()

    # 回复文本队列（供前端轮询）
    ReplyTextList = queue.Queue()

    # 语音是否生成完成标志
    is_tts_ready = True
