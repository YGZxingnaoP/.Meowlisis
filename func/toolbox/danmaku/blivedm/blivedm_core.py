# B站弹幕
from threading import Thread
import datetime
from func.log.default_log import DefaultLog
from func.pipeline.danmuku_llm import DanmukuLLMBridge
from func.tools.singleton_mode import singleton
from func.config.app_config import AppConfig
from func.llm.state import LLmState
from func.toolbox.danmaku.config import DanmakuConfig

from func.tts.tts_core import TTsCore
import func.toolbox.danmaku.blivedm as blivedm
import func.toolbox.danmaku.blivedm.models.open_live as open_models
import func.toolbox.danmaku.blivedm.models.web as web_models

import http.cookies
import asyncio, aiohttp
from typing import *
from cachetools import cached, TTLCache

@singleton
class BlivedmCore:
    # 设置控制台日志
    log = DefaultLog().getLogger()

    session: Optional[aiohttp.ClientSession] = None

    commonData = AppConfig() #公共数据
    biliDanmakuData = DanmakuConfig()  #b站弹幕数据
    llmData = LLmState()  # llm数据
    ttsCore = TTsCore()  # 语音核心

    danmuku_llm = DanmukuLLMBridge()  # 弹幕→LLM 桥接

    # blivedm弹幕监听
    async def blivedm_start(self):
        await self.run_single_client()

    # SessData会话监听
    async def blivedm_start2(self):
        global session
        self.init_session()
        try:
            await self.run_single_client2()
        finally:
            await session.close()

    def init_session(self):
        cookies = http.cookies.SimpleCookie()
        cookies["SESSDATA"] = self.biliDanmakuData.SESSDATA
        cookies["SESSDATA"]["domain"] = "bilibili.com"

        global session
        session = aiohttp.ClientSession()
        session.cookie_jar.update_cookies(cookies)

    # sessData方式监听
    async def run_single_client2(self):
        """
        演示监听一个直播间
        """
        global session

        client = blivedm.BLiveClient(self.biliDanmakuData.room_id, session=session)
        handler = self.MyHandler2(self)
        client.set_handler(handler)

        client.start()
        try:
            await client.join()
        finally:
            await client.stop_and_close()

    # 开放平台方式监听
    async def run_single_client(self):
        """
        演示监听一个直播间
        """
        client = blivedm.OpenLiveClient(
            access_key_id=self.biliDanmakuData.ACCESS_KEY_ID,
            access_key_secret=self.biliDanmakuData.ACCESS_KEY_SECRET,
            app_id=self.biliDanmakuData.APP_ID,
            room_owner_auth_code=self.biliDanmakuData.ROOM_OWNER_AUTH_CODE,
        )
        handler = self.MyHandler(self)
        client.set_handler(handler)

        client.start()
        try:
            await client.join()
        finally:
            await client.stop_and_close()

    # 监听B站直播间两个监听组合【开放平台+SessData会话】
    async def listen_blivedm_task(self):
        task1 = asyncio.create_task(self.blivedm_start())
        task2 = asyncio.create_task(self.blivedm_start2())
        results = await asyncio.gather(task1, task2)

    class MyHandler2(blivedm.BaseHandler):
        # 演示如何添加自定义回调
        _CMD_CALLBACK_DICT = blivedm.BaseHandler._CMD_CALLBACK_DICT.copy()

        def __init__(self,BlivedmCore):
            self.BlivedmCore = BlivedmCore

        def _on_heartbeat(self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage):
            self.BlivedmCore.log.debug(f'[{client.room_id}] 心跳2')

    class MyHandler(blivedm.BaseHandler):

        def __init__(self,BlivedmCore):
            self.BlivedmCore = BlivedmCore

        # 心跳
        def _on_heartbeat(self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage):
            self.BlivedmCore.log.debug(f'[{client.room_id}] 心跳1')

        # 弹幕获取
        def _on_open_live_danmaku(self, client: blivedm.OpenLiveClient, message: open_models.DanmakuMessage):
            self.BlivedmCore.log.info(f'{message.uname}：{message.msg}')
            self.BlivedmCore.danmuku_llm.send_to_llm(message.msg, message.uname)

        # 赠送礼物
        def _on_open_live_gift(self, client: blivedm.OpenLiveClient, message: open_models.GiftMessage):
            coin_type = '金瓜子' if message.paid else '银瓜子'
            total_coin = message.price * message.gift_num
            self.BlivedmCore.log.info(f'[{message.room_id}] {message.uname} 赠送{message.gift_name}x{message.gift_num}'
                     f' （{coin_type}x{total_coin}）')
            username = message.uname
            giftname = message.gift_name
            num = message.gift_num
            text = f"谢谢‘{username}’赠送的{num}个{giftname}"
            self.BlivedmCore.log.info(text)
            tts_say_thread = Thread(target=self.BlivedmCore.ttsCore.tts_say, args=(text,))
            tts_say_thread.start()

        def _on_open_live_super_chat(
                self, client: blivedm.OpenLiveClient, message: open_models.SuperChatMessage
        ):
            self.BlivedmCore.log.info(f'[{message.room_id}] 醒目留言 ¥{message.rmb} {message.uname}：{message.message}')
            username = message.uname
            rmb = message.rmb
            text = f"谢谢‘{username}’赠送的¥{rmb}元,她留言说\"{message.message}\""
            self.BlivedmCore.log.info(text)
            tts_say_thread = Thread(target=self.BlivedmCore.ttsCore.tts_say, args=(text,))
            tts_say_thread.start()

        def _on_open_live_super_chat_delete(
                self, client: blivedm.OpenLiveClient, message: open_models.SuperChatDeleteMessage
        ):
            self.BlivedmCore.log.info(f'[{message.room_id}] 删除醒目留言 message_ids={message.message_ids}')

        def _on_open_live_like(self, client: blivedm.OpenLiveClient, message: open_models.LikeMessage):
            self.BlivedmCore.log.info(f'{message.uname} 点赞')
            username = message.uname
            text = f"谢谢‘{username}’点赞,小{self.BlivedmCore.commonData.ai_name}最爱你了"
            self.BlivedmCore.log.info(text)
            # 发起语音【10秒说一次】
            self.say(text)

        @cached(TTLCache(maxsize=100, ttl=10))  # 例如30秒的失效时间
        def say(self,text):
            # 假设这是一个计算密集的函数
            tts_say_thread = Thread(target=self.BlivedmCore.ttsCore.tts_say, args=(text,))
            tts_say_thread.start()
            return text