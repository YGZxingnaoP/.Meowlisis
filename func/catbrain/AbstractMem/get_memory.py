# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/get_memory.py
# 记忆摘要缓存：所有用户混杂记录于 .temp/record.txt，首行为轮次计数

import os
import threading
from threading import Thread

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.update_abmem import MeowUpdateAbstractMemory


class MeowGetMemory:
    """摘要缓存类：混杂写入 .temp/record.txt，首行计数，达到轮数后触发概括并清空"""

    # 首行轮次计数格式
    COUNT_PREFIX = "#rounds:"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.temp_dir = ".temp"
        self.path = os.path.join(self.temp_dir, "record.txt")
        self._lock = threading.Lock()
        self._updater = MeowUpdateAbstractMemory()

    def cache_message(self, line: str):
        """缓存单条消息（所有用户混杂），累计到配置轮数后取出内容并异步触发概括"""
        os.makedirs(self.temp_dir, exist_ok=True)
        with self._lock:
            lines = self._read_lines()
            count, body_start = self._parse_count(lines)
            count += 1
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.write(self.COUNT_PREFIX + str(count) + "\n")
                    f.writelines(lines[body_start:])
                    f.write(line + "\n")
            except Exception:
                self.log.exception("摘要缓存写入失败")
                return
            if count >= self.config.summary_rounds:
                self._take_and_summarize()

    def _take_and_summarize(self):
        """取出缓存正文（跳过首行计数）并清空（调用方已持锁），随后异步触发概括"""
        lines = self._read_lines()
        count, body_start = self._parse_count(lines)
        content = "".join(lines[body_start:])
        if not content.strip():
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(self.COUNT_PREFIX + "0\n")
        except Exception:
            self.log.exception("清空摘要缓存失败")
            return
        Thread(target=self._summarize_worker, args=(content, count), daemon=True).start()

    def _summarize_worker(self, content: str, rounds: int):
        """异步概括：失败时把原文写回缓存，避免丢数据"""
        ok = self._updater.summarize(content, rounds)
        if not ok:
            with self._lock:
                try:
                    lines = self._read_lines()
                    _, body_start = self._parse_count(lines)
                    restored = max(0, content.count("\n"))
                    with open(self.path, "w", encoding="utf-8") as f:
                        f.write(self.COUNT_PREFIX + str(restored) + "\n")
                        f.writelines(lines[body_start:])
                        f.write(content)
                except Exception:
                    self.log.exception("摘要失败后写回缓存失败")

    def _read_lines(self) -> list:
        """读取缓存文件全部行（不存在时返回空列表）"""
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return f.readlines()
        except Exception:
            self.log.exception("读取摘要缓存失败")
            return []

    def _parse_count(self, lines: list):
        """解析首行轮次计数，返回(计数值, 正文起始行索引)"""
        if lines and lines[0].startswith(self.COUNT_PREFIX):
            try:
                return int(lines[0][len(self.COUNT_PREFIX):].strip()), 1
            except ValueError:
                pass
        return 0, 0
