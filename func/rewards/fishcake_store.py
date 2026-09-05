# -*- coding: utf-8 -*-
# func/rewards/fishcake_store.py
# 奖励账本：每个奖励一个 json（character/rewards/<名称>.json），原子读写
import json
import os
import random
import tempfile

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

REWARDS_DIR = os.path.join("character", "rewards")
HISTORY_LIMIT = 100
ILLEGAL_CHARS = '\\/:*?"<>|'


class FishCakeStore:
    """奖励账本（每奖励一 json）。含获取总数 total_acquired 与当前持有 balance。"""

    def __init__(self, log=None):
        self.log = log or DefaultLog().getLogger()
        self._dir = REWARDS_DIR
        os.makedirs(self._dir, exist_ok=True)
        self._ensure_default()

    # ==================== 基础 ====================
    @staticmethod
    def _sanitize_name(name):
        name = str(name or "").strip()
        for ch in ILLEGAL_CHARS:
            name = name.replace(ch, "")
        return name.strip() or "小鱼干"

    def _path(self, name):
        return os.path.join(self._dir, f"{self._sanitize_name(name)}.json")

    def _ensure_default(self):
        if not [f for f in os.listdir(self._dir) if f.endswith(".json")]:
            self.save("小鱼干", {
                "name": "小鱼干",
                "unit": "条",
                "battery_per_unit": 10,
                "startup_cost": 1,
                "total_acquired": 0.0,
                "balance": 0.0,
                "history": [],
            })

    def kinds(self):
        return sorted(f[:-5] for f in os.listdir(self._dir) if f.endswith(".json"))

    def load(self, name):
        path = self._path(name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                self.log.exception(f"读取奖励 {name} 失败")
        return {"name": self._sanitize_name(name), "unit": "", "battery_per_unit": 10,
                "startup_cost": 0, "total_acquired": 0.0, "balance": 0.0, "history": []}

    def save(self, name, data):
        path = self._path(name)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            self.log.exception(f"保存奖励 {name} 失败")
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass

    @staticmethod
    def _r1(v):
        try:
            return round(float(v or 0), 1)
        except Exception:
            return 0.0

    def _append_history(self, data, rec):
        data.setdefault("history", [])
        data["history"].append(rec)
        if len(data["history"]) > HISTORY_LIMIT:
            data["history"] = data["history"][-HISTORY_LIMIT:]

    # ==================== 入账 ====================
    def add(self, name, delta, rec_type, note="", **meta):
        """增减某奖励余额。delta>0 同时累计获取总数；delta<0 只减持有（不欠）。"""
        data = self.load(name)
        delta = self._r1(delta)
        balance = self._r1(data.get("balance"))
        if delta >= 0:
            data["total_acquired"] = self._r1(data.get("total_acquired")) + delta
            balance = balance + delta
        else:
            balance = max(balance + delta, 0.0)
        balance = self._r1(balance)
        data["balance"] = balance
        rec = {"ts": int(__import__("time").time()), "type": rec_type, "delta": delta}
        if note:
            rec["note"] = note
        for k, v in meta.items():
            if v is not None:
                rec[k] = v
        self._append_history(data, rec)
        self.save(name, data)
        return balance

    def add_gift(self, battery, user="", gift="", num=0):
        """礼物按电池入账：随机选一个现有奖励项整笔计入。返回入账事件或 None（无候选/过小）。"""
        kinds = self.kinds()
        if not kinds:
            return None
        kind = random.choice(kinds)
        data = self.load(kind)
        unit = data.get("unit") or ""
        qty = self._r1(battery / float(data.get("battery_per_unit") or 10))
        if qty <= 0:
            return None
        self.add(kind, qty, "gift", gift=f"{gift}x{num}" if num else gift, user=user)
        return {"kind": kind, "unit": unit, "qty": qty, "battery": self._r1(battery),
                "user": user, "gift": gift}

    def adjust(self, name, delta, note=""):
        """手动入/出库（GUI）。delta>0 计入获取总数。"""
        if delta >= 0:
            return self.add(name, delta, "manual_add", note=note or "手动入库")
        return self.add(name, delta, "manual_sub", note=note or "手动出库")

    def apply_startup_cost(self):
        """启动扣减：所有 startup_cost>0 的种类各扣（不欠条）。返回扣减记录。"""
        records = []
        for name in self.kinds():
            data = self.load(name)
            cost = float(data.get("startup_cost") or 0)
            balance = self._r1(data.get("balance"))
            if cost <= 0 or balance <= 0:
                continue
            cut = min(cost, balance)
            self.add(name, -cut, "startup", note="启动消耗")
            records.append({"name": name, "cost": self._r1(cut),
                            "before": balance, "after": self._r1(balance - cut)})
        return records

    # ==================== 管理（GUI/API） ====================
    def summary(self, history_limit=10):
        """汇总所有奖励（供 GUI / basket / api 展示）。"""
        kinds = []
        for name in self.kinds():
            data = self.load(name)
            kinds.append({
                "name": name,
                "unit": data.get("unit") or "",
                "battery_per_unit": data.get("battery_per_unit", 10),
                "startup_cost": data.get("startup_cost", 0),
                "total_acquired": data.get("total_acquired", 0.0),
                "balance": data.get("balance", 0.0),
                "history": (data.get("history") or [])[-history_limit:],
            })
        return {"kinds": kinds}

    def set_fields(self, name, **fields):
        data = self.load(name)
        for k in ("unit", "battery_per_unit", "startup_cost"):
            if k in fields:
                if k == "unit":
                    data[k] = str(fields[k] or "").strip()
                else:
                    try:
                        data[k] = float(fields[k])
                    except Exception:
                        pass
        data["name"] = self._sanitize_name(name)
        self.save(name, data)
        return True

    def add_kind(self, name, unit="", battery_per_unit=10, startup_cost=1):
        name = self._sanitize_name(name)
        if not name or name in self.kinds():
            return False
        data = {"name": name, "unit": unit or "", "battery_per_unit": float(battery_per_unit or 1),
                "startup_cost": float(startup_cost or 0), "total_acquired": 0.0,
                "balance": 0.0, "history": []}
        self.save(name, data)
        return True

    def remove_kind(self, name):
        path = self._path(name)
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            self.log.exception(f"删除奖励 {name} 失败")
            return False
        self._ensure_default()
        return True
