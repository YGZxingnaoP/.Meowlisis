# -*- coding: utf-8 -*-
# func/pipeline/llm_director.py
# 导演状态桥接：读写「当前对话走向」状态，并在导演进入/退出时通知宿主（主链路）
# 落盘：.temp/director_topic/main.json（active 中）；clear 后移到 character/director_topic/main/ 归档。

import os
import re
import json
import threading
import datetime

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class LLMDirectorBridge:
    """导演状态 + 事件桥接（只做状态与事件，不含规划/表演逻辑）。

    - 状态按 scope 分（main / qq），主链路用 main；
    - 缓存文件 .temp/director_topic/main.json；clear 时把最终状态归档到
      character/director_topic/main/{时间}_{原因}.json，并删除缓存文件（移动备份）；
    - 旧版 .temp/latest_director.json 在首次启动时自动迁移（只在 PATH 未被改写时）；
    - 宿主（主链路）通过 register_host 注入 is_busy / flush_history。
    """

    DEFAULT_PATH = os.path.join(".temp", "director_topic", "main.json")
    PATH = DEFAULT_PATH
    LEGACY_PATH = os.path.join(".temp", "latest_director.json")
    ARCHIVE_DIR = os.path.join("character", "director_topic", "main")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.RLock()
        self._cache = {}
        self._is_busy = None
        self._flush_history = None
        self._subs = []
        self._migrate()

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
        """激活导演：先归档旧计划（重写覆盖）→ 写状态 → 通知宿主归档 → 通知订阅者"""
        key = str(scope or "main")
        with self._lock:
            try:
                self._archive_current(key, "新计划覆盖")
            except Exception:
                self.log.exception("[导演] 归档旧计划失败")
            self.set_state(key, state)
        self._flush_host()
        self._notify(key, entered=True)
        self.log.info(f"[导演] 已激活（scope={scope}）")

    def clear(self, scope="main", reason=""):
        """结束导演：写 inactive → 归档 → 删除缓存文件 → 通知宿主与订阅者"""
        key = str(scope or "main")
        with self._lock:
            state = self.get(key)
            if not state:
                return
            state["active"] = False
            state["clear_reason"] = str(reason or "")
            state["updated_at"] = self._now()
            archived = self._archive_state(state, reason, key)
            self.set_state(key, state)
            if archived:
                try:
                    os.remove(self.PATH)
                except FileNotFoundError:
                    pass
                except Exception:
                    self.log.exception("[导演] 删除缓存状态失败")
            self._cache.pop(key, None)
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

    # ==================== 归档 ====================
    def _archive_current(self, scope, reason):
        """归档当前状态（不删文件，用于重写覆盖前备份）"""
        state = self.get(scope)
        if not state:
            return None
        return self._archive_state(state, reason, scope)

    def _archive_state(self, state, reason, channel):
        """把一份计划写到 character/director_topic/main/；失败返回 None"""
        if not isinstance(state, dict) or not state:
            return None
        try:
            os.makedirs(self.ARCHIVE_DIR, exist_ok=True)
            ts = self._now("%Y%m%d-%H%M%S")
            path = self._unique_path(self.ARCHIVE_DIR, f"{ts}_{self._safe(reason)}")
            payload = {
                "archived_at": self._now(),
                "channel": str(channel or "main"),
                "session": str(channel or "main"),
                "reason": str(reason or ""),
                "plan": state,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.log.info(f"[导演] 已归档：{path}")
            return path
        except Exception:
            self.log.exception("[导演] 归档失败，保留缓存状态")
            return None

    # ==================== 迁移 ====================
    def _migrate(self):
        """旧版 .temp/latest_director.json → 新布局（仅当 PATH 仍是默认值）"""
        if self.PATH != self.DEFAULT_PATH:
            return
        if not os.path.exists(self.LEGACY_PATH):
            return
        try:
            old = self._read_json(self.LEGACY_PATH)
            if not isinstance(old, dict):
                self.log.warning("[导演] 旧状态格式不对，跳过迁移")
                return
            state = old.get("main")
            if isinstance(state, dict) and state:
                if state.get("active") and not os.path.exists(self.PATH):
                    # 旧计划还在演：写进新缓存，交给 DirectorCore 决定 resume/重启收尾
                    self._write_json(self.PATH, {"main": state})
                else:
                    # 已结束，或新缓存已存在：旧计划直接归档
                    self._archive_state(state, "legacy", "main")
            self._cache.pop("main", None)
            os.remove(self.LEGACY_PATH)
            self.log.info("[导演] 已迁移旧状态到 .temp/director_topic/main.json")
        except Exception:
            self.log.exception("[导演] 迁移旧状态失败")

    # ==================== 落盘 ====================
    def _read_file(self):
        try:
            if not os.path.exists(self.PATH):
                return {}
            data = self._read_json(self.PATH)
            return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception("[导演] 读取状态失败")
            return {}

    def _write_file(self, data):
        try:
            self._write_json(self.PATH, data)
        except Exception:
            self.log.exception("[导演] 写入状态失败")

    def _read_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    @staticmethod
    def _now(fmt="%Y-%m-%d %H:%M:%S"):
        return datetime.datetime.now().strftime(fmt)

    @staticmethod
    def _safe(text):
        s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(text or "")).strip("_")
        return (s or "未注明")[:40]

    @staticmethod
    def _unique_path(directory, base):
        path = os.path.join(directory, base + ".json")
        i = 2
        while os.path.exists(path):
            path = os.path.join(directory, f"{base}_{i}.json")
            i += 1
        return path
