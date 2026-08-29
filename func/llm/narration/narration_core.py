# -*- coding: utf-8 -*-
# func/llm/narration/narration_core.py
# AI 回复丰富性打分 + 流式水词清洗

import os
import json
import datetime
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


class _Node:
    __slots__ = ("children", "is_word", "cats", "deletable")

    def __init__(self):
        self.children = {}
        self.is_word = False
        self.cats = set()
        self.deletable = False


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
        self.score_only_path = os.path.join("func", "llm", "narration", "score_only_word.json")
        self.root = _Node()
        self._load()
        self._load_config()
        self.s = float(self.initial_score)
        self._lock = threading.Lock()
        self._score_lock = threading.Lock()
        self.score_path = os.path.join("character", "memory", "llm_response_score.json")
        self.session_key = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
        self.score_log_enabled = bool(cfg.get("score_log_enabled", False))

    def _load(self):
        # 可删除水词：参与打分，也参与过滤删除
        self._load_words(self.path, deletable=True)
        # 只打分不删除的词（人设语气等）：计入 W，但清洗时原样保留
        self._load_words(self.score_only_path, deletable=False)

    def _load_words(self, path, deletable):
        try:
            with open(path, "r", encoding="utf-8") as f:
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
                    if deletable:
                        node.cats.add(cat)
                        node.deletable = True
        except FileNotFoundError:
            # score_only_word.json 允许不存在
            if deletable:
                self.log.exception("加载水词清单失败：%s", path)
        except Exception:
            self.log.exception("加载水词清单失败：%s", path)

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
        if self.score_log_enabled:
            self._log_score(raw, new_s)
        return raw, new_s

    def _log_score(self, raw: float, smooth: float):
        """把本轮原始/平滑得分追加到当前启动分组的分数记录文件"""
        try:
            os.makedirs(os.path.dirname(self.score_path), exist_ok=True)
            with self._score_lock:
                data = {}
                if os.path.exists(self.score_path):
                    with open(self.score_path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data = loaded
                data.setdefault(self.session_key, []).append({
                    "raw": round(float(raw), 2),
                    "smooth": round(float(smooth), 2),
                })
                with open(self.score_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入分数记录失败")

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
        for start, end, _cats, _deletable in self._match_all(text):
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
                    matched = (j, node.cats, node.deletable)
            if matched:
                end, cats, deletable = matched
                result.append((i, end, cats, deletable))
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
                    matched = (i, node.cats, node.deletable)
            if matched is not None:
                length, cats, deletable = matched
                if length == len(self.buffer) and node.children:
                    break
                if not self._should_delete(cats, deletable):
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
                    matched = (i, node.cats, node.deletable)
            if matched is not None:
                length, cats, deletable = matched
                if not self._should_delete(cats, deletable):
                    out.append(self.buffer[:length])
                self.buffer = self.buffer[length:]
            else:
                out.append(self.buffer[0])
                self.buffer = self.buffer[1:]
        result = "".join(out)
        self.cleaned += result
        return result

    def _should_delete(self, cats, deletable):
        if not deletable:
            return False
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
