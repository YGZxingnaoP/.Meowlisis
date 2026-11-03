# -*- coding: utf-8 -*-
# func/toolbox/napcat/reply/followup.py
# QQ 群聊追聊链路（窗口 / 接力）（自 func/toolbox/qq_response.py 原样拆出，行为不变）


class FollowupReplyMixin:
    """QQ 群聊追聊链路（窗口 / 接力）"""
    def _followup_feed(self, parsed: dict) -> bool:
        """续聊会话内的普通消息：交给协调器合并（kind=followup），返回 True=已消费"""
        if not self.napcat_config.group_followup_enabled:
            return False
        if self.napcat_config.group_followup_skip_bots and self._is_bot(parsed.get("user_id")):
            return False
        text = str(parsed.get("text") or "").strip()
        if not text:
            text = self._extract_emote_text(parsed.get("raw_message"))
        if not text:
            return False
        from func.toolbox.napcat.groupchat.group_followup import TBGroupFollowup
        if not TBGroupFollowup().active(parsed.get("group_id")):
            return False
        self._coord().offer({
            "group_id": str(parsed.get("group_id", "")),
            "group_name": str(parsed.get("group_name", "") or ""),
            "user_id": str(parsed.get("user_id", "")),
            "username": str(parsed.get("username", "") or ""),
            "self_id": str(parsed.get("self_id", "") or ""),
            "text": text,
            "kind": "followup", "at_self": False, "has_real_text": True,
        })
        return True

    def _followup_arm(self, gid, group_name, self_id, user, text, trigger):
        if not self.napcat_config.group_followup_enabled:
            return
        from func.toolbox.napcat.groupchat.group_followup import TBGroupFollowup
        TBGroupFollowup().arm(gid, group_name, self_id, user or {}, text, trigger or "@")

    def _followup_note(self, gid, final):
        if not self.napcat_config.group_followup_enabled:
            return
        from func.toolbox.napcat.groupchat.group_followup import TBGroupFollowup
        TBGroupFollowup().note_reply(gid, final)

    def _reply_group_followup(self, gid: str, group_name: str, self_id: str, merged: dict):
        """续聊批次：先由判断器决定要不要接，再走与 @ 同一条回复链路（记忆写 qq_groupchat）"""
        from func.toolbox.napcat.groupchat.group_followup import TBGroupFollowup
        from func.toolbox.napcat.analysis.followup_judge import TBNapcatFollowupJudge
        participants = merged.get("participants") or []
        merged_text = str(merged.get("merged_text") or "")
        followup = TBGroupFollowup()
        if not followup.active(gid) or not participants:
            return
        ctx = followup.judge_context(gid, self_id, merged_text, participants, group_name)
        verdict = TBNapcatFollowupJudge().judge(ctx)
        reason = str(verdict.get("reason") or "")
        if str(verdict.get("decision") or "") != "continue":
            ended = followup.mark_pass(gid)
            self.log.info(f"[群续聊] pass 群 {group_name}：{reason[:60]}")
            if ended:
                self.log.info(f"[群续聊] 连续 pass 达到上限，结束监听（群 {group_name}）")
            return
        target = self._followup_target(verdict.get("target"), participants)
        final = self._reply_group_directed(gid, group_name, self_id, merged_text, participants,
                                           [target] if target else [], followup=True,
                                           trigger="followup")
        followup.note_reply(gid, final)
        if followup.mark_reply(gid):
            self.log.info(f"[群续聊] 达到最大轮数，会话结束（群 {group_name}）")
        self.log.info(f"[群续聊] continue 群 {group_name}：{reason[:40]} → {(final or '')[:30]}")

    @staticmethod
    def _followup_target(raw, participants) -> dict:
        want = str(raw or "").strip()
        rows = [p for p in (participants or []) if isinstance(p, dict)]
        if not rows:
            return {}
        if want:
            for row in rows:
                if want in (str(row.get("user_id") or ""), str(row.get("username") or "")):
                    return row
            for row in rows:
                if want in str(row.get("username") or ""):
                    return row
        return rows[0]
