# -*- coding: utf-8 -*-
# func/toolbox/danmaku/danmaku_core.py
# B站弹幕模块总入口：连接线程 + 消费轮询线程 + 礼物/舰长感谢

import asyncio
import threading
import time
import uuid

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.danmaku.config import TBDanmakuConfig
from func.toolbox.danmaku.web.web_client import TBDanmakuWeb
from func.toolbox.danmaku.get_danmaku.get_danmaku import TBDanmakuReceiver
from func.toolbox.danmaku.reply.reply_engine import TBDanmakuReply


@singleton
class TBDanmakuCore:
    """B站弹幕模块核心：模块启用时启动连接线程与消费轮询线程。

    - 连接线程：跑 blivedm 双通道（开放平台 + web SESSDATA）；
    - 消费轮询线程：每秒检测 TTS 忙状态，空闲则消费弹幕队列；
    - 礼物/舰长感谢：不再硬编码，交给 toolbox LLM 拟词 + TTS（优先级与 weather/news 同级）。
    """

    # 轮询间隔（秒）
    POLL_INTERVAL = 1.0

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBDanmakuConfig()
        self.web = TBDanmakuWeb()
        self.receiver = TBDanmakuReceiver()
        self.reply = TBDanmakuReply()
        self._conn_thread: threading.Thread = None
        self._poll_thread: threading.Thread = None
        self._running = False

    # ==================== 生命周期 ====================
    def start(self):
        """启动弹幕模块后台线程（未启用则直接返回）"""
        if not self.config.enabled:
            self.log.info("B站弹幕模块未启用")
            return
        # 注入礼物/舰长回调
        self.web.set_callbacks(on_gift=self.thank_gift, on_guard=self.thank_guard)

        if self._conn_thread and self._conn_thread.is_alive():
            self.log.warning("B站弹幕连接已在运行")
        else:
            self._running = True
            self._conn_thread = threading.Thread(target=self._run_conn_loop, daemon=True)
            self._conn_thread.start()

        if self._poll_thread and self._poll_thread.is_alive():
            self.log.warning("B站弹幕消费轮询已在运行")
        else:
            self._poll_thread = threading.Thread(target=self._run_poll_loop, daemon=True)
            self._poll_thread.start()

        self.log.info("B站弹幕模块已启动")

    def stop(self):
        """停止后台线程"""
        self._running = False
        if self.web.loop and self.web.loop.is_running():
            self.web.loop.call_soon_threadsafe(self.web.loop.stop)
        if self._conn_thread:
            self._conn_thread.join(timeout=5)
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
        self.log.info("B站弹幕模块已停止")

    # ==================== 连接线程 ====================
    def _run_conn_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.web.loop = loop
        try:
            loop.run_until_complete(self.web.run())
        except Exception:
            self.log.exception("B站弹幕连接主协程异常")
        finally:
            self.web.loop = None
            loop.close()

    # ==================== 消费轮询线程 ====================
    def _run_poll_loop(self):
        from func.pipeline.toolbox_tts import ToolboxTtsBridge
        tts_bridge = ToolboxTtsBridge()
        while self._running:
            try:
                if not tts_bridge.is_busy():
                    self.reply.consume()
            except Exception:
                self.log.exception("弹幕消费轮询异常")
            time.sleep(self.POLL_INTERVAL)

    # ==================== 礼物/舰长感谢 ====================
    def thank_gift(self, username: str, gift_name: str, gift_num: int, price: int):
        """收到礼物：toolbox LLM 拟感谢词 + TTS（50 字以内）"""
        if not self.config.gift_thanks_enabled:
            return
        threading.Thread(target=self._thank_gift_async,
                         args=(username, gift_name, gift_num, price), daemon=True).start()

    def thank_guard(self, username: str, guard_level: int):
        """收到上舰：toolbox LLM 拟感谢词 + TTS（100 字以内）"""
        if not self.config.gift_thanks_enabled:
            return
        threading.Thread(target=self._thank_guard_async,
                         args=(username, guard_level), daemon=True).start()

    def _thank_gift_async(self, username: str, gift_name: str, gift_num: int, price: int):
        try:
            username = username or "观众"
            total_coin = int(price or 0) * int(gift_num or 0)
            user_msg = (
                f"观众 {username} 赠送了 {gift_num} 个 {gift_name}"
                f"（共 {total_coin} 瓜子），请以你的角色身份真诚感谢TA，控制在 50 字以内。"
            )
            reply = self._build_thanks(username, user_msg, 50)
            if reply:
                from func.pipeline.toolbox_tts import ToolboxTtsBridge
                ToolboxTtsBridge().send_stream(reply, source="toolbox_danmaku_gift")
        except Exception:
            self.log.exception("礼物感谢异常")

    def _thank_guard_async(self, username: str, guard_level: int):
        try:
            username = username or "观众"
            guard_name = {1: "总督", 2: "提督", 3: "舰长"}.get(int(guard_level or 0), "舰长")
            user_msg = (
                f"观众 {username} 开通了 {guard_name}，请以你的角色身份真诚感谢TA，控制在 100 字以内。"
            )
            reply = self._build_thanks(username, user_msg, 100)
            if reply:
                from func.pipeline.toolbox_tts import ToolboxTtsBridge
                ToolboxTtsBridge().send_stream(reply, source="toolbox_danmaku_gift")
        except Exception:
            self.log.exception("舰长感谢异常")

    def _build_thanks(self, username: str, user_msg: str, word_limit: int) -> str:
        """用 toolbox LLM 按角色档案拟感谢词"""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            system_prompt = TBoxGetPrompt().get_system_prompt(username, user_msg) or ""
            llm = self._llm()
            if llm is None or not llm.client:
                self.log.error("[Danmaku] 感谢词 LLM 不可用")
                return ""
            resp = llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ])
            if resp and resp.choices:
                return (resp.choices[0].message.content or "").strip()
        except Exception:
            self.log.exception("拟感谢词异常")
        return ""

    def _llm(self):
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
