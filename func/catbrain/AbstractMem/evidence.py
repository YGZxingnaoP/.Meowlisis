# -*- coding: utf-8 -*-
"""摘要证据纯函数：衰减、净分数、状态、信号应用与负分标记"""
from datetime import datetime

from func.catbrain.catbrain import MeowCatBrainConfig


class MeowEvidence:
    """摘要证据纯函数类"""

    def __init__(self):
        self.config = MeowCatBrainConfig()

    def initial_reinforcement(self, importance):
        """按 importance 映射初始强化值"""
        try:
            imp = int(importance)
        except (ValueError, TypeError):
            return 0.0
        for threshold, seed in ((10, 0.8), (9, 0.6), (8, 0.4), (7, 0.2)):
            if imp >= threshold:
                return seed
        return 0.0

    @staticmethod
    def _age_days(ts, now):
        """计算时间戳距今的天数"""
        if not ts:
            return 0.0
        try:
            parsed = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return 0.0
        delta = (now - parsed).total_seconds()
        if delta <= 0:
            return 0.0
        return delta / 86400

    def effective_reinforcement(self, evidence, now):
        """计算衰减后的强化值"""
        r = float(evidence.get("reinforcement", 0.0) or 0.0)
        if r == 0.0:
            return r
        age = self._age_days(evidence.get("rein_last_signal_at"), now)
        if age == 0.0:
            return r
        return r * (0.5 ** (age / self.config.evidence_rein_half_life_days))

    def effective_disputation(self, evidence, now):
        """计算衰减后的质疑值"""
        d = float(evidence.get("disputation", 0.0) or 0.0)
        if d == 0.0:
            return d
        age = self._age_days(evidence.get("disp_last_signal_at"), now)
        if age == 0.0:
            return d
        return d * (0.5 ** (age / self.config.evidence_disp_half_life_days))

    def score(self, evidence, now):
        """计算净证据分数"""
        return self.effective_reinforcement(evidence, now) - self.effective_disputation(evidence, now)

    def status(self, evidence, now):
        """推导证据状态"""
        s = self.score(evidence, now)
        if s >= self.config.evidence_confirmed_threshold:
            return "confirmed"
        if s <= self.config.evidence_archive_threshold:
            return "archive_candidate"
        return "pending"

    def apply_signal(self, evidence, relation, now_iso):
        """应用 same/opposite 信号"""
        if relation == "same":
            evidence["reinforcement"] = float(evidence.get("reinforcement", 0.0) or 0.0) + self.config.evidence_same_delta
            evidence["rein_last_signal_at"] = now_iso
        elif relation == "opposite":
            evidence["disputation"] = float(evidence.get("disputation", 0.0) or 0.0) + self.config.evidence_opposite_delta
            evidence["disp_last_signal_at"] = now_iso
        return evidence

    def mark_sub_zero(self, evidence, now):
        """负分标记：每天最多累计一次"""
        if self.score(evidence, now) >= 0:
            return False
        today = now.date().isoformat()
        if evidence.get("sub_zero_last_increment_date") == today:
            return False
        evidence["sub_zero_days"] = int(evidence.get("sub_zero_days", 0) or 0) + 1
        evidence["sub_zero_last_increment_date"] = today
        return True
