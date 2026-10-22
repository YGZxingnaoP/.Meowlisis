# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/group_followup.py
# 群聊 AT / 关键词触发后的续聊会话表：只记录会话与锚点，不做语义判断

import threading
import time
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.config import TBNapCatConfig


@singleton
class TBGroupFollowup:
    """每群续聊会话：@ / 关键词回复后进入持续监听状态。

    - arm：回复派发时开启，重复触发只刷新锚点（不叠加会话）；
    - active：该群是否仍处于监听状态（无时间窗，仅由配置/最大轮数/停止结束）；
    - judge_context：产出判断材料（锚点 + 最近群聊 + 本批消息）；
    - 本类不批量、不起线程、不判语义：合并交给 TBGroupReplyCoordinator，
      判断交给 TBNapcatFollowupJudge。
    """

    MEMBER_LIMIT = 30

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self._lock = threading.Lock()
        self._state: Dict[str, dict] = {}

    # ==================== 会话状态 ====================
    def active(self, group_id) -> bool:
        with self._lock:
            return bool(self._state.get(str(group_id or "")))

    def arm(self, group_id, group_name, self_id, user: dict, text: str, trigger: str = "@"):
        gid = str(group_id or "")
        if not gid:
            return
        user = user or {}
        now = time.time()
        with self._lock:
            st = dict(self._state.get(gid) or {})
            st.update({
                "group_name": str(group_name or st.get("group_name") or ""),
                "self_id": str(self_id or st.get("self_id") or ""),
                "anchor_qq": str(user.get("user_id") or st.get("anchor_qq") or ""),
                "anchor_name": str(user.get("username") or st.get("anchor_name") or ""),
                "anchor_text": str(text or "").strip(),
                "trigger": str(trigger or "@"),
                "last_reply": "",
                "last_reply_at": now,
                "armed_at": now,
                "rounds": 0,
                "passes": 0,
            })
            self._state[gid] = st
        self.log.info(
            f"[群续聊] arm 群 {st['group_name'] or gid}：{st['trigger']} 触发，"
            f"锚点 {st['anchor_name'] or st['anchor_qq']}"
        )

    def note_reply(self, group_id, final: str):
        gid = str(group_id or "")
        with self._lock:
            st = self._state.get(gid)
            if not st:
                return
            body = str(final or "").strip()
            if body and body.lower() != "pass":
                st["last_reply"] = body
            st["last_reply_at"] = time.time()

    def mark_pass(self, group_id) -> bool:
        gid = str(group_id or "")
        with self._lock:
            st = self._state.get(gid)
            if not st:
                return False
            st["passes"] = int(st.get("passes") or 0) + 1
            limit = int(getattr(self.config, "group_followup_max_passes", 5) or 0)
            if limit > 0 and st["passes"] >= limit:
                self._state.pop(gid, None)
                return True
            return False

    def mark_reply(self, group_id) -> bool:
        gid = str(group_id or "")
        with self._lock:
            st = self._state.get(gid)
            if not st:
                return False
            st["rounds"] = int(st.get("rounds") or 0) + 1
            st["passes"] = 0
            limit = int(getattr(self.config, "group_followup_max_rounds", 0) or 0)
            if limit > 0 and st["rounds"] >= limit:
                self._state.pop(gid, None)
                return True
            return False

    def disarm(self, group_id):
        with self._lock:
            self._state.pop(str(group_id or ""), None)

    def clear(self):
        with self._lock:
            self._state.clear()

    # ==================== 判断材料 ====================
    def judge_context(self, group_id, self_id, batch: str, participants, group_name: str = "") -> dict:
        gid = str(group_id or "")
        with self._lock:
            st = dict(self._state.get(gid) or {})
        now = time.time()
        sid = str(self_id or st.get("self_id") or "")
        return {
            "group_id": gid,
            "group_name": str(group_name or st.get("group_name") or ""),
            "self_id": sid,
            "self_name": str(getattr(self.config, "self_nickname", "") or ""),
            "aliases": self._aliases(),
            "members": self._members(gid),
            "trigger": str(st.get("trigger") or "@"),
            "anchor": {"user_id": st.get("anchor_qq", ""), "username": st.get("anchor_name", "")},
            "anchor_text": str(st.get("anchor_text") or ""),
            "last_reply": str(st.get("last_reply") or ""),
            "elapsed": self._elapsed(now - float(st.get("last_reply_at") or now)),
            "history": self._history(gid, sid),
            "batch": str(batch or ""),
            "batch_count": len([ln for ln in str(batch or "").split("\n") if ln.strip()]),
            "participants": [dict(p) for p in (participants or []) if isinstance(p, dict)],
        }

    def _aliases(self) -> List[str]:
        out: List[str] = []
        names = [getattr(self.config, "self_nickname", "")]
        names += list(getattr(self.config, "group_keywords", []) or [])
        for name in names:
            s = str(name or "").strip()
            if s and s not in out:
                out.append(s)
        return out

    def _members(self, group_id: str) -> List[str]:
        try:
            from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
            rows = TBGetGroupRecord().members(group_id)
        except Exception:
            self.log.exception("[群续聊] 拉取群成员失败")
            return []
        self_name = str(getattr(self.config, "self_nickname", "") or "").strip()
        out: List[str] = []
        for row in rows or []:
            name = str(row.get("name") or "").strip()
            if name and name != self_name and name not in out:
                out.append(name)
            if len(out) >= self.MEMBER_LIMIT:
                break
        return out

    def _history(self, group_id: str, self_id: str) -> List[str]:
        try:
            from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
            from func.toolbox.napcat.groupchat.get_group_message import TBGetGroupMessage
            limit = int(getattr(self.config, "group_followup_judge_history", 20) or 20)
            rows = TBGetGroupRecord().fetch_raw(group_id, limit=limit)
        except Exception:
            self.log.exception("[群续聊] 拉取群历史失败")
            return []
        self_name = str(getattr(self.config, "self_nickname", "") or "").strip()
        out: List[str] = []
        for row in rows or []:
            try:
                segments = TBGetGroupMessage._parse_segments(row.get("message"))
            except Exception:
                continue
            if not segments:
                continue
            sender = row.get("sender") or {}
            uid = str(row.get("user_id") or sender.get("user_id") or "")
            name = str(sender.get("card") or sender.get("nickname") or uid or "").strip()
            if self_id and uid == self_id:
                name = f"{self_name or name or self_id}（角色本人）"
            out.append(f"【{name or uid}】: {'，'.join(segments)}")
        return out

    @staticmethod
    def _elapsed(seconds) -> str:
        try:
            sec = max(0.0, float(seconds or 0))
        except (TypeError, ValueError):
            sec = 0.0
        if sec < 60:
            return f"刚刚（{int(sec)} 秒前）"
        if sec < 3600:
            return f"{int(sec // 60)} 分钟前"
        if sec < 86400:
            return f"{int(sec // 3600)} 小时前"
        return f"{int(sec // 86400)} 天前"
