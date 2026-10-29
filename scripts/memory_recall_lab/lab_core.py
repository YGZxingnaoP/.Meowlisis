# -*- coding: utf-8 -*-
"""记忆召回实验室 · 核心层

只读真实语料（character/abstract_memory/meow-*.json），不导入主程序模块，
因此不会写 logs/、不碰 .temp/。所有算法都在本目录内独立复刻，便于对照。

本文件提供：
  - load_records()      读取并稳定排序全部记忆条目
  - Tokenizer           中文分词 + 停用词 + 噪声词（数字/昵称碎片）过滤
  - InvertedIndex       倒排索引（词→条目）、df、字段 tf、条目长度
  - EntityIndex         参与人/别名 → 条目
  - MonthIndex          月份 → 条目
  - bm25()              BM25 打分（k1/b 可调、字段权重可调）
  - char_bigram()       字二元相似度（无分词依赖的廉价模糊匹配）
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Set, Tuple

# ── 可复现性 ────────────────────────────────────────────────────────────
# 召回链路里有若干「集合转字典 / 同分排序」，集合的迭代顺序受 PYTHONHASHSEED 影响。
# 不固定哈希种子时，同一配置每次跑出来的 recall 会差 ±0.03 —— 足够把好方案排到坏方案后面。
# 这里在首次导入时把种子固定为 0 并重启进程，保证任何人都能复现同一组数字。
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    _target = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if _target and os.path.isfile(_target):
        try:
            os.execv(sys.executable, [sys.executable, _target] + sys.argv[1:])
        except Exception:
            pass

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MEMORY_DIR = os.path.join(WORKSPACE, "character", "abstract_memory")

# 与主程序 func/catbrain/AbstractMem/load_abmem.py:33-38 完全一致
STOPWORDS = {
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "的", "了", "是", "说",
    "就", "都", "和", "跟", "有", "在", "也", "还", "又", "很", "太", "把", "被",
    "这个", "那个", "什么", "怎么", "一起", "然后", "因为", "所以", "但是", "如果",
    "主人", "喵呜", "喵利呜西斯", "今天", "现在", "一下", "觉得", "知道", "记得",
    "之前", "之后", "以后", "以前", "时候", "事情", "好像", "还有", "一些", "一直",
    "已经", "出来", "起来", "开始", "继续", "真的", "确实", "肯定", "到底", "反正",
}

# 主程序 msg 前缀/时间串引入的噪声词（实测会命中大量无关条目）
NOISE_PATTERNS = [
    re.compile(r"^\d+$"),                 # 纯数字：2026 / 00 / 08 / 29
    re.compile(r"^[a-zA-Z]{1,3}$"),       # 极短英文：ai / qq（大小写另行处理）
]

TIME_RE = re.compile(
    r"(昨天|前天|上周|上个星期|上个月|上上个月|去年|前年|上次|"
    r"以前|之前|那时候|当年|"
    r"\d{4}年|\d{4}[-/]\d{1,2})"
)


@dataclass
class Doc:
    doc_id: str
    event: str
    tags: List[str]
    topics: List[str]
    joint_names: List[str]
    joint_ids: List[str]
    month: str
    importance: float
    accuracy: float
    reinforcement: float
    time: str


def _joint_of(item: dict) -> Tuple[List[str], List[str]]:
    """参与人条目：兼容 id / meowid 两种历史键（主程序只读 meowid，这是 F7 缺陷来源）"""
    names, ids = [], []
    for entry in (item.get("joint") or []):
        if isinstance(entry, dict):
            nick = str(entry.get("nickname") or "").strip()
            uid = str(entry.get("meowid") or entry.get("id") or "").strip()
            if nick:
                names.append(nick)
            if uid:
                ids.append(uid)
        else:
            text = str(entry or "").strip()
            if text:
                names.append(text)
    return names, ids


def load_records(memory_dir: str = MEMORY_DIR) -> List[Doc]:
    """读取全部 meow-*.json，按 time + id 稳定排序"""
    raw: List[dict] = []
    seen: Set[str] = set()
    for path in sorted(glob.glob(os.path.join(memory_dir, "meow-*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        for item in (data if isinstance(data, list) else []):
            if not isinstance(item, dict):
                continue
            did = str(item.get("id") or "")
            if did and did in seen:
                continue
            if did:
                seen.add(did)
            raw.append(item)

    docs: List[Doc] = []
    for item in raw:
        names, ids = _joint_of(item)
        ts = str(item.get("time") or "")
        ev = (item.get("evidence") or {}) if isinstance(item.get("evidence"), dict) else {}
        docs.append(Doc(
            doc_id=str(item.get("id") or ""),
            event=str(item.get("event") or ""),
            tags=[str(t).strip() for t in (item.get("tags") or []) if str(t).strip()],
            topics=[str(t).strip() for t in (item.get("topics") or []) if str(t).strip()],
            joint_names=names,
            joint_ids=ids,
            month=ts[:7] if len(ts) >= 7 else "",
            importance=float(item.get("importance") or 0),
            accuracy=float(item.get("accuracy") or 0),
            reinforcement=float(ev.get("reinforcement") or 0),
            time=ts,
        ))
    docs.sort(key=lambda d: (d.time, d.doc_id))
    return docs


class Tokenizer:
    """分词 + 可选过滤。filter 开关用于消融，看每个清洗步骤各值多少。"""

    def __init__(self, docs: Sequence[Doc], use_userdict: bool = True,
                 userdict_max_len: int = 99):
        import jieba  # 延迟导入
        self._jieba = jieba
        self.userdict_terms: List[str] = []
        # 把语料自带的 tag / 话题 / 昵称灌进 jieba 用户词典。
        # 目的：修正分词边界 —— jieba 默认会把「英语六级考试」切成「英语六级 / 考试」，
        # 于是用户打「六级」永远命中不了（实测 q01 的目标记录因此掉出 BM25 top20）。
        # 用词典修比分词后补救更干净：不会像字二元通道那样把负例也灌满。
        if use_userdict:
            vocab: List[str] = []
            for d in docs:
                vocab.extend(d.tags)
                vocab.extend(d.topics)
            for word in dict.fromkeys(w.strip() for w in vocab):
                if (word and 2 <= len(word) <= userdict_max_len
                        and word not in STOPWORDS):
                    try:
                        jieba.add_word(word, freq=2000)
                        self.userdict_terms.append(word)
                    except Exception:
                        pass
        # 昵称表：用于剔除昵称碎片（实测「醒脑」命中 25 条）
        self.nicknames: Set[str] = set()
        for d in docs:
            for n in d.joint_names:
                n = n.strip()
                if len(n) > 1:
                    self.nicknames.add(n)
        self._nick_tokens: Set[str] = set()
        for n in self.nicknames:
            for t in jieba.cut(n):
                if len(t.strip()) > 1:
                    self._nick_tokens.add(t)

    def cut(self, text: str) -> List[str]:
        return [w for w in self._jieba.cut(str(text or "")) if len(w.strip()) > 1]

    def query_terms(
        self,
        text: str,
        drop_stopwords: bool = True,
        drop_noise: bool = True,
        drop_nickname: bool = True,
    ) -> List[str]:
        out: List[str] = []
        for w in self.cut(text):
            w = w.strip()
            if not w:
                continue
            if drop_stopwords and w in STOPWORDS:
                continue
            if drop_noise and any(p.match(w) for p in NOISE_PATTERNS):
                continue
            if drop_nickname and w in self._nick_tokens:
                continue
            if w not in out:
                out.append(w)
        return out


@dataclass
class InvertedIndex:
    """词→条目倒排；tf 分字段统计；另存 df 与条目长度"""
    field_weights: Dict[str, float] = field(
        default_factory=lambda: {"event": 1.0, "tags": 0.5, "joint": 0.3}
    )
    postings: Dict[str, Dict[str, Dict[str, int]]] = field(
        default_factory=lambda: defaultdict(dict)
    )          # token -> doc_id -> {field: tf}
    df: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    doc_len: Dict[str, float] = field(default_factory=dict)
    avg_len: float = 1.0
    n_docs: int = 0

    @classmethod
    def build(cls, docs: Sequence[Doc], tok: Tokenizer,
              field_weights: Dict[str, float] | None = None) -> "InvertedIndex":
        idx = cls()
        if field_weights:
            idx.field_weights = dict(field_weights)
        for d in docs:
            per_field: Dict[str, List[str]] = {
                "event": tok.cut(d.event),
                "tags": tok.cut(" ".join(d.tags)),
                "joint": tok.cut(" ".join(d.joint_names)),
            }
            weighted_len = 0.0
            for fname, toks in per_field.items():
                tf: Dict[str, int] = defaultdict(int)
                for t in toks:
                    tf[t] += 1
                w = idx.field_weights.get(fname, 1.0)
                weighted_len += len(toks) * w
                for t, c in tf.items():
                    idx.postings[t].setdefault(d.doc_id, {})[fname] = c
                    idx.df[t] += 1
            idx.doc_len[d.doc_id] = weighted_len or 1.0
        idx.n_docs = len(docs)
        idx.avg_len = (sum(idx.doc_len.values()) / len(idx.doc_len)) if idx.doc_len else 1.0
        return idx

    def idf(self, token: str) -> float:
        """BM25 的 Robertson-Sparck-Jones IDF，恒为正"""
        n = self.df.get(token, 0)
        if n <= 0:
            return math.log(1 + (self.n_docs + 0.5) / 0.5)
        return math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5))

    def score(
        self,
        terms: Sequence[str],
        k1: float = 1.2,
        b: float = 0.75,
        field_weights: Dict[str, float] | None = None,
    ) -> Dict[str, float]:
        """BM25；terms 为查询词（可重复）。返回 doc_id → score（仅含命中者）"""
        fw = field_weights or self.field_weights
        out: Dict[str, float] = defaultdict(float)
        for term in terms:
            posting = self.postings.get(term)
            if not posting:
                continue
            idf = self.idf(term)
            for doc_id, fields in posting.items():
                tf = sum(c * fw.get(f, 1.0) for f, c in fields.items())
                if tf <= 0:
                    continue
                dl = self.doc_len.get(doc_id, self.avg_len) or self.avg_len
                denom = tf + k1 * (1 - b + b * dl / self.avg_len)
                out[doc_id] += idf * tf * (k1 + 1) / (denom or 1.0)
        return dict(out)


@dataclass
class EntityIndex:
    """参与人（昵称 / 编号）→ 条目 id"""
    by_key: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))

    @classmethod
    def build(cls, docs: Sequence[Doc]) -> "EntityIndex":
        idx = cls()
        for d in docs:
            for key in list(d.joint_names) + list(d.joint_ids):
                key = str(key or "").strip()
                if key:
                    idx.by_key[key].add(d.doc_id)
        return idx

    def lookup(self, keys: Iterable[str]) -> Set[str]:
        hit: Set[str] = set()
        for k in keys:
            hit |= self.by_key.get(str(k or "").strip(), set())
        return hit


@dataclass
class MonthIndex:
    by_month: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))

    @classmethod
    def build(cls, docs: Sequence[Doc]) -> "MonthIndex":
        idx = cls()
        for d in docs:
            if d.month:
                idx.by_month[d.month].add(d.doc_id)
        return idx

    def lookup(self, months: Iterable[str]) -> Set[str]:
        hit: Set[str] = set()
        for m in months:
            hit |= self.by_month.get(str(m or "").strip(), set())
        return hit


def char_bigrams(text: str) -> Set[str]:
    """字二元集合（去标点空白）；中文里比词切分更稳的廉价近似"""
    cleaned = re.sub(r"[\s。，！？、,.!?;；:：~～·…—\-—_\"'“”‘’（）()【】\[\]]+", "", str(text or ""))
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def bigram_similarity(query: str, doc_text: str) -> float:
    """查询字二元被条目覆盖的比例（0~1）。不做 IDF，纯覆盖度。"""
    q = char_bigrams(query)
    if not q:
        return 0.0
    d = char_bigrams(doc_text)
    if not d:
        return 0.0
    return len(q & d) / len(q)


@dataclass
class BigramIndex:
    """字二元倒排 + IDF。

    动机：jieba 会把「英语六级考试」切成「英语六级 / 考试」，而用户只打「六级」，
    词面永远对不上（实测 q01 的目标记录因此掉出 BM25 top20）。
    字二元不看词边界，「六级」这个二元组仍能命中，且用 IDF 压掉
    「今天 / 主人」这类到处都有的二元组。
    """
    postings: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(dict))
    df: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    n_docs: int = 0

    @classmethod
    def build(cls, docs: Sequence[Doc]) -> "BigramIndex":
        idx = cls()
        for d in docs:
            grams = char_bigrams(d.event)
            for g in grams:
                idx.postings[g][d.doc_id] = idx.postings[g].get(d.doc_id, 0) + 1
                idx.df[g] += 1
        idx.n_docs = len(docs)
        return idx

    def idf(self, gram: str) -> float:
        n = self.df.get(gram, 0)
        if n <= 0:
            return 0.0
        return math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5))

    def coverage(self, query: str) -> Dict[str, float]:
        """IDF 加权的字二元覆盖率：命中稀有二元组比命中常见二元组更值钱

        注意：这里是「原始命中 IDF 和」，不再除以查询自身的 IDF 总和。
        除以自身和会让「晚安」这种单个二元组的查询一命中就 1.0 ——
        与主程序 hits/1.0 的饱和病完全一样（实测负例噪声就是这么来的）。
        闸门另配「至少命中 2 个二元组」，由调用方判断。
        """
        return {d: v[2] for d, v in self.stats(query).items()}

    def stats(self, query: str) -> Dict[str, tuple]:
        """返回 doc → (覆盖率, 命中二元组数, 命中 IDF 和)"""
        grams = char_bigrams(query)
        if not grams:
            return {}
        total_idf = sum(self.idf(g) for g in grams) or 1.0
        matched_count: Dict[str, int] = defaultdict(int)
        matched_idf: Dict[str, float] = defaultdict(float)
        for g in grams:
            idf = self.idf(g)
            if idf <= 0:
                continue
            for doc_id in self.postings.get(g, {}):
                matched_count[doc_id] += 1
                matched_idf[doc_id] += idf
        n_q = len(grams)
        return {d: (cnt / n_q, cnt, idf) for d, cnt in matched_count.items()
                for idf in (matched_idf[d],)}


@dataclass
class TagIndex:
    """tag 倒排。单独成路，是因为 tag 与话题高度共线（前四高频 tag 有三个就是话题名），
    塞进 BM25 会把 idf 直接拉到接近 0，19 条「价值观」互相打平（实测 q11 的目标记录掉到 #16/#18）。
    单独成路后，命中稀有 tag（72% 的 tag 只出现一次）就是强信号。
    """
    postings: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    n_docs: int = 0

    @classmethod
    def build(cls, docs: Sequence[Doc]) -> "TagIndex":
        idx = cls()
        for d in docs:
            for tag in d.tags:
                tag = tag.strip()
                if tag:
                    idx.postings[tag].add(d.doc_id)
        idx.n_docs = len(docs)
        return idx

    def idf(self, tag: str) -> float:
        n = len(self.postings.get(tag, ()))
        if n <= 0:
            return 0.0
        return math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5))

    def match(self, terms: Sequence[str]) -> Dict[str, float]:
        """查询词命中 tag：完全相等 > tag 包含查询词。按 tag 的 IDF 累加。"""
        acc: Dict[str, float] = defaultdict(float)
        for tag, doc_ids in self.postings.items():
            for term in terms:
                if not term or len(term) < 2:
                    continue
                if tag == term:
                    gain = self.idf(tag) * 1.0
                elif term in tag or tag in term:
                    gain = self.idf(tag) * 0.6
                else:
                    continue
                for doc_id in doc_ids:
                    acc[doc_id] = max(acc[doc_id], gain)
                break
        return dict(acc)


def extract_time_window(query: str, docs: Sequence[Doc]):
    """只识别「回溯型」时间线索（去年/上个月/上次/昨天…），返回允许的月份集合。

    刻意不处理「今天 / 现在 / 明天」：
      它们是当下或未来，不构成「去翻旧记忆」的理由。
      实测把这些词也当线索时，负例「你今天心情怎么样」「今天天气不错」会命中当月全部条目，
      凭空给每个寒暄灌进 3~8 条记忆 —— 时间通道的噪声全部来自这里。
    """
    m = TIME_RE.search(str(query or ""))
    if not m:
        return None, None
    word = m.group(1)
    months = sorted({d.month for d in docs if d.month})
    if not months:
        return word, []
    latest = months[-1]
    yy, mm = int(latest[:4]), int(latest[5:7])

    def shift(back: int) -> str:
        total = (yy * 12 + (mm - 1)) - back
        return f"{total // 12:04d}-{total % 12 + 1:02d}"

    if word in ("昨天", "前天", "上次"):
        return word, [latest, shift(1)]
    if word in ("上周", "上个星期"):
        return word, [latest, shift(1)]
    if word in ("上个月",):
        return word, [latest, shift(1)]
    if word == "上上个月":
        return word, [shift(1), shift(2)]
    if word == "去年":
        return word, [f"{yy - 1:04d}-{mm:02d}"]
    if word == "前年":
        return word, [f"{yy - 2:04d}-{mm:02d}"]
    if word in ("以前", "之前", "那时候", "当年"):
        return word, months                       # 模糊回溯：全时段，靠其他通道排序
    year_match = re.match(r"(\d{4})", word)
    if year_match:
        year = year_match.group(1)
        return word, [m2 for m2 in months if m2.startswith(year)]
    return word, []


def prime_jieba() -> None:
    """预热 jieba，避免首次调用计入耗时统计"""
    import jieba
    jieba.initialize()
