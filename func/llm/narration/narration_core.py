# -*- coding: utf-8 -*-
# func/llm/narration/narration_core.py
# AI 回复丰富性打分 + 流式水词清洗

import os
import json
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


class _Node:
    __slots__ = ("children", "is_word", "cats")

    def __init__(self):
        self.children = {}
        self.is_word = False
        self.cats = set()


@singleton
class NarrationCore:
    """打分系统：EWMA 平滑得分，决定清洗档位；维护水词 trie"""

    LEVEL_FULL = 0
    LEVEL_PART = 1
    LEVEL_ALL = 2
    PART_CATS = {2, 3, 5}

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.path = os.path.join("func", "llm", "narration", "adjunct_word.json")
        self.root = _Node()
        self._load()
        self._load_config()
        self.s = float(self.initial_score)
        self._lock = threading.Lock()

    def _load_config(self):
        try:
            from func.pipeline.config_reader import ConfigReader
            cfg = ConfigReader().get("llm", {}).get("narration", {}) or {}
        except Exception:
            cfg = {}
        self.enabled = bool(cfg.get("enabled", True))
        self.initial_score = float(cfg.get("initial_score", 70))
        self.lambda_down = float(cfg.get("lambda_down", 0.75))
        self.lambda_up = float(cfg.get("lambda_up", 0.55))
        self.lambda_equal = float(cfg.get("lambda_equal", 0.70))
        self.density_threshold = float(cfg.get("density_threshold", 0.8))
        self.length_threshold = float(cfg.get("length_threshold", 30))
        self.length_penalty_rate = float(cfg.get("length_penalty_rate", 0.4))
        self.length_penalty_cap = float(cfg.get("length_penalty_cap", 20))
        self.part_level_upper = float(cfg.get("part_level_upper", 60))
        self.part_level_lower = float(cfg.get("part_level_lower", 30))

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, words in (data.items() if isinstance(data, dict) else []):
                cat = int(key)
                for w in (words or []):
                    if not w:
                        continue
                    node = self.root
                    for ch in w:
                        node = node.children.setdefault(ch, _Node())
                    node.is_word = True
                    node.cats.add(cat)
        except Exception:
            self.log.exception("加载水词清单失败")
            self.root = _Node()

    def current_level(self):
        """读取当前平滑得分对应的清洗档位（本轮开始调用）"""
        with self._lock:
            s = self.s
        if s >= self.part_level_upper:
            return self.LEVEL_FULL
        if s >= self.part_level_lower:
            return self.LEVEL_PART
        return self.LEVEL_ALL

    def build_cleaner(self, level):
        return NarrationCleaner(self.root, level)

    def update(self, raw_text):
        """本轮结束：用源文本计算 Raw 并更新平滑得分 S"""
        raw, L, W = self._raw_score(raw_text)
        with self._lock:
            prev = self.s
            if raw < prev:
                lam = self.lambda_down
            elif raw > prev:
                lam = self.lambda_up
            else:
                lam = self.lambda_equal
            self.s = lam * prev + (1 - lam) * raw
            new_s = self.s
        self.log.info(
            f"[narration] Raw={raw:.1f} S={new_s:.1f} "
            f"(prev={prev:.1f} lambda={lam:.2f} L={L} W={W})"
        )
        return raw, new_s

    def _raw_score(self, text):
        L = len(text)
        if L == 0:
            return 70.0, 0, 0
        W = self._count_water(text)
        if L > 0 and (W / L) >= self.density_threshold:
            density = 0.0
        else:
            density = 100.0 - (W / L * 100.0)
        penalty = 0.0
        if L > self.length_threshold:
            penalty = min(self.length_penalty_cap,
                          (L - self.length_threshold) * self.length_penalty_rate)
        return max(0.0, density - penalty), L, W

    def _count_water(self, text):
        total = 0
        for start, end, _cats in self._match_all(text):
            total += end - start
        return total

    def _match_all(self, text):
        result = []
        i = 0
        n = len(text)
        while i < n:
            node = self.root
            matched = None
            j = i
            while j < n and text[j] in node.children:
                node = node.children[text[j]]
                j += 1
                if node.is_word:
                    matched = (j, node.cats)
            if matched:
                end, cats = matched
                result.append((i, end, cats))
                i = end
            else:
                i += 1
        return result


class NarrationCleaner:
    """流式清洗器：最长匹配优先 + 已占用跳过，按档位删除水词"""

    def __init__(self, root, level):
        self.root = root
        self.level = level
        self.buffer = ""
        self.cleaned = ""

    def feed(self, ch):
        if self.level == 0:
            self.cleaned += ch
            return ch
        self.buffer += ch
        out = []
        while self.buffer:
            node = self.root
            matched = None
            i = 0
            while i < len(self.buffer) and self.buffer[i] in node.children:
                node = node.children[self.buffer[i]]
                i += 1
                if node.is_word:
                    matched = (i, node.cats)
            if matched is not None:
                length, cats = matched
                if length == len(self.buffer) and node.children:
                    break
                if not self._should_delete(cats):
                    out.append(self.buffer[:length])
                self.buffer = self.buffer[length:]
                continue
            if self._is_prefix(self.buffer):
                break
            out.append(self.buffer[0])
            self.buffer = self.buffer[1:]
        result = "".join(out)
        self.cleaned += result
        return result

    def flush(self):
        if self.level == 0:
            return ""
        out = []
        while self.buffer:
            node = self.root
            matched = None
            i = 0
            while i < len(self.buffer) and self.buffer[i] in node.children:
                node = node.children[self.buffer[i]]
                i += 1
                if node.is_word:
                    matched = (i, node.cats)
            if matched is not None:
                length, cats = matched
                if not self._should_delete(cats):
                    out.append(self.buffer[:length])
                self.buffer = self.buffer[length:]
            else:
                out.append(self.buffer[0])
                self.buffer = self.buffer[1:]
        result = "".join(out)
        self.cleaned += result
        return result

    def _should_delete(self, cats):
        if self.level == NarrationCore.LEVEL_FULL:
            return False
        if self.level == NarrationCore.LEVEL_PART:
            return bool(cats & NarrationCore.PART_CATS)
        return True

    def _is_prefix(self, s):
        node = self.root
        for ch in s:
            if ch not in node.children:
                return False
            node = node.children[ch]
        return True
