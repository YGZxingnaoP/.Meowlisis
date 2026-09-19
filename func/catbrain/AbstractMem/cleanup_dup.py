# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/cleanup_dup.py
# 摘要重复条目一次性清洗：按归一化文本合并重复、封顶证据分，写入前整体备份

import os
import re
import json
import datetime

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory


class MeowDupCleanup:
    """摘要重复条目清洗类：合并同文本条目、封顶证据分，重写前整体备份"""

    # 归一化时需要剔除的空白与标点
    PUNCT_PATTERN = r"[\s。，！？、,.!?;；:：~～·…—\-—_\"'“”‘’（）()【】\[\]]+"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.loader = MeowLoadAbstractMemory()
        self.meow_dir = os.path.join("character", "abstract_memory")
        self.backup_dir = os.path.join(self.meow_dir, "_backup")

    @classmethod
    def _key(cls, item) -> str:
        """条目归一化键（去空白与标点）"""
        return re.sub(cls.PUNCT_PATTERN, "", str(item.get("event") or ""))

    @staticmethod
    def _merge_list(a, b) -> list:
        """合并两个列表字段（去重保序）"""
        result = list(a or [])
        for v in (b or []):
            v = str(v).strip()
            if v and v not in result:
                result.append(v)
        return result

    @staticmethod
    def _number(value) -> float:
        """数值安全转换（失败按 0 处理）"""
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _merge(self, items: list) -> dict:
        """把同文本的多条合并为一条（保留最早时间与首个 id，证据取最大并封顶）"""
        items = sorted(items, key=lambda x: str(x.get("time") or ""))
        base = dict(items[0])
        cap = self._number(self.config.rank_evidence_saturation) or 5.0
        reinforcement = 0.0
        disputation = 0.0
        for item in items:
            evidence = item.get("evidence") or {}
            reinforcement = max(reinforcement, self._number(evidence.get("reinforcement")))
            disputation = max(disputation, self._number(evidence.get("disputation")))
            base["tags"] = self._merge_list(base.get("tags"), item.get("tags"))
            base["topics"] = self._merge_list(base.get("topics"), item.get("topics"))
            base["joint"] = self._merge_list(base.get("joint"), item.get("joint"))
            base["accuracy"] = int(max(self._number(base.get("accuracy")), self._number(item.get("accuracy"))))
            base["importance"] = max(self._number(base.get("importance")), self._number(item.get("importance")))
        evidence = dict(base.get("evidence") or {})
        evidence["reinforcement"] = min(reinforcement, cap)
        evidence["disputation"] = disputation
        base["evidence"] = evidence
        return base

    def run(self, min_importance=None, llm_dedup=False) -> dict:
        """执行清洗：备份 → 合并同文本 → 可选低重要度过滤/语义去重 → 重写摘要文件

        - min_importance：传入数值时丢弃 importance 低于该值的条目（None 表示不过滤）
        - llm_dedup：保留参数以兼容旧调用，语义合并已随新版流程移除
        """
        data = self.loader.load()
        if not data:
            return {"before": 0, "after": 0, "merged": 0, "dropped": 0}
        self._backup(data)
        groups = {}
        others = []
        for item in data:
            if not isinstance(item, dict):
                others.append(item)
                continue
            key = self._key(item)
            if not key:
                others.append(item)
                continue
            groups.setdefault(key, []).append(item)
        merged = [self._merge(items) for items in groups.values()] + others
        exact_merged = len(data) - len(merged)

        dropped = 0
        if min_importance is not None:
            kept = []
            for item in merged:
                if isinstance(item, dict):
                    importance = self._number(item.get("importance"))
                    if importance < float(min_importance):
                        dropped += 1
                        continue
                kept.append(item)
            merged = kept

        if llm_dedup and merged:
            try:
                from func.catbrain.AbstractMem.process.dedup import MeowDedup
                MeowDedup()
            except Exception:
                self.log.exception("语义去重不可用，跳过该步骤")

        merged.sort(key=lambda x: str(x.get("time") or ""))
        self._clear_files()
        self.loader.save(merged)
        result = {"before": len(data), "after": len(merged),
                  "merged": exact_merged, "dropped": dropped}
        self.log.info(f"摘要清洗完成: {result}")
        return result

    def _backup(self, data: list):
        """把清洗前的全部条目备份到 _backup/merge_时间戳.json"""
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.backup_dir, f"merge_{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.log.info(f"摘要清洗备份完成: {path}")

    def _clear_files(self):
        """删除旧的分月摘要文件（已备份，交由 save 按月份重写）"""
        for fname in os.listdir(self.meow_dir):
            if fname.startswith("meow-") and fname.endswith(".json"):
                try:
                    os.remove(os.path.join(self.meow_dir, fname))
                except Exception:
                    self.log.exception(f"删除旧摘要文件失败: {fname}")


if __name__ == "__main__":
    import sys
    min_importance = None
    llm_dedup = "--llm" in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith("--min-importance="):
            try:
                min_importance = float(arg.split("=", 1)[1])
            except ValueError:
                pass
    print(MeowDupCleanup().run(min_importance=min_importance, llm_dedup=llm_dedup))
