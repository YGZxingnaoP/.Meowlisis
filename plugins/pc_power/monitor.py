# -*- coding: utf-8 -*-
"""睡前监听计时器：到点体检 → 需要确认就等 → 否则结束服务并关机。"""

import threading
import time

from .state import CONFIRM, LISTENING


def _num(cfg, key, default):
    try:
        return float((cfg or {}).get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _bool(cfg, key, default=False):
    value = (cfg or {}).get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class SleepMonitor:
    """1 秒一跳的监听者；只负责状态机与到点动作，不直接操作插件上下文。"""

    def __init__(self, store, cfg, log, say_need=None, transfer_check=None,
                 power_exec=None, on_idle=None):
        self.store = store
        self.cfg = dict(cfg or {})
        self.log = log
        self._say_need = say_need
        self._check = transfer_check
        self._power = power_exec
        self._on_idle = on_idle
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._executing = False

    # ==================== 生命周期 ====================
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="pc_power_monitor")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                self.log.exception("[pc_power] 监听心跳异常")
            self._stop.wait(1.0)

    # ==================== 心跳 ====================
    def tick(self, now=None):
        state = self.store.read()
        phase = state.get("phase")
        if phase not in (LISTENING, CONFIRM):
            return
        deadline = float(state.get("deadline") or 0)
        if not deadline:
            return
        now = float(now if now is not None else time.time())
        if now < deadline:
            return
        if phase == LISTENING:
            self._fire(state, now)
        else:
            self._confirm_timeout(now)

    def _fire(self, state, now=None):
        now = float(now if now is not None else time.time())
        current = self.store.read()
        if current.get("phase") != LISTENING:
            return
        if float(current.get("deadline") or 0) > now:
            return
        transfers = []
        if _bool(self.cfg, "check_transfer", True) and self._check:
            keywords = self.cfg.get("transfer_keywords") or ()
            mbps = _num(self.cfg, "net_busy_mbps", 0)
            try:
                transfers = self._check(keywords, mbps) or []
            except Exception:
                self.log.exception("[pc_power] 下载/上传体检失败，按无占用处理")
                transfers = []
        if transfers:
            window = _num(self.cfg, "confirm_window_sec", 120)
            self.store.to_confirm("transfer", transfers, window, now=now)
            self.log.info("[pc_power] 有下载/上传在跑：%s", transfers)
            self._need(self._ask_need(transfers))
            return
        self.execute("timeout")

    def _confirm_timeout(self, now=None):
        self.log.info("[pc_power] 等不到明确确认，取消关机")
        self.store.cancel("confirm_timeout", now=now)
        self._finish_idle("confirm_timeout")
        self._need("等不到主人的确认，这次已经取消关机；用你自己的口气告诉他先不关了。")

    # ==================== 执行 ====================
    def execute(self, reason="confirmed"):
        """真正执行：结束服务 → 关机（dry-run 下只记录）"""
        with self._lock:
            if self._executing:
                return False
            self._executing = True
        try:
            state = self.store.read()
            if state.get("phase") not in (LISTENING, CONFIRM):
                return False
            self.store.mark_off(reason)
            self._finish_idle(reason)
            if not self._power:
                self.log.warning("[pc_power] 没有关机执行器")
                self.store.cancel("no_power_exec")
                return False
            ok, message = self._power()
            if not ok:
                self.log.warning("[pc_power] 关机未执行：%s", message)
                reason = "dry_run" if str(message) == "dry-run" else \
                    "power_failed:%s" % str(message)[:80]
                self.store.cancel(reason)
                return False
            self.log.info("[pc_power] 关机已排队：%s", message)
            return True
        finally:
            with self._lock:
                self._executing = False

    def _finish_idle(self, reason):
        if self._on_idle:
            try:
                self._on_idle(reason)
            except Exception:
                self.log.exception("[pc_power] on_idle 回调异常")

    # ==================== 口播意图 ====================
    def _need(self, need):
        """把「要说什么事」交给角色本人组织语言（不写死台词）"""
        need = str(need or "").strip()
        if not need or not self._say_need:
            return
        try:
            self._say_need(need)
        except Exception:
            self.log.exception("[pc_power] 组织口播失败")

    def _ask_need(self, transfers):
        hint = str(self.cfg.get("transfer_ask_hint") or
                   "告诉主人还有东西在下载/上传（{names}），问他要不要现在关掉电脑。")
        names = "、".join(str(x.get("name") or "") for x in transfers[:3]) or "有任务"
        return hint.replace("{names}", names).replace("{count}", str(len(transfers)))
