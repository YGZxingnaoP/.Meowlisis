# func/tts/subtitle.py
# 字幕处理线程：消费字幕队列，转入回复文本队列供前端轮询
import queue
import threading

from func.log.default_log import DefaultLog


class SubtitleWorker:
    """独立字幕线程，负责回复文本队列与浏览器字幕推送"""

    def __init__(self, tts_data, is_paused=None):
        self.log = DefaultLog().getLogger()
        self.tts_data = tts_data
        self.is_paused = is_paused or (lambda: False)
        self.queue = queue.Queue()
        self._thread = None

    def start(self):
        """启动字幕后台线程"""
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def put(self, reply_json):
        """字幕 JSON 入队"""
        self.queue.put(reply_json)

    def clear(self):
        """清空待处理字幕队列"""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _worker(self):
        """字幕消费线程：转入回复文本队列供前端轮询"""
        while True:
            reply_json = self.queue.get()
            if self.is_paused():
                continue
            self.tts_data.ReplyTextList.put(reply_json)
            self.log.info(reply_json)
