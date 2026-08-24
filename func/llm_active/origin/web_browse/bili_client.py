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

    - 登录态复用 llm_active.web_browse（回退 danmaku.blivedm）的 SESSDATA / bili_jct；
    - 从 B站「首页推荐流」随机抓一个视频（每次刷新可换，等价于打开 bilibili.com 首页）；
    - 返回视频元信息 + 可抽帧的流地址。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = AutoWebBrowseConfig()
        # 启用 bili_ticket，应对 B站 412 安全风控（需在发请求前设置）
        try:
            from bilibili_api import request_settings
            request_settings.set_enable_bili_ticket(True)
        except Exception:
            pass
        self.sessdata, self.bili_jct = self._load_credential()

    @staticmethod
    def _load_credential():
        """读取 B站登录态：优先 llm_active.web_browse 独立配置，回退 danmaku.blivedm"""
        from func.pipeline.config_reader import ConfigReader
        cfg = ConfigReader().get('llm_active', {})
        wb = cfg.get('web_browse', {}) if isinstance(cfg, dict) else {}
        sessdata = str(wb.get('sessdata', '') or '').strip()
        bili_jct = str(wb.get('bili_jct', '') or '').strip()

        if not sessdata or not bili_jct:
            danmaku = ConfigReader().get('danmaku', {})
            blivedm = danmaku.get('blivedm', {}) if isinstance(danmaku, dict) else {}
            sessdata = sessdata or str(blivedm.get('sessdata', '') or '').strip()
            bili_jct = bili_jct or str(blivedm.get('bili_jct', '') or '').strip()
        return sessdata, bili_jct

    def _credential(self):
        from bilibili_api import Credential
        return Credential(sessdata=self.sessdata, bili_jct=self.bili_jct)

    # ==================== 对外同步入口 ====================
    def fetch_candidate(self) -> Optional[Dict]:
        """随机抓取一个「首页推荐」视频的元信息 + 流地址，失败返回 None"""
        if not self.sessdata:
            self.log.warning("[WebBrowse] 未配置 B站 SESSDATA，首页推荐可能为空/非个性化，仍尝试抓取")
        try:
            return asyncio.run(self._fetch_candidate_async())
        except Exception:
            self.log.exception("[WebBrowse] 抓取视频候选异常")
            return None

    # ==================== 异步实现 ====================
    async def _fetch_home_feed(self, ps: int = 30) -> list:
        """调用 B站首页推荐接口，返回推荐视频列表（刷新可换）"""
        from bilibili_api.utils.network import Api
        api = Api(
            url="https://api.bilibili.com/x/web-interface/wbi/index/top/feed/rcmd",
            method="GET",
            credential=self._credential(),
            wbi=True,
            no_csrf=True,
        )
        try:
            resp = await api.update_params(
                ps=ps,
                fresh_idx=1,
                brush=1,
                homepage_ver=1,
                fetch_row=1,
                fresh_idx_1h=1,
            ).result
        except Exception as e:
            self.log.warning(f"[WebBrowse] 获取首页推荐失败: {e}")
            return []
        # bilibili_api 的 result 已解包 code/data，resp 即 data 部分
        return (resp or {}).get("item") or []

    async def _fetch_candidate_async(self) -> Optional[Dict]:
        from bilibili_api import video

        # 1. 从首页推荐流随机取一个视频
        items = await self._fetch_home_feed()
        if not items:
            self.log.warning("[WebBrowse] 首页推荐为空")
            return None

        item = random.choice(items)
        bvid = str(item.get("bvid") or "").strip()
        if not bvid:
            return None

        # 2. 拿视频信息
        v = video.Video(bvid=bvid, credential=self._credential())
        try:
            info = await v.get_info()
        except Exception as e:
            self.log.warning(f"[WebBrowse] 获取视频信息失败: {e}")
            return None
        if not info:
            return None

        cid = self._first_cid(info)
        title = str(info.get("title") or item.get("title") or "").strip()
        desc = str(info.get("desc") or "").strip()
        duration = int(info.get("duration") or item.get("duration") or 0)
        owner_name = str((info.get("owner") or {}).get("name")
                         or (item.get("owner") or {}).get("name") or "").strip()

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
