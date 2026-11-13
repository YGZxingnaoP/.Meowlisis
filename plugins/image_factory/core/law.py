# -*- coding: utf-8 -*-
"""提示词法典检索（自包含实现，只读 md 数据，不 import 主项目）。

主项目那份 ANIMA3 法典是纯文本 md，这里按标题切章，用「关键词命中」打分检索：
  · 标题命中权重高，正文命中权重低；
  · §0~§4 / §15 作为常驻规则区整段带上（输出协议、槽位、配额、互斥）；
  · 检索预算有上限，避免把整本法典塞进提示词。
与主项目逻辑同源，但代码独立，插件可单独拷走。
"""

import os
import re

# 常驻章节前缀：内容少、但几乎每张图都要遵守
ALWAYS_PREFIX = ("0.", "1.", "2.", "3.", "4.", "15.")
ALWAYS_WORDS = ("互斥", "冲突", "镜头", "视角", "景别", "POV", "构图", "分镜", "视线",
                "槽位", "配额", "成年", "露出", "服装", "材质")

STOP = set("""的 了 一个 一张 想要 想 给我 帮我 来张 我 你 她 他 它 和 就 在 把 像 一样 那种
这个 那个 吧 啊 呀 哦 嗯 看 到 着 是 有 要 会 能 让 给 也 都 很 真 挺 主人 喵 请 帮""".split())


class PromptLaw:
    """ANIMA3 法典（角色/服装/场景/动作/成年向词汇都在里面）"""

    def __init__(self, path, log=None, budget=24000, per_section=2200, top=6):
        """记录法典路径、预算与章节上限。"""
        self.path = str(path or "")
        self.log = log
        self.budget = int(budget)
        self.per_section = int(per_section)
        self.top = int(top)
        self._sections = None
        self._head = ""

    # ---------- 载入 ----------
    def available(self):
        """法典文件是否可用。"""
        return bool(self.path) and os.path.isfile(self.path)

    def _load(self):
        """惰性解析法典：规则区 + 章节 + 关键词。"""
        if self._sections is not None:
            return
        self._sections, self._head = [], ""
        if not self.available():
            if self.log:
                self.log.warning("[image_factory] 法典不存在: %s" % self.path)
            self._sections = []
            return
        try:
            text = open(self.path, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            text = ""
        sections, cur = [], {"title": "(前言)", "text": []}
        for line in text.splitlines():
            m = re.match(r"^(\#{1,4})\s+(.*)$", line.strip())
            if m:
                if cur["text"]:
                    sections.append(cur)
                cur = {"title": m.group(2).strip(), "text": []}
            else:
                cur["text"].append(line)
        if cur["text"]:
            sections.append(cur)
        rules = []
        for sec in sections:
            if sec["title"].startswith(ALWAYS_PREFIX):
                rules.append("### %s\n%s" % (sec["title"], "\n".join(sec["text"])))
        self._sections = sections
        self._head = "\n".join(rules)

    # ---------- 检索 ----------
    @staticmethod
    def _words(query):
        """把检索词切成去重的关键词。"""
        q = str(query or "")
        words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", q)
        # 中文长串再切 2 字滑窗，弥补没有分词
        extra = []
        for w in words:
            if len(w) > 3 and re.match(r"[\u4e00-\u9fff]", w):
                extra += [w[i:i + 2] for i in range(0, len(w) - 1)]
        out = []
        for w in list(words) + extra:
            if w and w not in STOP and w not in out:
                out.append(w)
        return out[:30]

    def retrieve(self, query, extra_keywords=()):
        """返回 (规则区, 检索章节)；法典不可用时都返回空串"""
        self._load()
        if not self._sections:
            return "", ""
        words = self._words(query) + [str(x) for x in (extra_keywords or []) if str(x).strip()]
        scored = []
        if words:
            for idx, sec in enumerate(self._sections):
                title = sec["title"]
                body = "\n".join(sec["text"])[:2500]
                score = 0
                for w in words:
                    if w in title:
                        score += 8
                    elif w in body:
                        score += 2
                if score > 0:
                    scored.append((score, idx, sec))
            scored.sort(key=lambda x: (-x[0], x[1]))

        picked, seen, total = [], set(), 0

        def take(idx, sec, limit):
            """按关键词取若干章节正文（受预算限制）。"""
            nonlocal total
            txt = "### [%s]\n%s" % (sec["title"], "\n".join(sec["text"])[:limit])
            if total + len(txt) > self.budget:
                return
            picked.append(txt)
            seen.add(idx)
            total += len(txt)

        for _score, idx, sec in scored[:self.top]:
            take(idx, sec, self.per_section)
        for idx, sec in enumerate(self._sections):
            if idx in seen:
                continue
            title = sec["title"]
            if title.startswith(ALWAYS_PREFIX) or any(w in title for w in ALWAYS_WORDS):
                take(idx, sec, self.per_section)
        return self._head, "\n\n".join(picked)

    def head(self):
        """取规则区开头部分。"""
        self._load()
        return self._head

    # ---------- 供 LLM 工具使用 ----------
    def index_text(self, keyword=""):
        """章节目录（可按标题关键词过滤）。"""
        self._load()
        lines = [s["title"] for s in self._sections]
        kw = str(keyword or "").strip()
        if kw:
            hit = [t for t in lines if kw in t]
            if hit:
                lines = hit
        return "\n".join(lines)[:6000] or "（法典为空）"

    def search(self, query, top=3):
        """按查询词取章节正文（省 token：默认 3 章 × 800 字，总长 ≤2400）。"""
        self._load()
        _, sections = self.retrieve(query)
        if not sections:
            return "（没有匹配的章节，换关键词再试）"
        blocks = [b for b in sections.split("\n\n### ") if b.strip()]
        picked, total = [], 0
        for i, block in enumerate(blocks[:3]):
            body = block if block.startswith("### ") else "### " + block
            body = body[:800]
            if total and total + len(body) > 2400:
                break
            picked.append(body)
            total += len(body)
        return "\n\n".join(picked)[:2400]

    def read_section(self, title):
        """按标题精读一章。"""
        self._load()
        key = str(title or "").strip()
        for sec in self._sections:
            if sec["title"] == key or (key and key in sec["title"]):
                return ("### [%s]\n%s" % (sec["title"], "\n".join(sec["text"])))[:6000]
        return "（没有这一章；先用 law_index 看目录）"
