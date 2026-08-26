# -*- coding: utf-8 -*-
# func/toolbox/danmaku/reply/reply_engine.py
# 弹幕回复引擎：消费缓存队列 → 朗读（可选）+ LLM 回复（一个连续 TTS 任务）

import random
import uuid

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.danmaku.config import TBDanmakuConfig
from func.toolbox.danmaku.get_danmaku.get_danmaku import TBDanmakuReceiver
from func.toolbox.danmaku.reply.read_aloud import TBDanmakuReadAloud
from func.pipeline.toolbox_llm import ToolboxLLMBridge
from func.pipeline.toolbox_tts import ToolboxTtsBridge


@singleton
class TBDanmakuReply:
    """弹幕回复引擎：按 SC 优先、普通弹幕算法选取，回复后清空对应队列。

    - SC：始终优先，每个都读；sc_llm_reply_enabled=True 时额外走 LLM；
    - 普通弹幕：单条直接回复，多条按策略（longest/newest/all/random）；
    - 朗读段 + LLM 回复段共享同一 traceid，由主链路串成一个连续 TTS 任务。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBDanmakuConfig()
        self.receiver = TBDanmakuReceiver()
        self.read_aloud = TBDanmakuReadAloud(self.config.read_aloud_mode)
        self.toolbox_llm = ToolboxLLMBridge()
        self.toolbox_tts = ToolboxTtsBridge()

    # ==================== 消费入口 ====================
    def consume(self):
        """消费一次：SC 优先，否则消费普通弹幕队列"""
        try:
            # 海龟汤游戏激活时：弹幕猜测优先走游戏（live 会话）
            if self._route_turtle_soup():
                return
            # 1. SC 优先
            sc = self.receiver.pop_sc()
            if sc:
                self._reply_sc(sc)
                self.receiver.remove_sc(sc)  # SC 只删除被回复的这条
                return

            # 2. 普通弹幕
            danmaku_list = self.receiver.snapshot_danmaku()
            if not danmaku_list:
                return
            picked = self._pick(danmaku_list)
            if not picked:
                self.receiver.clear_danmaku()
                return
            self._reply_danmaku(picked)
            self.receiver.clear_danmaku()  # 每次回复清空弹幕队列
        except Exception:
            self.log.exception("[DanmakuReply] 消费弹幕异常")

    # ==================== 海龟汤路由 ====================
    def _route_turtle_soup(self) -> bool:
        """游戏激活时逐条路由弹幕（SC 优先，再普通弹幕）：consumed=游戏已处理，pass=走弹幕单条回复主持"""
        try:
            from func.pipeline.turtle_soup_state import TurtleSoupStateBridge
            if not TurtleSoupStateBridge().is_active("live"):
                return False
            from func.toolbox.turtle_soup.turtle_soup_core import TBTurtleSoupCore
            core = TBTurtleSoupCore()

            # SC 优先
            sc = self.receiver.pop_sc()
            if sc:
                self._route_one(core, sc)
                self.receiver.remove_sc(sc)
                return True

            # 普通弹幕
            danmaku_list = self.receiver.snapshot_danmaku()
            if not danmaku_list:
                return False
            for d in danmaku_list:
                self._route_one(core, d)
            self.receiver.clear_danmaku()
            return True
        except Exception:
            self.log.exception("[DanmakuReply] 海龟汤路由异常")
            return False

    def _route_one(self, core, d):
        content = (d.get("content") or "").strip()
        if not content:
            return
        r = core.route_text(content, d.get("username", "用户"), channel="live")
        if r == "pass":
            # 普通猜测：走弹幕单条回复（主 LLM 用 danmaku 提示词，已注入游戏块）
            self._reply_single(d)

    # ==================== 选取算法 ====================
    def _pick(self, danmaku_list: list) -> list:
        """按配置策略从多条弹幕中选取；单条直接返回"""
        if len(danmaku_list) == 1:
            return list(danmaku_list)

        strategy = str(self.config.multi_danmaku_strategy or "random").strip().lower()
        if strategy == "longest":
            return [max(danmaku_list, key=lambda d: len(d.get("content", "")))]
        if strategy == "newest":
            return [danmaku_list[-1]]
        if strategy == "all":
            total = sum(len(d.get("content", "")) for d in danmaku_list)
            if total > int(self.config.multi_danmaku_char_limit or 200):
                # 总字符超阈值，回退最长一条
                return [max(danmaku_list, key=lambda d: len(d.get("content", "")))]
            return list(danmaku_list)
        # random（默认）
        return [random.choice(danmaku_list)]

    # ==================== 普通弹幕回复 ====================
    def _reply_danmaku(self, picked: list):
        if len(picked) == 1:
            self._reply_single(picked[0])
            return

        # 多条（all 策略）：统一回复，不朗读，只记 assistant（不记用户记忆）
        usernames = [d.get("username", "用户") for d in picked]
        multi_user = len(set(usernames)) > 1
        lines = [f"{d.get('username', '用户')}: {d.get('content', '')}" for d in picked]
        wrapped = "【弹幕】" + "；".join(lines)
        traceid = str(uuid.uuid4())
        self.toolbox_llm.send_to_llm(
            wrapped, usernames[0], source="danmaku",
            preamble_text="", traceid=traceid, multi_user=multi_user,
            memory_config=self._memory_config(assistant_only=True),
        )

    def _reply_single(self, d: dict):
        username = d.get("username", "用户")
        content = d.get("content", "")
        wrapped = f"【弹幕】{username}: {content}"
        read_text = ""
        if self.config.read_aloud_enabled:
            read_text = self.read_aloud.render_normal(username, content)
        traceid = str(uuid.uuid4())
        self.toolbox_llm.send_to_llm(
            wrapped, username, source="danmaku",
            preamble_text=read_text, traceid=traceid, multi_user=False,
            memory_config=self._memory_config(assistant_only=False),
        )

    # ==================== SC 回复 ====================
    def _reply_sc(self, sc: dict):
        username = sc.get("username", "用户")
        content = sc.get("content", "")
        read_text = self.read_aloud.render_sc(username, content)

        if self.config.sc_llm_reply_enabled:
            # 朗读 SC + LLM 回复（连续任务）
            wrapped = f"【弹幕】{username}: {content}"
            traceid = str(uuid.uuid4())
            self.toolbox_llm.send_to_llm(
                wrapped, username, source="danmaku",
                preamble_text=read_text, traceid=traceid, multi_user=False,
                memory_config=self._memory_config(assistant_only=False),
            )
        else:
            # 仅朗读 SC（独立完整 TTS 任务）
            self.toolbox_tts.send_stream(read_text, source="toolbox_danmaku")

    # ==================== 弹幕专属记忆配置 ====================
    def _memory_config(self, assistant_only: bool = False) -> dict:
        """构造弹幕专属记忆配置（仅弹幕使用，与其它模块完全隔离）

        - short_type: 弹幕短期记忆独立类型；
        - short_mode: items（按条计数）；
        - short_limit: danmaku.memory_short_limit；
        - record_ltmem: danmaku.ltmem_enabled（是否写长期+摘要）；
        - assistant_only: 多弹幕统一回复时只记 assistant、不记用户记忆。
        """
        return {
            "short_type": "danmaku_response",
            "short_mode": "items",
            "short_limit": int(self.config.memory_short_limit or 40),
            "record_ltmem": bool(self.config.ltmem_enabled),
            "assistant_only": bool(assistant_only),
        }
