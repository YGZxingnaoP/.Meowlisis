# -*- coding: utf-8 -*-
# func/toolbox/napcat/director/store.py
# QQ 导演状态：按 session 分文件，落 .temp/director_topic/qq/
# 用完（clear）后移到 character/director_topic/qq/{session}/ 归档（移动备份）。

import os
import re
import copy
import json
import threading
import datetime

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class QQDirectorStore:
    """QQ 导演状态（本模块自包含，不经过主链路桥接）

    - 缓存：.temp/director_topic/qq/{safe_session}.json（一个 session 一个文件）
    - 归档：character/director_topic/qq/{safe_session}/{时间}_{原因}.json
    - 旧版 .temp/latest_director_qq.json 在首次使用时自动迁移（仅当 DIR 仍是默认值）
    """

    DEFAULT_DIR = os.path.join(".temp", "director_topic", "qq")
    DIR = DEFAULT_DIR
    LEGACY_PATH = os.path.join(".temp", "latest_director_qq.json")
    ARCHIVE_ROOT = os.path.join("character", "director_topic", "qq")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.RLock()
        self._migrate()

    # ==================== 对外 ====================
    def get(self, session: str) -> dict:
        """读取某个 session 的计划（没有返回空 dict）"""
        with self._lock:
            plan = self._read(session)
            return copy.deepcopy(plan) if isinstance(plan, dict) else {}

    def set(self, session: str, plan: dict) -> bool:
        """写入某个 session 的计划并落盘"""
        if not str(session or "") or not isinstance(plan, dict):
            return False
        with self._lock:
            return self._write(session, copy.deepcopy(plan))

    def clear(self, session: str, reason: str = "") -> dict:
        """结束某个 session：写 inactive → 归档 → 删除缓存文件；归档失败则保留 inactive"""
        key = str(session or "")
        if not key:
            return {}
        with self._lock:
            plan = self._read(key)
            if not isinstance(plan, dict) or not plan:
                return {}
            plan = copy.deepcopy(plan)
            plan["active"] = False
            plan["clear_reason"] = str(reason or "")
            plan["updated_at"] = self._now()
            archived = self._archive(plan, reason, key)
            if archived:
                self._remove(key)
            else:
                self._write(key, plan)
            return plan

    # ==================== 路径/读写 ====================
    def _path(self, session: str) -> str:
        return os.path.join(self.DIR, self._safe(session) + ".json")

    def _read(self, session: str) -> dict:
        path = self._path(session)
        try:
            if not os.path.exists(path):
                return {}
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception(f"[QQ导演] 读取状态失败: {path}")
            return {}

    def _write(self, session: str, plan: dict) -> bool:
        path = self._path(session)
        try:
            os.makedirs(self.DIR, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except Exception:
            self.log.exception(f"[QQ导演] 写入状态失败: {path}")
            return False

    def _remove(self, session: str):
        try:
            os.remove(self._path(session))
        except FileNotFoundError:
            pass
        except Exception:
            self.log.exception("[QQ导演] 删除缓存状态失败")

    # ==================== 归档 ====================
    def _archive(self, plan: dict, reason: str, session: str):
        """把一份计划写到 character/director_topic/qq/{session}/；失败返回 None"""
        key = str(session or plan.get("session") or "unknown")
        try:
            directory = os.path.join(self.ARCHIVE_ROOT, self._safe(key))
            os.makedirs(directory, exist_ok=True)
            ts = self._now("%Y%m%d-%H%M%S")
            path = self._unique_path(directory, f"{ts}_{self._safe(reason, 40)}")
            payload = {
                "archived_at": self._now(),
                "session": key,
                "channel": str(plan.get("channel") or ""),
                "reason": str(reason or ""),
                "plan": plan,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.log.info(f"[QQ导演] 已归档：{path}")
            return path
        except Exception:
            self.log.exception("[QQ导演] 归档失败，保留缓存状态")
            return None

    # ==================== 迁移 ====================
    def _migrate(self):
        """旧版 .temp/latest_director_qq.json → 按 session 分文件（仅当 DIR 仍是默认值）"""
        if self.DIR != self.DEFAULT_DIR:
            return
        if not os.path.exists(self.LEGACY_PATH):
            return
        try:
            with open(self.LEGACY_PATH, "r", encoding="utf-8") as f:
                old = json.load(f)
            if not isinstance(old, dict):
                self.log.warning("[QQ导演] 旧状态格式不对，跳过迁移")
                return
            ok = True
            for session, plan in old.items():
                if not isinstance(plan, dict):
                    continue
                if plan.get("active"):
                    if not self._write(session, plan):
                        ok = False
                else:
                    if not self._archive(plan, plan.get("clear_reason") or "legacy", session):
                        ok = False
            if ok:
                os.remove(self.LEGACY_PATH)
                self.log.info("[QQ导演] 已迁移旧状态到 .temp/director_topic/qq/")
        except Exception:
            self.log.exception("[QQ导演] 迁移旧状态失败")

    # ==================== 杂项 ====================
    @staticmethod
    def _now(fmt="%Y-%m-%d %H:%M:%S"):
        return datetime.datetime.now().strftime(fmt)

    @staticmethod
    def _safe(text, limit=60):
        s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(text or "")).strip("_")
        return (s or "unknown")[:limit]

    @staticmethod
    def _unique_path(directory, base):
        path = os.path.join(directory, base + ".json")
        i = 2
        while os.path.exists(path):
            path = os.path.join(directory, f"{base}_{i}.json")
            i += 1
        return path
