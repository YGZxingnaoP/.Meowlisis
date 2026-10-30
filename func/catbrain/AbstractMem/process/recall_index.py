# -*- coding: utf-8 -*-
import datetime
import math
import os
import re
import threading

from collections import defaultdict

from func.catbrain.AbstractMem.process.evidence import MeowEvidence

STOPWORDS = {
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "的", "了", "是", "说",
    "就", "都", "和", "跟", "有", "在", "也", "还", "又", "很", "太", "把", "被",
    "这个", "那个", "什么", "怎么", "一起", "然后", "因为", "所以", "但是", "如果",
    "主人", "喵呜", "喵利呜西斯", "今天", "现在", "一下", "觉得", "知道", "记得",
    "之前", "之后", "以后", "以前", "时候", "事情", "好像", "还有", "一些", "一直",
    "已经", "出来", "起来", "开始", "继续", "真的", "确实", "肯定", "到底", "反正",
    "上次", "上回", "那次",
}

NOISE_PATTERNS = (
    re.compile(r"^\d+$"),
    re.compile(r"^[a-zA-Z]{1,3}$"),
)

RETRO_PATTERN = re.compile(
    r"(昨天|前天|上周|上个星期|上个月|上上个月|去年|前年|上次|以前|之前|那时候|当年|\d{4}年)"
)

FIELD_WEIGHTS = {"event": 1.0, "tags": 0.5, "joint": 0.3}
BM25_K1 = 0.9
BM25_B = 0.5
GATE_RATIO = 0.1
TAG_MIN_IDF = 2.0
MAX_DF_RATIO = 0.35
RRF_K = 60.0
CHANNEL_TOP = 200
W_BM25 = 1.0
W_TAG = 1.0
W_ENTITY = 1.0
W_MONTH = 1.0
W_TOPIC = 0.5
ANCHOR_LIMIT = 5


