# -*- coding: utf-8 -*-
# func/meowsinger/narration/narration_core.py
# 唱歌评价/感想专用 narration 复制件：水词清洗 + DeepSeek 专属密度稀释。
# 纪律：本文件不 import func.llm / func.pipeline。

import json
import os
import re

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


class _Node:
    __slots__ = ("children", "is_word", "cats", "deletable")

    def __init__(self):
        self.children = {}
        self.is_word = False
        self.cats = set()
        self.deletable = False


class _Cleaner:
    def __init__(self, root, level):
        self.root = root
        self.level = level
        self.buffer = ""
        self.cleaned = ""

    def feed(self, ch):
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
                if not self._drop(cats, deletable):
                    out.append(self.buffer[:length])
                self.buffer = self.buffer[length:]
                continue
            if self._prefix(self.buffer):
                break
            out.append(self.buffer[0])
            self.buffer = self.buffer[1:]
        result = "".join(out)
        self.cleaned += result
        return result

    def flush(self):
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
                if not self._drop(cats, deletable):
                    out.append(self.buffer[:length])
                self.buffer = self.buffer[length:]
            else:
                out.append(self.buffer[0])
                self.buffer = self.buffer[1:]
        result = "".join(out)
        self.cleaned += result
        return result

    def _drop(self, cats, deletable):
        if not deletable:
            return False
        return bool(cats & {2, 3, 5})

    def _prefix(self, s):
        node = self.root
        for ch in s:
            if ch not in node.children:
                return False
            node = node.children[ch]
        return True


@singleton
class SingerNarration:
    """唱歌评价/感想用：水词清洗 + DeepSeek 专属密度稀释。"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        base = os.path.join("func", "meowsinger", "narration")
        self.path = os.path.join(base, "adjunct_word.json")
        self.score_only_path = os.path.join(base, "score_only_word.json")
        self.dilute_path = os.path.join(base, "deepseek_dilute_word.json")
        self.root = _Node()
        self._dilute_rules = []
        self._load_words(self.path, True)
        self._load_words(self.score_only_path, False)
        self._load_dilute()

    def _load_words(self, path, deletable):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, words in (data.items() if isinstance(data, dict) else []):
                cat = int(key)
                for word in (words or []):
                    if not word:
                        continue
                    node = self.root
                    for ch in word:
                        node = node.children.setdefault(ch, _Node())
                    node.is_word = True
                    if deletable:
                        node.cats.add(cat)
                        node.deletable = True
        except Exception:
            self.log.exception("加载唱歌水词清单失败：%s", path)

    def _load_dilute(self):
        rules = []
        try:
            with open(self.dilute_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in (data.get("rules") or []):
                pattern = str(item.get("pattern") or "")
                replacement = str(item.get("replacement") or "")
                if not pattern:
                    continue
                rules.append({
                    "rx": re.compile(pattern) if item.get("regex") else None,
                    "pattern": pattern,
                    "replacement": replacement,
                    "last": bool(item.get("last")),
                })
        except Exception:
            self.log.exception("加载唱歌稀释清单失败：%s", self.dilute_path)

        def weight(item):
            if item.get("last"):
                return -1
            pattern = item["pattern"]
            if item["rx"] is not None:
                m = re.search(r"[\(\[\{\*\+\?\^\$\|\\]", pattern)
                return len(pattern[:m.start()]) if m else len(pattern)
            return len(pattern)

        rules.sort(key=weight, reverse=True)
        self._dilute_rules = rules

    def dilute(self, text: str) -> str:
        s = str(text or "")
        for rule in self._dilute_rules:
            if rule["rx"] is not None:
                s = rule["rx"].sub(rule["replacement"], s)
            else:
                s = s.replace(rule["pattern"], rule["replacement"])
        return s

    def clean_complete(self, text: str) -> str:
        s = str(text or "")
        if not s:
            return s
        cleaner = _Cleaner(self.root, 1)
        for ch in s:
            cleaner.feed(ch)
        cleaner.flush()
        return str(cleaner.cleaned or "").strip()

    def clean(self, text: str) -> str:
        return self.clean_complete(self.dilute(text))
