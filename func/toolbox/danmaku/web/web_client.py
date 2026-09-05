# -*- coding: utf-8 -*-
# func/toolbox/danmaku/web/web_client.py
# B站直播连接工具（TB 前缀封装）：复用 blivedm 双通道，回调分发 + HTTP API 同步封装

import http.cookies
import asyncio
import aiohttp
from typing import Optional, Callable

from cachetools import TTLCache

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.danmaku.config import TBDanmakuConfig
from func.toolbox.danmaku.get_danmaku.get_danmaku import TBDanmakuReceiver
from func.toolbox.danmaku.web.http_api import TBDanmakuHttpApi

import func.toolbox.danmaku.blivedm as blivedm
import func.toolbox.danmaku.blivedm.models.open_live as open_models
import func.toolbox.danmaku.blivedm.models.web as web_models


@singleton
class TBDanmakuWeb:
    """B站直播连接工具：负责双通道连接、消息回调分发与 HTTP 操作同步封装。

    - 开放平台通道（OpenLiveClient）：弹幕/礼物/舰长/SC；
    - web 通道（BLiveClient，SESSDATA）：弹幕/礼物/舰长/SC（兜底）；
    - 双通道弹幕/SC 用 TTLCache 去重（5 秒内同人同内容视为重复）；
    - 点赞感谢已移除，不处理。
    """

    # 双通道去重窗口（秒）
    DEDUP_TTL = 5

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBDanmakuConfig()
        self.receiver = TBDanmakuReceiver()
        self.session: Optional[aiohttp.ClientSession] = None
        self.http_api: Optional[TBDanmakuHttpApi] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        # 弹幕/SC 去重缓存：fingerprint -> True
        self._danmaku_dedup = TTLCache(maxsize=5000, ttl=self.DEDUP_TTL)
        self._sc_dedup = TTLCache(maxsize=1000, ttl=self.DEDUP_TTL)
        # 礼物/舰长回调（由 danmaku_core 注入，避免循环 import）
        self.on_gift: Optional[Callable[[str, str, int, int, str, Optional[bool]], None]] = None
        self.on_guard: Optional[Callable[[str, int], None]] = None

    # ==================== 回调注入 ====================
    def set_callbacks(self, on_gift=None, on_guard=None):
        """注入礼物/舰长回调（由 danmaku_core 提供，触发 AI 拟感谢词）"""
        self.on_gift = on_gift
        self.on_guard = on_guard

    # ==================== 连接生命周期 ====================
    def init_session(self):
        """初始化带登录态的 aiohttp session（SESSDATA + bili_jct）"""
        cookies = http.cookies.SimpleCookie()
        if self.config.SESSDATA:
            cookies["SESSDATA"] = self.config.SESSDATA
            cookies["SESSDATA"]["domain"] = "bilibili.com"
        if self.config.bili_jct:
            cookies["bili_jct"] = self.config.bili_jct
            cookies["bili_jct"]["domain"] = "bilibili.com"
        self.session = aiohttp.ClientSession()
        self.session.cookie_jar.update_cookies(cookies)
        self.http_api = TBDanmakuHttpApi(self.session, self.config.room_id, self.config.bili_jct)

    async def close(self):
        """释放 session 资源"""
        if self.session is not None:
            await self.session.close()
            self.session = None
            self.http_api = None

    async def run(self):
        """启动弹幕连接：默认只走开放平台，web(SESSDATA) 作为兜底。

        - 开放平台配置完整 → 只跑开放平台；
        - 开放平台未配置但有 SESSDATA → 回退跑 web 通道；
        - 均未配置 → 报错并结束。
        """
        self.init_session()
        try:
            if self._has_open_live_credentials():
                self.log.info("[DanmakuWeb] 使用开放平台通道监听")
                await self._run_open_live()
            elif self.config.SESSDATA:
                self.log.info("[DanmakuWeb] 开放平台未配置，回退使用 web(SESSDATA) 通道监听")
                await self._run_web()
            else:
                self.log.error("[DanmakuWeb] 开放平台与 SESSDATA 均未配置，无法连接直播间")
        finally:
            await self.close()

    def _has_open_live_credentials(self) -> bool:
        """判断开放平台四项配置是否齐全"""
        return all([
            str(self.config.ACCESS_KEY_ID or '').strip(),
            str(self.config.ACCESS_KEY_SECRET or '').strip(),
            str(self.config.APP_ID or '').strip(),
            str(self.config.ROOM_OWNER_AUTH_CODE or '').strip(),
        ])

    async def _run_open_live(self):
        """开放平台通道"""
        client = blivedm.OpenLiveClient(
            access_key_id=self.config.ACCESS_KEY_ID,
            access_key_secret=self.config.ACCESS_KEY_SECRET,
            app_id=self.config.APP_ID,
            room_owner_auth_code=self.config.ROOM_OWNER_AUTH_CODE,
            session=self.session,
        )
        client.set_handler(self._OpenHandler(self))
        client.start()
        try:
            await client.join()
        finally:
            await client.stop_and_close()

    async def _run_web(self):
        """web（SESSDATA）通道"""
        client = blivedm.BLiveClient(self.config.room_id, session=self.session)
        client.set_handler(self._WebHandler(self))
        client.start()
        try:
            await client.join()
        finally:
            await client.stop_and_close()

    # ==================== 同步封装（供外部线程调用） ====================
    def submit(self, coro, timeout: float = 10.0):
        """把协程提交到弹幕 loop 并同步等待结果"""
        if self.loop is None or not self.loop.is_running():
            self.log.warning("[DanmakuWeb] 弹幕 loop 未运行，无法执行 HTTP 操作")
            return None
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
            return fut.result(timeout=timeout)
        except Exception:
            self.log.exception("[DanmakuWeb] HTTP 操作异常")
            return None

    def send_danmaku_sync(self, text: str) -> bool:
        if self.http_api is None:
            return False
        return bool(self.submit(self.http_api.send_danmaku(text)) or False)

    def get_room_info_sync(self) -> Optional[dict]:
        if self.http_api is None:
            return None
        return self.submit(self.http_api.get_room_info())

    def get_online_rank_sync(self) -> list:
        if self.http_api is None:
            return []
        return self.submit(self.http_api.get_online_rank()) or []

    def get_guard_list_sync(self) -> list:
        if self.http_api is None:
            return []
        return self.submit(self.http_api.get_guard_list()) or []

    def get_fans_medal_list_sync(self) -> list:
        if self.http_api is None:
            return []
        return self.submit(self.http_api.get_fans_medal_list()) or []

    def get_audience_list_sync(self) -> list:
        if self.http_api is None:
            return []
        return self.submit(self.http_api.get_audience_list()) or []

    # ==================== 去重 ====================
    def _is_dup_danmaku(self, uname: str, msg: str) -> bool:
        fp = f"{uname}|{msg}"
        if fp in self._danmaku_dedup:
            return True
        self._danmaku_dedup[fp] = True
        return False

    def _is_dup_sc(self, msg_id: str, uname: str, message: str) -> bool:
        fp = str(msg_id or "") or f"{uname}|{message}"
        if fp in self._sc_dedup:
            return True
        self._sc_dedup[fp] = True
        return False

    # ==================== 消息回调 ====================
    def _handle_danmaku(self, uname: str, msg: str):
        if self._is_dup_danmaku(uname, msg):
            return
        self.receiver.add_danmaku(uname, msg)
        self.log.info(f"[弹幕] {uname}: {msg}")

    def _handle_sc(self, uname: str, message: str, msg_id: str = ""):
        if self._is_dup_sc(msg_id, uname, message):
            return
        self.receiver.add_sc(uname, message, msg_id)
        self.log.info(f"[SC] {uname}: {message}")

    def _handle_gift(self, uname: str, gift_name: str, gift_num: int, price: int,
                     coin_type: str = 'gold', paid: Optional[bool] = None):
        if self.on_gift:
            try:
                self.on_gift(uname, gift_name, gift_num, price, coin_type, paid)
            except Exception:
                self.log.exception("[DanmakuWeb] 礼物感谢回调异常")

    def _handle_guard(self, uname: str, guard_level: int):
        if self.on_guard:
            try:
                self.on_guard(uname, guard_level)
            except Exception:
                self.log.exception("[DanmakuWeb] 舰长感谢回调异常")

    # ==================== 开放平台 handler ====================
    class _OpenHandler(blivedm.BaseHandler):
        def __init__(self, web: "TBDanmakuWeb"):
            self.web = web

        def _on_open_live_danmaku(self, client, message: open_models.DanmakuMessage):
            self.web._handle_danmaku(message.uname, message.msg)

        def _on_open_live_gift(self, client, message: open_models.GiftMessage):
            self.web._handle_gift(message.uname, message.gift_name, message.gift_num,
                                  message.price, coin_type=None, paid=message.paid)

        def _on_open_live_buy_guard(self, client, message: open_models.GuardBuyMessage):
            self.web._handle_guard(message.user_info.uname, message.guard_level)

        def _on_open_live_super_chat(self, client, message: open_models.SuperChatMessage):
            self.web._handle_sc(message.uname, message.message, message.msg_id)

        def _on_open_live_super_chat_delete(self, client, message: open_models.SuperChatDeleteMessage):
            self.web.log.info(f"[SC删除] message_ids={message.message_ids}")

    # ==================== web handler ====================
    class _WebHandler(blivedm.BaseHandler):
        def __init__(self, web: "TBDanmakuWeb"):
            self.web = web

        def _on_danmaku(self, client, message: web_models.DanmakuMessage):
            self.web._handle_danmaku(message.uname, message.msg)

        def _on_gift(self, client, message: web_models.GiftMessage):
            self.web._handle_gift(message.uname, message.gift_name, message.num,
                                  message.price, coin_type=message.coin_type, paid=None)

        def _on_buy_guard(self, client, message: web_models.GuardBuyMessage):
            self.web._handle_guard(message.username, message.guard_level)

        def _on_super_chat(self, client, message: web_models.SuperChatMessage):
            self.web._handle_sc(message.uname, message.message, str(message.id))

        def _on_super_chat_delete(self, client, message: web_models.SuperChatDeleteMessage):
            self.web.log.info(f"[SC删除] ids={message.ids}")