class MeowRecallIndex:

    def __init__(self, docs, segment, now=None):
        self.segment = segment
        self.docs = {}
        self.postings = defaultdict(dict)
        self.df = defaultdict(int)
        self.doc_len = {}
        self.avg_len = 1.0
        self.tag_postings = defaultdict(set)
        self.entity_postings = defaultdict(set)
        self.month_postings = defaultdict(list)
        self.topic_postings = defaultdict(set)
        self.nick_tokens = set()
        self.blocked = set()
        self._evidence = MeowEvidence()
        self._strength = {}
        self._recency = {}
        self._accuracy = {}
        self._build(docs, now or datetime.datetime.now())

    def _tokens(self, text):
        return [w for w in self.segment.segment(str(text or "")) if len(w.strip()) > 1]

    def _build(self, docs, now):
        for item in docs:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("id") or "")
            if not doc_id or doc_id in self.docs:
                continue
            event = str(item.get("event") or "")
            raw_tags = item.get("tags")
            raw_topics = item.get("topics")
            raw_joint = item.get("joint")
            tags = [str(t).strip() for t in (raw_tags if isinstance(raw_tags, list) else []) if str(t).strip()]
            topics = [str(t).strip() for t in (raw_topics if isinstance(raw_topics, list) else []) if str(t).strip()]
            names, uids = [], []
            for entry in (raw_joint if isinstance(raw_joint, list) else []):
                if isinstance(entry, dict):
                    name = str(entry.get("nickname") or "").strip()
                    uid = str(entry.get("meowid") or entry.get("id") or "").strip()
                else:
                    name, uid = str(entry or "").strip(), ""
                if name:
                    names.append(name)
                if uid:
                    uids.append(uid)

            self.docs[doc_id] = item
            length = 0.0
            for field, tokens in (("event", self._tokens(event)),
                                  ("tags", self._tokens(" ".join(tags))),
                                  ("joint", self._tokens(" ".join(names)))):
                weight = FIELD_WEIGHTS[field]
                length += len(tokens) * weight
                counts = defaultdict(int)
                for token in tokens:
                    counts[token] += 1
                for token, count in counts.items():
                    self.postings[token].setdefault(doc_id, {})[field] = count
                    self.df[token] += 1
            self.doc_len[doc_id] = length or 1.0
            for tag in tags:
                self.tag_postings[tag].add(doc_id)
            for key in names + uids:
                self.entity_postings[key].add(doc_id)
            for topic in topics:
                self.topic_postings[topic].add(doc_id)
            month = str(item.get("time") or "")[:7]
            if len(month) == 7:
                self.month_postings[month].append(doc_id)
            for token in self._tokens(" ".join(names)):
                self.nick_tokens.add(token)

            evidence = item.get("evidence")
            if isinstance(evidence, dict) and self._evidence.score(evidence, now) <= self._evidence.config.evidence_archive_threshold:
                self.blocked.add(doc_id)
            self._strength[doc_id] = self._strength_of(evidence, now)
            self._recency[doc_id] = self._recency_of(item.get("time"), now)
            try:
                accuracy = float(item.get("accuracy", 5) or 5)
            except (TypeError, ValueError):
                accuracy = 5.0
            self._accuracy[doc_id] = max(0.0, min(5.0, accuracy)) / 5.0

        lengths = list(self.doc_len.values())
        self.avg_len = (sum(lengths) / len(lengths)) if lengths else 1.0

    def _strength_of(self, evidence, now):
        """归一化证据分"""
        if not isinstance(evidence, dict):
            return 0.0
        cap = float(self._evidence.config.rank_evidence_saturation or 0)
        if cap <= 0:
            return 0.0
        score = max(0.0, self._evidence.score(evidence, now))
        return min(score / cap, 1.0)

    def _recency_of(self, value, now):
        """按半衰期计算新近度"""
        ts = str(value or "")
        parsed = None
        for fmt, size in (("%Y-%m-%d-%H-%M", 16), ("%Y-%m-%d", 10)):
            try:
                parsed = datetime.datetime.strptime(ts[:size], fmt)
                break
            except (TypeError, ValueError):
                continue
        if parsed is None:
            return 0.0
        half = float(self._evidence.config.rank_recency_half_life_days or 0)
        if half <= 0:
            return 0.0
        age = max(0.0, (now - parsed).total_seconds() / 86400)
        return 0.5 ** (age / half)

    def _final(self, doc_id, fused):
        """综合相关度与证据/新近/准确度"""
        cfg = self._evidence.config
        if not cfg.rank_use_evidence:
            return fused.get(doc_id, 0.0)
        def weight(name):
            return max(0.0, min(1.0, float(getattr(cfg, name, 0.0) or 0.0)))
        mult = (1 + weight("rank_w_evidence") * (self._strength.get(doc_id, 0.0) - 0.5))
        mult *= (1 + weight("rank_w_recency") * (self._recency.get(doc_id, 0.0) - 0.5))
        mult *= (1 + weight("rank_w_accuracy") * (self._accuracy.get(doc_id, 0.0) - 0.5))
        return fused.get(doc_id, 0.0) * mult

    def _idf(self, token):
        total = len(self.docs)
        if total <= 0:
            return 0.0
        df = self.df.get(token, 0)
        if df <= 0:
            return 0.0
        return math.log(1 + (total - df + 0.5) / (df + 0.5))

    def query_terms(self, query):
        terms = []
        for word in self._tokens(query):
            if word in STOPWORDS:
                continue
            if any(pattern.match(word) for pattern in NOISE_PATTERNS):
                continue
            if word in self.nick_tokens:
                continue
            if word in self.df:
                if word not in terms:
                    terms.append(word)
                continue
            if len(word) >= 3 and all('\u4e00' <= c <= '\u9fff' for c in word):
                for i in range(len(word) - 1):
                    piece = word[i:i + 2]
                    if piece in STOPWORDS or piece not in self.df or piece in terms:
                        continue
                    terms.append(piece)
        return terms

    def _char_fallback(self, query):
        """词组全未命中时的单字兜底：只用低频字，按命中字数和时间排序"""
        if re.search(r"[A-Za-z0-9]", str(query or "")):
            return []
        chars = list(dict.fromkeys(c for c in str(query or "") if '\u4e00' <= c <= '\u9fff'))
        if not chars:
            return []
        texts = {}
        for doc_id, item in self.docs.items():
            if not isinstance(item, dict):
                continue
            tags = item.get("tags")
            tag_text = " ".join(str(t) for t in tags) if isinstance(tags, list) else ""
            texts[doc_id] = str(item.get("event") or "") + " " + tag_text
        total = len(texts) or 1
        limit = max(3, int(total * 0.05))
        low_freq = [c for c in chars
                    if 0 < sum(1 for text in texts.values() if c in text) <= limit]
        if not low_freq:
            return []
        scored = []
        for doc_id, text in texts.items():
            if doc_id in self.blocked:
                continue
            hit = sum(1 for c in low_freq if c in text)
            if hit:
                scored.append((hit, self._time_of(doc_id), doc_id))
        scored.sort(reverse=True)
        return [doc_id for _, _, doc_id in scored[:ANCHOR_LIMIT * 2]]

    def bm25(self, terms):
        total = len(self.docs)
        if total <= 0:
            return {}
        scores = defaultdict(float)
        for term in terms:
            df = self.df.get(term, 0)
            if df <= 0 or df / total > MAX_DF_RATIO:
                continue
            idf = self._idf(term)
            if idf <= 0:
                continue
            for doc_id, fields in self.postings.get(term, {}).items():
                if doc_id in self.blocked:
                    continue
                tf = sum(count * FIELD_WEIGHTS.get(field, 1.0) for field, count in fields.items())
                if tf <= 0:
                    continue
                length = self.doc_len.get(doc_id, self.avg_len) or self.avg_len
                denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * length / self.avg_len)
                if denom <= 0:
                    continue
                scores[doc_id] += idf * tf * (BM25_K1 + 1) / denom
        return dict(scores)

    def tag_scores(self, terms):
        total = len(self.docs)
        if total <= 0:
            return {}
        scores = {}
        for tag, doc_ids in self.tag_postings.items():
            hit = 0.0
            for term in terms:
                if len(term) < 2:
                    continue
                if tag == term:
                    hit = 1.0
                    break
                if term in tag or tag in term:
                    hit = 0.6
            if hit <= 0:
                continue
            df = len(doc_ids)
            value = math.log(1 + (total - df + 0.5) / (df + 0.5)) * hit
            for doc_id in doc_ids:
                if doc_id in self.blocked:
                    continue
                if value > scores.get(doc_id, 0.0):
                    scores[doc_id] = value
        return scores

    def entity_docs(self, query):
        text = str(query or "")
        docs = set()
        for key in self.entity_postings:
            if len(key) > 1 and key in text:
                docs |= self.entity_postings[key]
        return docs - self.blocked

    def retro_months(self, query):
        match = RETRO_PATTERN.search(str(query or ""))
        if not match:
            return []
        months = sorted(self.month_postings)
        if not months:
            return []
        latest = months[-1]
        year, month = int(latest[:4]), int(latest[5:7])

        def shift(back):
            total = (year * 12 + month - 1) - back
            return "%04d-%02d" % (total // 12, total % 12 + 1)

        word = match.group(1)
        if word in ("昨天", "前天", "上次", "上周", "上个星期", "上个月"):
            return [latest, shift(1)]
        if word == "上上个月":
            return [shift(1), shift(2)]
        if word == "去年":
            return ["%04d-%02d" % (year - 1, month)]
        if word == "前年":
            return ["%04d-%02d" % (year - 2, month)]
        if word in ("以前", "之前", "那时候", "当年"):
            return months
        prefix = word[:4]
        if prefix.isdigit():
            return [item for item in months if item.startswith(prefix)]
        return []

    def _ordered(self, doc_ids):
        return sorted(doc_ids, key=lambda d: (str(self.docs[d].get("time") or ""), d), reverse=True)

    def _time_of(self, doc_id):
        item = self.docs.get(doc_id)
        return str(item.get("time") or "") if isinstance(item, dict) else ""

    def _rank(self, scores):
        ranked = sorted(scores.items(),
                        key=lambda kv: (kv[1], self._time_of(kv[0]), kv[0]),
                        reverse=True)
        return [doc_id for doc_id, _ in ranked[:CHANNEL_TOP]]

    def recall(self, query, months=None, gate_ratio=None, topic="", blocked=()):
        cfg = self._evidence.config
        ratio = GATE_RATIO if gate_ratio is None else float(gate_ratio)
        rrf_k = float(cfg.rank_rrf_k or RRF_K)
        if rrf_k <= 0:
            rrf_k = RRF_K
        tag_weight = float(cfg.rank_w_tag or W_TAG)
        blocked = set(blocked) | self.blocked
        terms = self.query_terms(query)
        month_docs = set()
        for month in (months or []):
            month_docs |= set(self.month_postings.get(str(month).strip(), ()))
        month_docs -= blocked
        topic_docs = set(self.topic_postings.get(topic, ())) - blocked if topic else set()

        if not terms:
            fallback = self._char_fallback(query)
            if fallback:
                return fallback
            if not topic_docs:
                return []
            return self._ordered(topic_docs)[:ANCHOR_LIMIT * 2]

        bm25 = {k: v for k, v in self.bm25(terms).items() if k not in blocked}
        tag = {k: v for k, v in self.tag_scores(terms).items() if k not in blocked}
        entity = self.entity_docs(query) - blocked

        channels = []
        if bm25:
            channels.append((self._rank(bm25), W_BM25))
        if tag:
            channels.append((self._rank(tag), tag_weight))
        if entity:
            channels.append((self._ordered(entity), W_ENTITY))
        if month_docs:
            channels.append((self._ordered(month_docs), W_MONTH))
        if topic_docs:
            channels.append((self._ordered(topic_docs), W_TOPIC))
        if not channels:
            return []

        fused = defaultdict(float)
        for ranked, weight in channels:
            for position, doc_id in enumerate(ranked):
                fused[doc_id] += weight / (position + rrf_k)

        gate = max(bm25.values()) * ratio if bm25 else None
        core, supp = [], []
        for doc_id in sorted(fused,
                             key=lambda d: (fused[d], bm25.get(d, 0.0), tag.get(d, 0.0),
                                            self._time_of(d), d),
                             reverse=True):
            if doc_id in entity or doc_id in month_docs:
                core.append(doc_id)
                continue
            if gate is not None and bm25.get(doc_id, 0.0) >= gate:
                supp.append(doc_id)
                continue
            if tag.get(doc_id, 0.0) >= TAG_MIN_IDF:
                supp.append(doc_id)

        picked = core[:ANCHOR_LIMIT] + supp
        if not picked and bm25:
            picked = [max(bm25, key=lambda d: (bm25[d], d))]
        if not picked and topic_docs:
            picked = self._ordered(topic_docs)[:ANCHOR_LIMIT]
        if cfg.rank_use_evidence and picked:
            picked = sorted(picked, key=lambda d: (self._final(d, fused), bm25.get(d, 0.0),
                                                   tag.get(d, 0.0), self._time_of(d), d), reverse=True)
        return picked


_CACHE = {"signature": None, "index": None}
_LOCK = threading.Lock()


def _signature(meow_dir):
    if not os.path.isdir(meow_dir):
        return ()
    parts = []
    try:
        names = sorted(os.listdir(meow_dir))
    except OSError:
        return ()
    for name in names:
        if not (name.startswith("meow-") and name.endswith(".json")):
            continue
        try:
            stat = os.stat(os.path.join(meow_dir, name))
        except OSError:
            continue
        parts.append((name, stat.st_mtime_ns, stat.st_size))
    return tuple(parts)


def get_index(meow_dir, docs, segment):
    signature = _signature(meow_dir)
    cached = _CACHE.get("index")
    if cached is not None and _CACHE.get("signature") == signature:
        return cached
    with _LOCK:
        if _CACHE.get("index") is not None and _CACHE.get("signature") == signature:
            return _CACHE["index"]
        index = MeowRecallIndex(docs, segment)
        _CACHE["signature"] = signature
        _CACHE["index"] = index
        return index


def warm_index(meow_dir, docs, segment):
    signature = _signature(meow_dir)
    index = MeowRecallIndex(docs, segment)
    with _LOCK:
        _CACHE["signature"] = signature
        _CACHE["index"] = index
    return index
