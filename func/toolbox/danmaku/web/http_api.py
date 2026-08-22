# -*- coding: utf-8 -*-
# func/toolbox/danmaku/web/http_api.py
# B站直播 HTTP API 封装（发弹幕/表情 + 查询房间/在线榜/舰长/粉丝团/观众列表）
# 复用 SESSDATA 登录态 session（aiohttp），所有方法均为 async，由 web_client 在弹幕 loop 中调度。

import time
from typing import Optional, List, Dict

import aiohttp

from func.log.default_log import DefaultLog

# 基础请求头
_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://live.bilibili.com/",
}


class TBDanmakuHttpApi:
    """B站直播 HTTP API 客户端（aiohttp，复用登录态 session）"""

    def __init__(self, session: aiohttp.ClientSession, room_id: str = "", bili_jct: str = ""):
        self.log = DefaultLog().getLogger()
        self.session = session
        self.room_id = str(room_id or "")
        self.bili_jct = bili_jct or ""

    # ==================== 通用请求 ====================
    async def _get_json(self, url: str, params: Optional[dict] = None) -> Optional[dict]:
        try:
            async with self.session.get(url, params=params, headers=_BASE_HEADERS,
                                        timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    self.log.warning(f"[DanmakuHttp] GET {url} status={resp.status}")
                    return None
                data = await resp.json(content_type=None)
                return data
        except Exception:
            self.log.exception(f"[DanmakuHttp] GET 异常: {url}")
            return None

    async def _post_form(self, url: str, data: Optional[dict] = None,
                         headers: Optional[dict] = None) -> Optional[dict]:
        h = dict(_BASE_HEADERS)
        if headers:
            h.update(headers)
        try:
            async with self.session.post(url, data=data, headers=h,
                                         timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    self.log.warning(f"[DanmakuHttp] POST {url} status={resp.status}")
                    return None
                return await resp.json(content_type=None)
        except Exception:
            self.log.exception(f"[DanmakuHttp] POST 异常: {url}")
            return None

    # ==================== 房间信息 ====================
    async def get_room_info(self, room_id: str = "") -> Optional[dict]:
        """获取房间信息（getInfoByRoom）"""
        rid = room_id or self.room_id
        data = await self._get_json(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom",
            params={"room_id": rid},
        )
        return data.get("data") if data and data.get("code") == 0 else None

    # ==================== 在线榜 / 高能榜 ====================
    async def get_online_rank(self, room_id: str = "", ruid: str = "",
                              page_size: int = 50) -> List[dict]:
        """获取在线榜/高能榜（getOnlineGoldRank），需主播 uid（ruid）"""
        rid = room_id or self.room_id
        if not ruid:
            info = await self.get_room_info(rid)
            if info:
                ruid = str((info.get("room_info") or {}).get("uid", ""))
        if not ruid:
            return []
        data = await self._get_json(
            "https://api.live.bilibili.com/xlive/general-interface/v1/rank/getOnlineGoldRank",
            params={"ruid": ruid, "roomId": rid, "page": 1, "pageSize": page_size},
        )
        if not data or data.get("code") != 0:
            return []
        return (data.get("data") or {}).get("online_list") or []

    # ==================== 舰长列表 ====================
    async def get_guard_list(self, room_id: str = "", ruid: str = "",
                             page_size: int = 29) -> List[dict]:
        """获取大航海（舰长）列表，权限受限时返回空"""
        rid = room_id or self.room_id
        if not ruid:
            info = await self.get_room_info(rid)
            if info:
                ruid = str((info.get("room_info") or {}).get("uid", ""))
        if not ruid:
            return []
        data = await self._get_json(
            "https://api.live.bilibili.com/xlive/app-room/v2/guardTab/topList",
            params={"roomid": rid, "ruid": ruid, "page": 1, "page_size": page_size},
        )
        if not data or data.get("code") != 0:
            return []
        return (data.get("data") or {}).get("list") or []

    # ==================== 粉丝团列表 ====================
    async def get_fans_medal_list(self, room_id: str = "", page_size: int = 29) -> List[dict]:
        """获取粉丝团列表，权限受限时返回空"""
        rid = room_id or self.room_id
        data = await self._get_json(
            "https://api.live.bilibili.com/xlive/app-room/v2/medalTab/topList",
            params={"roomid": rid, "page": 1, "page_size": page_size},
        )
        if not data or data.get("code") != 0:
            return []
        return (data.get("data") or {}).get("list") or []

    # ==================== 观众列表 ====================
    async def get_audience_list(self, room_id: str = "", page_size: int = 29) -> List[dict]:
        """获取观众列表，权限受限时返回空"""
        rid = room_id or self.room_id
        data = await self._get_json(
            "https://api.live.bilibili.com/xlive/app-room/v2/audienceTab/topList",
            params={"roomid": rid, "page": 1, "page_size": page_size},
        )
        if not data or data.get("code") != 0:
            return []
        return (data.get("data") or {}).get("list") or []

    # ==================== 发弹幕 ====================
    async def send_danmaku(self, text: str, room_id: str = "") -> bool:
        """主动发送文本弹幕（需 bili_jct）"""
        text = (text or "").strip()
        if not text:
            return False
        if not self.bili_jct:
            self.log.warning("[DanmakuHttp] 未配置 bili_jct，无法发弹幕")
            return False
        rid = room_id or self.room_id
        data = {
            "bubble": 0,
            "msg": text,
            "color": 16777215,
            "mode": 1,
            "fontsize": 25,
            "rnd": int(time.time()),
            "roomid": rid,
            "csrf": self.bili_jct,
            "csrf_token": self.bili_jct,
        }
        headers = {
            "Referer": f"https://live.bilibili.com/{rid}",
            "Origin": "https://live.bilibili.com",
        }
        resp = await self._post_form("https://api.live.bilibili.com/msg/send", data=data, headers=headers)
        return bool(resp and resp.get("code") == 0)

    # ==================== 表情 ====================
    async def get_emoticons(self, room_id: str = "") -> List[dict]:
        """获取直播间可用表情包列表"""
        rid = room_id or self.room_id
        data = await self._get_json(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/getEmoticons",
            params={"platform": "pc", "room_id": rid},
        )
        if not data or data.get("code") != 0:
            return []
        emojis = []
        for group in (data.get("data") or {}).get("data") or []:
            for emoji in group.get("emoticons") or []:
                emojis.append(emoji)
        return emojis

    async def send_emoticon(self, emoticon: dict, room_id: str = "") -> bool:
        """发送表情（emoticon 为 get_emoticons 返回的单个表情 dict）"""
        if not emoticon:
            return False
        if not self.bili_jct:
            self.log.warning("[DanmakuHttp] 未配置 bili_jct，无法发表情")
            return False
        rid = room_id or self.room_id
        # 优先使用 emoticon_unique / emoticon_id，其次用表情文本
        emoticon_id = emoticon.get("emoticon_id") or emoticon.get("id") or ""
        emoticon_unique = emoticon.get("emoticon_unique") or emoticon.get("unique") or ""
        data = {
            "bubble": 0,
            "msg": emoticon.get("descr") or emoticon.get("text") or "",
            "color": 16777215,
            "mode": 1,
            "fontsize": 25,
            "rnd": int(time.time()),
            "roomid": rid,
            "csrf": self.bili_jct,
            "csrf_token": self.bili_jct,
        }
        if emoticon_id:
            data["emoticon_id"] = str(emoticon_id)
        if emoticon_unique:
            data["emoticon_unique"] = str(emoticon_unique)
        headers = {
            "Referer": f"https://live.bilibili.com/{rid}",
            "Origin": "https://live.bilibili.com",
        }
        resp = await self._post_form("https://api.live.bilibili.com/msg/send", data=data, headers=headers)
        return bool(resp and resp.get("code") == 0)
