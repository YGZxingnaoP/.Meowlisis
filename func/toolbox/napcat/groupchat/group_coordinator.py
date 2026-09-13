# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/group_coordinator.py
# 群聊回复协调器：聚合同群多触发/多用户，窗口内合并为一次回复，避免刷屏。

import random
import threading
import time
from collections import OrderedDict

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.config import TBNapCatConfig


@singleton
class TBGroupReplyCoordinator:
    """群聊回复协调器（per-group 状态机）。

    规则：
    - 单参与者（@ / 关键词）：使用用户续聊窗口（默认 5~15s），窗口内该用户后续消息合并；
    - 出现第二个参与者 / 主动触发：压缩为合并窗口（默认 2s），多人/多触发合并为一次回复；
    - 生成期间新触发进入 queued，本轮结束后最多再聚合 max_extra_rounds 轮；
    - group_merge.enabled=false 时不做跨用户合并（仍保留同用户续聊）。

    本类只负责"聚合 + 定时派发"，真正的回复由 set_flush_handler 注入的回调执行。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self._lock = threading.Lock()
        # group_id -> state
        self._state = {}
        self._flush = None

    # ==================== 对外接口 ====================
    def set_flush_handler(self, fn):
        """注入派发回调：fn(group_id, merged_dict)"""
        self._flush = fn

    def has_user(self, group_id, user_id) -> bool:
        """该用户是否已在当前群的触发窗口内（用于续聊合并判定）"""
        with self._lock:
            st = self._state.get(str(group_id or ""))
            return bool(st and str(user_id or "") in st["participants"])

    def any_pending(self, group_id) -> bool:
        with self._lock:
            return bool(self._state.get(str(group_id or "")))

    def cancel_user(self, group_id, user_id) -> str:
        """取出并移除某用户当前待合并文本（返回合并文本，无则空串）"""
        gid = str(group_id or "")
        uid = str(user_id or "")
        with self._lock:
            st = self._state.get(gid)
            if not st:
                return ""
            p = st["participants"].pop(uid, None)
            text = "，".join([t for t in (p or {}).get("texts", []) if t and t.strip()]) if p else ""
            if not st["participants"] and st["phase"] == "COLLECTING":
                self._cancel_timer(st)
                self._state.pop(gid, None)
            return text

    def take_user(self, group_id, user_id) -> str:
        """同 cancel_user（语义别名，图片路径使用）"""
        return self.cancel_user(group_id, user_id)

    def add_text(self, group_id, user_id, text):
        """续聊合并：把该用户后续文本并入其条目并重置计时"""
        gid = str(group_id or "")
        uid = str(user_id or "")
        text = str(text or "").strip()
        with self._lock:
            st = self._state.get(gid)
            if not st:
                return
            p = st["participants"].get(uid)
            if p is None:
                return
            if text:
                p["texts"].append(text)
                p["has_real_text"] = True
            self._rearm(gid, st, new_user=False)

    def offer(self, item: dict):
        """登记一个触发：合并进当前窗口或开启新窗口。"""
        gid = str(item.get("group_id") or "")
        if not gid:
            return
        uid = str(item.get("user_id") or "")
        with self._lock:
            st = self._state.get(gid)
            # 生成中：排队，本轮结束后再聚合
            if st and st["phase"] == "GENERATING":
                st["queued"].append(item)
                return
            if st is None:
                st = self._new_state(item)
                self._state[gid] = st
            # 关闭跨用户合并：不同用户到来时先派发已存在的，再为本条开新窗
            elif (not self.config.group_merge_enabled) and st["participants"] and uid not in st["participants"]:
                st["queued"].append(item)
                self._arm(gid, st, 0.01)
                return
            else:
                st["queued_rounds"] = 0
            new_user = uid not in st["participants"]
            self._merge(st, item)
            self._rearm(gid, st, new_user=new_user)

    # ==================== 内部 ====================
    def _new_state(self, item: dict) -> dict:
        return {
            "participants": OrderedDict(),
            "anchor": time.time(),
            "deadline": 0.0,
            "timer": None,
            "phase": "COLLECTING",
            "queued": [],
            "queued_rounds": 0,
            "group_name": str(item.get("group_name", "") or ""),
            "self_id": str(item.get("self_id", "") or ""),
        }

    def _merge(self, st: dict, item: dict):
        uid = str(item.get("user_id") or "")
        text = str(item.get("text") or "").strip()
        kind = str(item.get("kind") or "active")
        p = st["participants"].get(uid)
        if p is None:
            p = {"user_id": uid, "username": str(item.get("username", "") or ""),
                 "texts": [], "kinds": set(), "at_self": False,
                 "has_real_text": False, "force": False}
            st["participants"][uid] = p
        if text:
            p["texts"].append(text)
        p["kinds"].add(kind)
        p["at_self"] = bool(p["at_self"] or item.get("at_self"))
        p["has_real_text"] = bool(p["has_real_text"] or item.get("has_real_text"))
        p["force"] = bool(p["force"] or item.get("force"))
        # 群名/self_id 以最新为准
        if item.get("group_name"):
            st["group_name"] = str(item.get("group_name"))
        if item.get("self_id"):
            st["self_id"] = str(item.get("self_id"))

    def _rearm(self, gid: str, st: dict, new_user: bool):
        """重新计算窗口并重置定时器"""
        if st.get("timer") is not None:
            st["timer"].cancel()
            st["timer"] = None
        now = time.time()
        n = len(st["participants"])
        if n >= 2 and self.config.group_merge_enabled:
            base = max(0.05, float(self.config.group_merge_window))
            if self.config.group_merge_sliding:
                deadline = min(now + base, st["anchor"] + float(self.config.group_merge_max_wait))
            else:
                # 从第一个参与者起算的固定窗口，不无限延长
                deadline = st["anchor"] + base
                if deadline <= now:
                    deadline = now + base
            delay = max(0.05, deadline - now)
        else:
            p = next(iter(st["participants"].values())) if n else None
            kinds = p["kinds"] if p else set()
            if p is not None and not (("at" in kinds) or ("keyword" in kinds)):
                # 纯主动触发：不需要等待续聊，用短合并窗口即可
                delay = max(0.05, float(self.config.group_merge_window))
            else:
                delay = random.uniform(float(self.config.group_merge_user_window_min),
                                       float(self.config.group_merge_user_window_max))
        self._arm(gid, st, delay)

    def _arm(self, gid: str, st: dict, delay: float):
        if st.get("timer") is not None:
            st["timer"].cancel()
        st["deadline"] = time.time() + delay
        t = threading.Timer(delay, self._on_timeout, args=(gid,))
        t.daemon = True
        st["timer"] = t
        t.start()

    def _cancel_timer(self, st: dict):
        if st.get("timer") is not None:
            try:
                st["timer"].cancel()
            except Exception:
                pass
            st["timer"] = None

    def _build_merged(self, gid: str, st: dict, participants: "OrderedDict") -> dict:
        plist = []
        at_users = []
        mode = "active"
        for uid, p in participants.items():
            texts = [t for t in p["texts"] if t and t.strip()]
            text = "，".join(texts)
            kinds = p["kinds"]
            directed = bool(p["at_self"]) or ("at" in kinds) or ("keyword" in kinds)
            kind = "at" if "at" in kinds else ("keyword" if "keyword" in kinds else "active")
            plist.append({"user_id": uid, "username": p["username"], "text": text,
                          "kind": kind, "at_self": bool(p["at_self"]),
                          "has_real_text": bool(p["has_real_text"]), "force": bool(p["force"])})
            if directed:
                mode = "at"
                at_users.append({"user_id": uid, "username": p["username"]})
        if len(plist) == 1:
            merged_text = plist[0]["text"] or f"{plist[0]['username'] or '有人'}@了你"
        else:
            lines = [f"【{p['username'] or p['user_id']}】{p['text']}" for p in plist if p["text"]]
            merged_text = "\n".join(lines) or "有人@了你"
        return {"group_id": gid, "group_name": st.get("group_name", ""),
                "self_id": st.get("self_id", ""), "participants": plist,
                "mode": mode, "at_users": at_users, "merged_text": merged_text,
                "force": any(p["force"] for p in plist)}

    def _on_timeout(self, gid: str):
        with self._lock:
            st = self._state.get(gid)
            if not st or st["phase"] != "COLLECTING":
                return
            participants = st["participants"]
            if not participants:
                self._state.pop(gid, None)
                return
            st["participants"] = OrderedDict()
            st["timer"] = None
            st["phase"] = "GENERATING"
            merged = self._build_merged(gid, st, participants)
        # 派发在锁外执行（LLM 可能耗时）
        try:
            if self._flush:
                self.log.info(f"[群聊协调器] 派发群 {gid}：{len(merged['participants'])} 人 / "
                              f"mode={merged['mode']} / {merged['merged_text'][:60]!r}")
                self._flush(gid, merged)
        except Exception:
            self.log.exception("群聊协调器派发异常")
        with self._lock:
            st = self._state.get(gid)
            if not st:
                return
            queued = st.get("queued") or []
            if queued and st["queued_rounds"] < int(self.config.group_merge_max_extra_rounds):
                st["queued"] = []
                st["queued_rounds"] = int(st["queued_rounds"]) + 1
                st["phase"] = "COLLECTING"
                st["anchor"] = time.time()
                for it in queued:
                    self._merge(st, it)
                self._rearm(gid, st, new_user=True)
            else:
                self._state.pop(gid, None)

    def clear(self):
        """清空所有窗口与定时器（停止时调用）"""
        with self._lock:
            for st in self._state.values():
                self._cancel_timer(st)
            self._state.clear()
