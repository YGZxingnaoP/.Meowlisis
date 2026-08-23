# -*- coding: utf-8 -*-
# func/llm_active/origin/web_browse/bili_client.py
# B站客户端：复用 danmaku 登录态（SESSDATA/bili_jct）封装 bilibili_api 的同步调用

import asyncio
import random
from typing import Dict, Optional

from func.log.default_log import DefaultLog
from func.llm_active.origin.web_browse.config import AutoWebBrowseConfig


class AutoBiliClient:
    """封装 bilibili_api 的异步调用，对外提供同步方法（内部 asyncio.run）。

    - 登录态复用 danmaku.blivedm.sessdata / bili_jct；
    - 随机抓取「自己账号首页」的一个投稿视频；
    - 返回视频元信息 + 可抽帧的流地址。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = AutoWebBrowseConfig()
        self.sessdata, self.bili_jct = self._load_credential()

    @staticmethod
    def _load_credential():
        """从 danmaku.blivedm 节点读取 SESSDATA / bili_jct"""
        from func.pipeline.config_reader import ConfigReader
        cfg = ConfigReader().get('danmaku', {})
        blivedm = cfg.get('blivedm', {}) if isinstance(cfg, dict) else {}
        sessdata = str(blivedm.get('sessdata', '') or '').strip()
        bili_jct = str(blivedm.get('bili_jct', '') or '').strip()
        return sessdata, bili_jct

    def _credential(self):
        from bilibili_api import Credential
        return Credential(sessdata=self.sessdata, bili_jct=self.bili_jct)

    # ==================== 对外同步入口 ====================
    def fetch_candidate(self) -> Optional[Dict]:
        """随机抓取一个投稿视频的元信息 + 流地址，失败返回 None"""
        if not self.sessdata:
            self.log.warning("[WebBrowse] 未配置 B站 SESSDATA，无法抓取账号首页视频")
            return None
        try:
            return asyncio.run(self._fetch_candidate_async())
        except Exception:
            self.log.exception("[WebBrowse] 抓取视频候选异常")
            return None

    # ==================== 异步实现 ====================
    async def _fetch_candidate_async(self) -> Optional[Dict]:
        from bilibili_api import user, video

        mid = await self._resolve_mid_async()
        if not mid:
            return None

        # 1. 随机取一个投稿视频
        u = user.User(mid, credential=self._credential())
        resp = await u.get_videos(ps=30)
        vlist = ((resp or {}).get("list") or {}).get("vlist") or []
        if not vlist:
            self.log.warning(f"[WebBrowse] mid={mid} 无投稿视频")
            return None

        item = random.choice(vlist)
        bvid = str(item.get("bvid") or "").strip()
        if not bvid:
            return None

        # 2. 拿视频信息
        v = video.Video(bvid=bvid, credential=self._credential())
        info = await v.get_info()
        if not info:
            return None

        cid = self._first_cid(info)
        title = str(info.get("title") or "").strip()
        desc = str(info.get("desc") or "").strip()
        duration = int(info.get("duration") or 0)
        owner_name = str((info.get("owner") or {}).get("name") or "").strip()

        # 3. 视频自身标签
        label = ""
        if cid:
            try:
                tags = await v.get_tags(cid=cid)
                names = [str(t.get("tag_name") or "").strip() for t in (tags or [])]
                label = "、".join([n for n in names if n])
            except Exception:
                self.log.exception("[WebBrowse] 获取视频标签失败")
        if not label:
            label = str(info.get("tname") or "").strip()

        # 4. 流地址（html5 mp4，抽帧用）
        stream_url = await self._get_stream_url(v)

        return {
            "bvid": bvid,
            "url": f"https://www.bilibili.com/video/{bvid}",
            "title": title,
            "introduction": desc,
            "len": self._format_duration(duration),
            "duration_sec": duration,
            "uploader": owner_name,
            "label": label,
            "stream_url": stream_url,
        }

    async def _resolve_mid_async(self) -> Optional[int]:
        from bilibili_api import user
        if self.config.mid > 0:
            return self.config.mid
        info = await user.get_self_info(self._credential())
        return int((info or {}).get("mid") or 0) or None

    @staticmethod
    def _first_cid(info: Dict) -> Optional[int]:
        cid = info.get("cid")
        if cid:
            return int(cid)
        pages = info.get("pages") or []
        if pages:
            return int(pages[0].get("cid") or 0) or None
        return None

    @staticmethod
    def _format_duration(seconds: int) -> str:
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h}小时{m}分{s}秒"
        if m > 0:
            return f"{m}分{s}秒"
        return f"{s}秒"

    async def _get_stream_url(self, v) -> Optional[str]:
        """取 html5 mp4 流地址，失败返回 None"""
        try:
            data = await v.get_download_url(page_index=0, html5=True)
        except Exception:
            self.log.exception("[WebBrowse] 获取视频流地址失败")
            return None
        durl = (data or {}).get("durl") or []
        if not durl:
            return None
        url = str(durl[0].get("url") or "").strip()
        return url or None
