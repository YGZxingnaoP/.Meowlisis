# func/tts/subtitle.py
# 字幕处理线程：消费字幕队列 + 推送浏览器完整字幕
import queue
import threading

from func.log.default_log import DefaultLog


class SubtitleWorker:
    """独立字幕线程，负责回复文本队列与浏览器字幕推送"""

    def __init__(self, tts_data, subtitle_server, is_paused=None):
        self.log = DefaultLog().getLogger()
        self.tts_data = tts_data
        self.subtitle_server = subtitle_server
        self.is_paused = is_paused or (lambda: False)
        self.queue = queue.Queue()
        self.current_full_subtitle = None
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

    def send_full_text(self, text):
        """推送完整回复字幕到浏览器（同文本去重）"""
        if not text or text == self.current_full_subtitle:
            return
        self.current_full_subtitle = text
        try:
            self.subtitle_server.send_subtitle(text)
        except Exception as e:
            self.log.error(f"发送字幕失败: {e}")

    def _worker(self):
        """字幕消费线程：转入回复文本队列供前端轮询"""
        while True:
            reply_json = self.queue.get()
            if self.is_paused():
                continue
            self.tts_data.ReplyTextList.put(reply_json)
            self.log.info(reply_json)
