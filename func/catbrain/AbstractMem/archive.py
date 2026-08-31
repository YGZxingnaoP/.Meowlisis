# -*- coding: utf-8 -*-
"""摘要归档：负分累计扫描并移入 wrong_mem.json"""
import os
import json
from datetime import datetime

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.evidence import MeowEvidence
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory


class MeowArchive:
    """摘要归档类"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.evidence = MeowEvidence()
        self.loader = MeowLoadAbstractMemory()
        self.meow_dir = os.path.join("character", "abstract_memory")
        self.wrong_path = os.path.join(self.meow_dir, "wrong_mem.json")

    def scan(self) -> int:
        """扫描负分条目并归档，返回本次归档条数"""
        data = self.loader.load()
        if not data:
            return 0
        now = datetime.now()
        kept = []
        archived = []
        for item in data:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            evidence = item.get("evidence")
            if not isinstance(evidence, dict):
                kept.append(item)
                continue
            if self.evidence.score(evidence, now) < 0:
                self.evidence.mark_sub_zero(evidence, now)
                if int(evidence.get("sub_zero_days", 0) or 0) >= self.config.evidence_archive_days:
                    archived.append(item)
                    continue
            kept.append(item)
        if archived:
            self._append_wrong(archived)
            self.log.info(f"摘要归档 {len(archived)} 条")
        self.loader.save(kept)
        return len(archived)

    def _append_wrong(self, archived):
        """把归档条目追加到 wrong_mem.json"""
        os.makedirs(self.meow_dir, exist_ok=True)
        existing = []
        try:
            if os.path.exists(self.wrong_path):
                with open(self.wrong_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    existing = data
        except Exception:
            self.log.exception("读取 wrong_mem.json 失败")
        existing.extend(archived)
        try:
            with open(self.wrong_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入 wrong_mem.json 失败")
