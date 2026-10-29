# -*- coding: utf-8 -*-
# func/pipeline/llm_director.py
# 导演状态桥接：读写「当前对话走向」状态，并在导演进入/退出时通知宿主（主链路）

import os
import json
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class LLMDirectorBridge:
    """导演状态 + 事件桥接（只做状态与事件，不含规划/表演逻辑）。

    - 状态按 scope 分（main / qq），落盘 .temp/latest_director.json；
    - 宿主（主链路）通过 register_host 注入 is_busy / flush_history：
      导演激活期间主链路把用户回合让出去；进入/退出时把主链路内存里的
      短期记忆归档，避免「json 旧 + 内存新」倒序；
    - 导演模块自己订阅进入/退出事件，负责重置失望计数。
    """

    PATH = os.path.join(".temp", "latest_director.json")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.RLock()
        self._cache = {}
        self._is_busy = None
        self._flush_history = None
        self._subs = []

    # ==================== 状态读写 ====================
    def get(self, scope="main"):
        """读取指定场景的导演状态（缺失返回空 dict）"""
        key = str(scope or "main")
        with self._lock:
            if key in self._cache:
                return dict(self._cache[key])
            data = self._read_file()
            state = data.get(key) if isinstance(data.get(key), dict) else {}
            self._cache[key] = state
            return dict(state)

    def is_active(self, scope="main"):
        """指定场景导演是否处于激活状态"""
        return bool(self.get(scope).get("active"))

    def set_state(self, scope, state):
        """写入状态并落盘（进度更新用，不触发进入/退出事件）"""
        key = str(scope or "main")
        if not isinstance(state, dict):
            return
        with self._lock:
            self._cache[key] = dict(state)
            data = self._read_file()
            data[key] = dict(state)
            self._write_file(data)

    def activate(self, scope, state):
        """激活导演：写状态 → 通知宿主归档 → 通知订阅者"""
        self.set_state(scope, state)
        self._flush_host()
        self._notify(str(scope or "main"), entered=True)
        self.log.info(f"[导演] 已激活（scope={scope}）")

    def clear(self, scope="main", reason=""):
        """结束导演：active=False 后通知宿主与订阅者（状态保留备查）"""
        key = str(scope or "main")
        state = self.get(key)
        if not state:
            return
        state["active"] = False
        state["clear_reason"] = str(reason or "")
        self.set_state(key, state)
        self._flush_host()
        self._notify(key, entered=False)
        self.log.info(f"[导演] 已结束（scope={key}，原因={reason or '未注明'}）")

    # ==================== 宿主（主链路）接线 ====================
    def register_host(self, is_busy=None, flush_history=None):
        """注册主链路宿主回调：是否忙 / 归档内存短期记忆"""
        if is_busy is not None:
            self._is_busy = is_busy
        if flush_history is not None:
            self._flush_history = flush_history

    def host_busy(self):
        """主链路是否正在处理消息（队列非空或正在生成）"""
        if self._is_busy is None:
            return False
        try:
            return bool(self._is_busy())
        except Exception:
            self.log.exception("[导演] 宿主忙碌检查失败")
            return True

    def can_take_over(self):
        """导演激活且主链路空闲时才允许接管用户回合"""
        return self.is_active() and not self.host_busy()

    # ==================== 事件订阅 ====================
    def subscribe(self, on_entered=None, on_cleared=None):
        """订阅进入/退出事件（callback(scope)）"""
        if on_entered is None and on_cleared is None:
            return
        self._subs.append({"entered": on_entered, "cleared": on_cleared})

    def _notify(self, scope, entered):
        for sub in list(self._subs):
            cb = sub.get("entered" if entered else "cleared")
            if cb is None:
                continue
            try:
                cb(scope)
            except Exception:
                self.log.exception("[导演] 订阅者回调异常")

    def _flush_host(self):
        """让主链路把内存里的短期记忆归档（对齐 json 顺序）"""
        if self._flush_history is None:
            return
        try:
            self._flush_history()
        except Exception:
            self.log.exception("[导演] 主链路短期记忆归档失败")

    # ==================== 落盘 ====================
    def _read_file(self):
        try:
            if not os.path.exists(self.PATH):
                return {}
            with open(self.PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception("[导演] 读取状态失败")
            return {}

    def _write_file(self, data):
        try:
            os.makedirs(os.path.dirname(self.PATH), exist_ok=True)
            tmp = self.PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.PATH)
        except Exception:
            self.log.exception("[导演] 写入状态失败")
