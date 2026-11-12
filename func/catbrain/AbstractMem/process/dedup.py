# -*- coding: utf-8 -*-
import difflib
import re
import hashlib

from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.process.evidence import MeowEvidence
from func.catbrain.AbstractMem import joint_util


class MeowDedup:
    """摘要记忆更新类"""

    # 同一事件被模型用不同措辞写两遍时（如“陪他”/“陪着”），
    # 归一化文本仍会差一个字，稳定主键不同，需要近似文本兜底。
    NEAR_DUP_RATIO = 0.92
    # 同一分钟写入、标签高度重合的，允许更低的文本相似度（同一次概括里的改写）
    SAME_TIME_RATIO = 0.62
    SAME_TIME_TAG_JACCARD = 0.5
    SAME_TIME_LEN_RATIO = 0.6

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
        owner = joint_util.owner(event)
        raw = f"{self._norm_text(event.get('event', ''))}|{owner}"
        return "mem_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _tags(item):
        """标签集合（用于同分钟改写的辅助判定）"""
        return {str(t).strip() for t in (item.get("tags") or []) if str(t).strip()}

    def find_near(self, event, candidates):
        """找同一天、同类型、同参与者的近似重复事件；没有则返回 None

        两级判定：
        - 文本相似度 >= 0.92：直接视为同一事件；
        - 同一分钟 + 标签 Jaccard >= 0.5 + 长度接近 + 相似度 >= 0.62：
          同一次概括里被改写成不同说法的同一件事。
        """
        text = self._norm_text(event.get("event", ""))
        if not text:
            return None
        kind = event.get("kind")
        owner = joint_util.owner(event)
        day = str(event.get("time") or "")[:10]
        stamp = str(event.get("time") or "")
        tags_a = self._tags(event)
        best, best_ratio = None, 0.0
        for item in candidates or []:
            if not isinstance(item, dict):
                continue
            if kind and item.get("kind") and item.get("kind") != kind:
                continue
            if owner and joint_util.owner(item) and joint_util.owner(item) != owner:
                continue
            if day and str(item.get("time") or "")[:10] != day:
                continue
            other = self._norm_text(item.get("event", ""))
            if not other:
                continue
            ratio = difflib.SequenceMatcher(None, text, other).ratio()
            accept = ratio >= self.NEAR_DUP_RATIO
            if not accept and stamp and stamp == str(item.get("time") or ""):
                tags_b = self._tags(item)
                union = tags_a | tags_b
                jaccard = (len(tags_a & tags_b) / len(union)) if union else 0.0
                length_ratio = min(len(text), len(other)) / max(len(text), len(other))
                accept = (ratio >= self.SAME_TIME_RATIO
                          and jaccard >= self.SAME_TIME_TAG_JACCARD
                          and length_ratio >= self.SAME_TIME_LEN_RATIO)
            if accept and ratio > best_ratio:
                best, best_ratio = item, ratio
        return best

    @staticmethod
    def _merge_list(item, key, values):
        """合并列表字段并去重保序"""
        current = list(item.get(key) or [])
        for v in (values or []):
            v = str(v).strip()
            if v and v not in current:
                current.append(v)
        item[key] = current

    def _apply_same(self, item, event, now_iso, delta=None, accuracy_step=None):
        """强化已有记忆：累加证据、合并标签，不改写原文"""
        evidence = item.setdefault("evidence", {})
        self.evidence.apply_signal(evidence, "same", now_iso, delta)
        step = self.config.accuracy_same_increment if accuracy_step is None else accuracy_step
        if step:
            acc = int(item.get("accuracy", 5) or 5)
            item["accuracy"] = min(5, acc + step)
        self._merge_list(item, "tags", event.get("tags"))
        self._merge_list(item, "topics", event.get("topics"))
        item["joint"] = joint_util.merge(item.get("joint"), event.get("joint"))
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
