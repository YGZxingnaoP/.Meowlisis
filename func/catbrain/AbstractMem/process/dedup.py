# -*- coding: utf-8 -*-
import re
import hashlib

from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.process.evidence import MeowEvidence


class MeowDedup:
    """摘要记忆更新类"""

    def __init__(self):
        """加载配置与证据函数"""
        self.config = MeowCatBrainConfig()
        self.evidence = MeowEvidence()

    @staticmethod
    def _norm_text(text) -> str:
        """归一化事件文本用于稳定主键"""
        return re.sub(r"[\s。，！？、,.!?;；:：~～·…—\-—_\"'“”‘’（）()【】\[\]]+", "", str(text or ""))

    def make_id(self, event):
        """生成事件稳定主键（归一化文本 + 首个参与用户）"""
        joint = event.get("joint") or []
        owner = str(joint[0]).strip() if joint else ""
        raw = f"{self._norm_text(event.get('event', ''))}|{owner}"
        return "mem_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _merge_list(item, key, values):
        """合并列表字段并去重保序"""
        current = list(item.get(key) or [])
        for v in (values or []):
            v = str(v).strip()
            if v and v not in current:
                current.append(v)
        item[key] = current

    def _apply_same(self, item, event, now_iso):
        """强化已有记忆：累加证据、合并标签，不改写原文"""
        evidence = item.setdefault("evidence", {})
        self.evidence.apply_signal(evidence, "same", now_iso)
        acc = int(item.get("accuracy", 5) or 5)
        item["accuracy"] = min(5, acc + self.config.accuracy_same_increment)
        self._merge_list(item, "tags", event.get("tags"))
        self._merge_list(item, "topics", event.get("topics"))
        self._merge_list(item, "joint", event.get("joint"))
        try:
            old_imp = float(item.get("importance", 0) or 0)
            new_imp = float(event.get("importance", 0) or 0)
            item["importance"] = max(old_imp, new_imp)
        except (TypeError, ValueError):
            pass

    def _apply_opposite(self, item, now_iso):
        """削弱已有记忆：累加质疑并降低准确度"""
        evidence = item.setdefault("evidence", {})
        self.evidence.apply_signal(evidence, "opposite", now_iso)
        acc = int(item.get("accuracy", 5) or 5)
        item["accuracy"] = max(1, acc - self.config.accuracy_opposite_decrement)

    def _init_evidence(self, event, now_iso):
        """为新事件初始化证据字段"""
        rein = self.evidence.initial_reinforcement(event.get("importance", 0))
        event["evidence"] = {
            "reinforcement": rein,
            "disputation": 0.0,
            "rein_last_signal_at": now_iso if rein > 0 else None,
            "disp_last_signal_at": None,
            "sub_zero_days": 0,
            "sub_zero_last_increment_date": None
        }
