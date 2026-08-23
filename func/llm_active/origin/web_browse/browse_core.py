# -*- coding: utf-8 -*-
# func/llm_active/origin/web_browse/browse_core.py
# B站内容收集总调度：独立后台线程，定时抓取→过滤→抽帧→视觉概括→落盘

import time
from threading import Thread
from typing import Dict

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.llm_active.origin.web_browse.config import AutoWebBrowseConfig
from func.llm_active.origin.web_browse.bili_client import AutoBiliClient
from func.llm_active.origin.web_browse.filter import AutoVideoFilter
from func.llm_active.origin.web_browse.keyframe import AutoKeyframe
from func.llm_active.origin.web_browse.store import AutoBrowseStore
from func.llm_active.origin.web_browse.topics import get_summary_topics, get_tags_pool
from func.llm_active.origin.vision.get_response import AutoVisionGetResponse


@singleton
class AutoBrowseCore:
    """主动回复 B站内容收集：独立线程定时执行，缓存满则停止补货"""

    MAX_ATTEMPTS = 3  # 单轮最多尝试的候选视频数
    RETRY_WAIT = 30   # 候选失败/不合适时的等待秒数

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = AutoWebBrowseConfig()
        self.client = AutoBiliClient()
        self.filter = AutoVideoFilter()
        self.keyframe = AutoKeyframe()
        self.store = AutoBrowseStore()
        self.vision = AutoVisionGetResponse()
        self._thread = None
        self._running = False

    # ==================== 生命周期 ====================
    def start(self):
        """启动后台采集线程（若配置关闭则跳过）"""
        if not self.config.enabled:
            self.log.info("[WebBrowse] 未启用，跳过启动")
            return
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log.info(f"[WebBrowse] 采集线程已启动，间隔 {self.config.interval}s")

    def stop(self):
        self._running = False

    # ==================== 主循环 ====================
    def _loop(self):
        while self._running:
            try:
                if self.store.is_full():
                    self.log.info("[WebBrowse] 缓存已满，本轮跳过")
                else:
                    self._collect_round()
            except Exception:
                self.log.exception("[WebBrowse] 采集轮异常")
            self._sleep(self.config.interval)

    def _collect_round(self):
        """单轮采集：最多尝试 MAX_ATTEMPTS 个候选，成功入库 1 个即结束"""
        for i in range(self.MAX_ATTEMPTS):
            if not self._running:
                return
            if self.store.is_full():
                return
            ok = self._collect_one()
            if ok:
                self.log.info(f"[WebBrowse] 本轮采集成功（第 {i + 1} 个候选）")
                return
            self.log.info(f"[WebBrowse] 候选 {i + 1} 失败/不合适，{self.RETRY_WAIT}s 后换下一个")
            self._sleep(self.RETRY_WAIT)

    # ==================== 单个候选完整流程 ====================
    def _collect_one(self) -> bool:
        video = self.client.fetch_candidate()
        if not video:
            return False

        # 主题过滤（LLM 语义判断）
        decision = self.filter.is_suitable(video)
        if not decision.get("suitable"):
            self.log.info(
                f"[WebBrowse] 视频不合适: {video.get('title', '')[:30]} "
                f"reason={decision.get('reason', '')}"
            )
            return False

        # 流式抽帧（n 等分，每段随机一帧）
        frames = self.keyframe.extract(
            video.get("stream_url", ""),
            video.get("duration_sec", 0),
            self.config.frames,
        )
        if not frames:
            self.log.info(f"[WebBrowse] 抽帧失败，舍弃: {video.get('title', '')[:30]}")
            return False

        # 视觉概括（帧用后即删）
        try:
            result = self.vision.analyze(
                frames, video, get_summary_topics(), get_tags_pool()
            )
        finally:
            self.keyframe.cleanup(frames)

        content = str(result.get("content") or "").strip()
        if not content:
            self.log.info(f"[WebBrowse] 视觉概括为空，舍弃: {video.get('title', '')[:30]}")
            return False

        item = self._build_item(video, result)
        path = self.store.save(item)
        if path:
            self.log.info(f"[WebBrowse] 已入库: {item.get('title', '')[:30]} -> {path}")
            return True
        return False

    @staticmethod
    def _build_item(video: Dict, result: Dict) -> Dict:
        """组装最终 json 结构"""
        return {
            "url": video.get("url", ""),
            "title": video.get("title", ""),
            "introduction": video.get("introduction", ""),
            "len": video.get("len", ""),
            "uploader": video.get("uploader", ""),
            "label": video.get("label", ""),
            "content": str(result.get("content") or "").strip(),
            "topic": str(result.get("topic") or "日常").strip(),
            "tags": list(result.get("tags") or [])[:3],
        }

    # ==================== 工具 ====================
    def _sleep(self, seconds: int):
        """分片等待，便于 stop 及时生效"""
        seconds = max(1, int(seconds))
        end = time.time() + seconds
        while self._running and time.time() < end:
            time.sleep(min(1, max(0.1, end - time.time())))
