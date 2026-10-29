# -*- coding: utf-8 -*-
"""记忆召回实验室 · 召回算法变体

每个变体签名统一为：recall(ctx, query, cfg) -> Result
Result.ids 为「按顺序、已过闸门、已按预算截断」的条目 id 列表。

变体分三类：
  baseline*  复刻主程序现状（与原函数逐行对齐，含已知缺陷）
  minimal*   只改打分公式的「最小修复」
  hybrid*    索引化 + 多路召回 + 对称 RRF + 自适应闸门 + 分级预算
  baishou*   复刻 BaiShou-Next 的两条取法，用于量化对照
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from lab_core import (
    STOPWORDS,
    BigramIndex,
    Doc,
    EntityIndex,
    InvertedIndex,
    MonthIndex,
    TagIndex,
    Tokenizer,
    bigram_similarity,
    extract_time_window,
)


# ─────────────────────────── 公共上下文 ───────────────────────────
@dataclass
class Ctx:
    docs: Sequence[Doc]
    tok: Tokenizer
    index: InvertedIndex
    entity: EntityIndex
    month: MonthIndex
    bigram: "BigramIndex | None" = None
    tagindex: "TagIndex | None" = None
    text_by_id: Dict[str, str] = field(default_factory=dict)
    current_topic: str = "日常"          # 线上真实值（.temp/current_topic.json）


@dataclass
class Result:
    ids: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    gated: int = 0                        # 通过闸门的候选数（预算截断前）
    channel: Dict[str, int] = field(default_factory=dict)


@dataclass
class Cfg:
    """所有变体共用的可调项；默认值即「推荐配置」"""
    # BM25
    k1: float = 1.2
    b: float = 0.75
    field_event: float = 1.0
    field_tags: float = 0.5
    field_joint: float = 0.3
    # 查询词清洗 / 选词
    drop_stopwords: bool = True
    drop_noise: bool = True
    drop_nickname: bool = True
    max_df_ratio: float = 0.0             # >0 时丢弃「太常见」的词
    max_terms: int = 0                    # >0 时只保留 IDF 最高的前 N 个词
    # 闸门
    gate_mode: str = "p75"                # none | abs | p75 | p50 | ratio
    gate_value: float = 0.0               # abs 用；ratio 用（0~1）
    entity_gate: bool = True
    time_gate: bool = True
    # 预算
    core_n: int = 3                       # 实体/时间精确命中，最多几条
    supp_n: int = 5                       # BM25 补充，最多几条
    min_keep: int = 1                     # 闸门全灭时的保底条数（0=允许全空）
    # 融合
    rrf_k: float = 60.0
    w_bm25: float = 1.0
    w_entity: float = 1.0
    w_time: float = 1.0
    w_bigram: float = 1.0
    w_tag: float = 1.0
    channel_top: int = 40                 # 每路只取前 N 参与融合
    # 通道开关（放进 Cfg 才能被网格搜索完整序列化）
    use_entity: bool = True
    use_time: bool = True
    # 字二元通道
    use_bigram: bool = True
    bigram_gate: float = 0.20             # IDF 加权覆盖率 ≥ 此值视为通过（0=用 P75）
    bigram_min_hits: int = 2              # 至少命中几个字二元组（防「晚安」这类单词命中）
    bigram_candidates: int = 40
    # tag 通道
    use_tag: bool = True
    tag_can_gate: bool = True             # False = tag 只参与排序，不单独放行
    tag_gate: float = 2.5                 # tag IDF 门槛：压掉「日常/闲聊」这类话题同名 tag


# ─────────────────── 一、现状基线（逐行复刻） ───────────────────
REL_WEIGHTS = {"text": 0.5, "tags": 0.2, "topic": 0.2, "joint": 0.1}
RANK_WEIGHTS = {"strength": 0.20, "accuracy": 0.10, "relevance": 0.45,
                "recency": 0.15, "importance": 0.10}
OVERLAP_SATURATION = 1.0
RELEVANCE_THRESHOLD = 0.15


def _baseline_text_sim(item: Doc, msg_words: Set[str]) -> float:
    if not msg_words:
        return 0.0
    words = msg_words - STOPWORDS
    if not words:
        return 0.0
    hits = sum(1 for w in words if w in item.event)      # 单向子串包含
    return min(1.0, hits / OVERLAP_SATURATION)           # 一个词即满分


def _baseline_tags_sim(item: Doc, msg_words: Set[str], tok: Tokenizer) -> float:
    if not item.tags or not msg_words:
        return 0.0
    best = 0.0
    for tag in item.tags[:3]:
        tw = set(tok.cut(tag))
        if not tw:
            continue
        best = max(best, len(tw & msg_words) / len(tw))
    return best


def _baseline_joint_sim(item: Doc, uid: str) -> float:
    """复刻 F7 缺陷：只认 meowid（历史条目只有 id 键 → 恒不命中）"""
    if not uid:
        return 0.0
    for entry_id in item.joint_ids:
        if entry_id and entry_id == uid:
            return 1.0
    return 0.0


def _days(now_ord: float, time_str: str) -> float:
    import datetime
    try:
        dt = datetime.datetime.strptime(time_str, "%Y-%m-%d-%H-%M")
    except Exception:
        return 0.0
    return max(0.0, now_ord - dt.toordinal())


def baseline_recall(ctx: Ctx, query: str, cfg: Cfg, limit: int = 30,
                    uid: str = "000001", fix_joint: bool = False) -> Result:
    import datetime
    now_ord = datetime.datetime(2026, 10, 28).toordinal()
    msg_words = set(ctx.tok.cut(query)) if query else set()

    scored = []
    for doc in ctx.docs:
        rein = doc.reinforcement
        if rein < 0:
            continue
        strength = min(rein, 5.0) / 5.0
        accuracy = doc.accuracy / 5.0
        rel = (REL_WEIGHTS["text"] * _baseline_text_sim(doc, msg_words)
               + REL_WEIGHTS["tags"] * _baseline_tags_sim(doc, msg_words, ctx.tok)
               + REL_WEIGHTS["topic"] * (1.0 if ctx.current_topic in doc.topics else 0.0))
        if fix_joint:
            joint_hit = bool(doc.joint_ids and uid in doc.joint_ids) or bool(
                doc.joint_names and uid in doc.joint_names)
            rel += REL_WEIGHTS["joint"] * (1.0 if joint_hit else 0.0)
        else:
            rel += REL_WEIGHTS["joint"] * _baseline_joint_sim(doc, uid)
        age = _days(now_ord, doc.time)
        recency = 0.5 ** (age / 14.0) if age > 0 else 1.0
        imp = doc.importance / 10.0
        total = (RANK_WEIGHTS["strength"] * strength + RANK_WEIGHTS["accuracy"] * accuracy
                 + RANK_WEIGHTS["relevance"] * rel + RANK_WEIGHTS["recency"] * recency
                 + RANK_WEIGHTS["importance"] * imp)
        scored.append((total, rel, doc))
    scored.sort(key=lambda x: -x[0])

    out, seen = [], set()
    gated = 0
    for total, rel, doc in scored:
        if rel >= RELEVANCE_THRESHOLD:
            gated += 1
    for total, rel, doc in scored:
        if len(out) >= limit:
            break
        if rel < RELEVANCE_THRESHOLD:
            continue
        key = doc.event.replace(" ", "")
        if key in seen:
            continue
        seen.add(key)
        out.append(doc.doc_id)
    return Result(ids=out, scores={d.doc_id: t for t, r, d in scored}, gated=gated)


# ─────────────────── 二、最小修复（只改公式） ───────────────────
def minimal_recall(ctx: Ctx, query: str, cfg: Cfg, limit: int = 8,
                   threshold: float = 0.35, w_prior: float = 0.20,
                   use_idf: bool = True) -> Result:
    """把「一个词=满分」改成「命中词数 / 查询词数」，并按 IDF 加权。"""
    terms = ctx.tok.query_terms(query, cfg.drop_stopwords, cfg.drop_noise, cfg.drop_nickname)
    if not terms:
        return Result(ids=[], scores={}, gated=0)

    total_idf = sum(ctx.index.idf(t) for t in terms) or 1.0
    now_ord = __import__("datetime").datetime(2026, 10, 28).toordinal()

    scored = []
    for doc in ctx.docs:
        if doc.reinforcement < 0:
            continue
        hit_terms = [t for t in terms if t in doc.event]
        if use_idf:
            text = sum(ctx.index.idf(t) for t in hit_terms) / total_idf
        else:
            text = len(hit_terms) / len(terms)
        tag_hit = 0.0
        for tag in doc.tags[:3]:
            tw = set(ctx.tok.cut(tag))
            if tw:
                tag_hit = max(tag_hit, len(tw & set(terms)) / len(tw))
        rel = 0.7 * text + 0.3 * tag_hit
        age = _days(now_ord, doc.time)
        recency = 0.5 ** (age / 14.0) if age > 0 else 1.0
        prior = (0.5 * (doc.importance / 10.0) + 0.5 * recency) * w_prior
        scored.append((rel * (1 - w_prior) + prior, rel, doc))

    scored.sort(key=lambda x: -x[0])
    gated = sum(1 for _, rel, _ in scored if rel >= threshold)
    out = [d.doc_id for _, rel, d in scored if rel >= threshold][:limit]
    return Result(ids=out, scores={d.doc_id: s for s, r, d in scored}, gated=gated)


# ─────────────────── 三、索引化混合召回 ───────────────────
def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    k = max(0, min(len(vs) - 1, int(round((len(vs) - 1) * p))))
    return vs[k]


def _adaptive_threshold(scores: Dict[str, float], cfg: Cfg,
                        mode: str | None = None, value: float | None = None) -> float:
    """逐路闸门。默认按「本次候选的 P75」定线 —— 阈值随语料规模自动缩放。"""
    mode = mode or cfg.gate_mode
    value = cfg.gate_value if value is None else value
    vals = list(scores.values())
    if not vals or mode == "none":
        return float("-inf")
    if mode == "any":
        return min(vals)
    if mode == "abs":
        return value
    if mode == "ratio":
        return max(vals) * value
    if mode == "p50":
        return _percentile(vals, 0.50)
    return _percentile(vals, 0.75)


def hybrid_recall(ctx: Ctx, query: str, cfg: Cfg,
                  use_entity: bool | None = None,
                  use_time: bool | None = None,
                  use_rrf: bool = True,
                  use_bigram: bool | None = None) -> Result:
    """五路召回：词 BM25 · 字二元(IDF) · tag · 实体 · 时间 → 对称 RRF → 逐路自适应闸门 → 分级预算

    为什么是五路而不是一路：
      词 BM25   分词边界一变就漏（「英语六级考试」切不出「六级」）
      字二元    不看词边界，救分词漏召；用 IDF 压掉到处都有的二元组
      tag       独立成路，避免被话题同名 tag 的高 df 拉平（否则 19 条「价值观」打平）
      实体      用户直接点名时零歧义直达
      时间      有明确时间线索时优先用，而不是靠衰减去猜
    每路各自算「本次候选的 P75」当闸门，阈值随语料规模自动缩放（治「记录越多越不准」）。
    """
    if use_bigram is None:
        use_bigram = cfg.use_bigram
    if use_entity is None:
        use_entity = cfg.use_entity
    if use_time is None:
        use_time = cfg.use_time
    terms = ctx.tok.query_terms(query, cfg.drop_stopwords, cfg.drop_noise, cfg.drop_nickname)

    # ── 路 1：词 BM25 ──
    kept = []
    for t in terms:
        df = ctx.index.df.get(t, 0)
        if cfg.max_df_ratio > 0 and ctx.index.n_docs and df / ctx.index.n_docs > cfg.max_df_ratio:
            continue
        if df > 0:
            kept.append(t)
    if cfg.max_terms > 0 and len(kept) > cfg.max_terms:
        kept = sorted(kept, key=lambda t: -ctx.index.idf(t))[: cfg.max_terms]
    bm25 = ctx.index.score(
        kept, k1=cfg.k1, b=cfg.b,
        field_weights={"event": cfg.field_event, "tags": cfg.field_tags,
                       "joint": cfg.field_joint},
    ) if kept else {}

    # ── 路 2：字二元（IDF 加权覆盖率 + 命中二元组数）──
    bigram: Dict[str, float] = {}
    bigram_stats: Dict[str, tuple] = {}
    if use_bigram and ctx.bigram is not None and query:
        bigram_stats = ctx.bigram.stats(query)
        bigram = {d: s[2] for d, s in bigram_stats.items()}

    # ── 路 3：tag ──
    tag: Dict[str, float] = {}
    if cfg.use_tag and ctx.tagindex is not None and terms:
        tag = ctx.tagindex.match(terms)

    # ── 路 4：实体 ──
    entity_hits: Set[str] = set()
    if use_entity:
        keys = [n for n in ctx.entity.by_key if len(n) > 1 and n in query]
        entity_hits = ctx.entity.lookup(keys)

    # ── 路 5：时间 ──
    time_hits: Set[str] = set()
    time_word = None
    if use_time:
        time_word, months = extract_time_window(query, ctx.docs)
        if months:
            time_hits = ctx.month.lookup(months)

    # ── 对称 RRF：每路只贡献「列表内名次」，量纲一致 ──
    channels: List[Tuple[str, Dict[str, float], float]] = []
    if bm25:
        channels.append(("bm25", bm25, cfg.w_bm25))
    if bigram:
        channels.append(("bigram", bigram, cfg.w_bigram))
    if tag:
        channels.append(("tag", tag, cfg.w_tag))
    if entity_hits:
        channels.append(("entity", {d: 1.0 for d in entity_hits}, cfg.w_entity))
    if time_hits:
        channels.append(("time", {d: 1.0 for d in time_hits}, cfg.w_time))

    gate_by_channel: Dict[str, float] = {}
    for name, scores, _w in channels:
        if name == "bm25":
            gate_by_channel[name] = _adaptive_threshold(scores, cfg, cfg.gate_mode,
                                                        cfg.gate_value)
        elif name == "bigram":
            gate_by_channel[name] = _adaptive_threshold(
                scores, cfg, "p75" if cfg.bigram_gate <= 0 else "abs", cfg.bigram_gate)
        elif name == "tag":
            gate_by_channel[name] = _adaptive_threshold(scores, cfg, "abs", cfg.tag_gate)
        else:                                    # entity / time：命中即通过
            gate_by_channel[name] = _adaptive_threshold(scores, cfg, "any")

    fused: Dict[str, float] = {}
    time_key = {d.doc_id: d.time for d in ctx.docs}

    def _ordered(scores):
        return sorted(scores.items(),
                      key=lambda kv: (kv[1], time_key.get(kv[0], ""), kv[0]),
                      reverse=True)

    if use_rrf:
        for name, scores, w in channels:
            ranked = _ordered(scores)[: cfg.channel_top]
            for i, (d, _s) in enumerate(ranked):
                fused[d] = fused.get(d, 0.0) + w / (i + cfg.rrf_k)
    else:
        fused = dict(bm25)
        for d in entity_hits | time_hits:
            fused[d] = fused.get(d, 0.0) + 1e6

    core: List[str] = []
    supp: List[str] = []
    for d, _s in _ordered(dict(fused)):
        is_core = bool(d in entity_hits or (d in time_hits))
        passed = is_core
        if not passed:
            # 词路：BM25 过自适应线
            if d in bm25 and bm25[d] >= gate_by_channel["bm25"]:
                passed = True
            # 字二元路：IDF 和过线，且至少 2 个二元组一致
            # （单个二元组一致就放行，等于把「晚安」这类寒暄也当检索线索）
            if not passed and d in bigram_stats:
                cov, cnt, idf = bigram_stats[d]
                if idf >= gate_by_channel["bigram"] and cnt >= cfg.bigram_min_hits:
                    passed = True
            if not passed and cfg.tag_can_gate and d in tag and tag[d] >= gate_by_channel["tag"]:
                passed = True
        if passed:
            (core if is_core else supp).append(d)

    ids = core[: cfg.core_n] + supp[: cfg.supp_n]
    if not ids and cfg.min_keep > 0 and fused:
        ids = [d for d, _ in _ordered(fused)[: cfg.min_keep]]
    return Result(
        ids=ids,
        scores=fused,
        gated=len(core) + len(supp),
        channel={name: len(scores) for name, scores, _ in channels},
    )


# ─────────────────── 四、BaiShou-Next 取法对照 ───────────────────
def baishou_shortcircuit(ctx: Ctx, query: str, cfg: Cfg, limit: int = 12) -> Result:
    """复刻 resolveAnchors：名字/实体有命中就短路，不再走关键词通道。"""
    keys = [n for n in ctx.entity.by_key if len(n) > 1 and n in query]
    if keys:
        ids = sorted(ctx.entity.lookup(keys))[:limit]
        return Result(ids=ids, scores={d: 1.0 for d in ids}, gated=len(ids),
                      channel={"shortcircuit": 1})
    return Result(ids=[], scores={}, gated=0, channel={"shortcircuit": 0})


def baishou_phrase_like(ctx: Ctx, query: str, cfg: Cfg, limit: int = 20) -> Result:
    """复刻 BaiShou 中文关键词通道：整句作为短语做子串匹配（无分词、无 IDF）。"""
    q = str(query or "").strip()
    if len(q) < 2:
        return Result(ids=[], scores={}, gated=0)
    hits = [d for d in ctx.docs if q in d.event]
    return Result(ids=[d.doc_id for d in hits][:limit],
                  scores={d.doc_id: 1.0 for d in hits}, gated=len(hits))


def bigram_recall(ctx: Ctx, query: str, cfg: Cfg, threshold: float = 0.30,
                  limit: int = 8) -> Result:
    """字二元覆盖度：不依赖分词，抗「词边界不同」的近似匹配。"""
    scored = []
    for d in ctx.docs:
        sim = bigram_similarity(query, d.event)
        if sim > 0:
            scored.append((sim, d))
    scored.sort(key=lambda x: -x[0])
    gated = sum(1 for s, _ in scored if s >= threshold)
    out = [d.doc_id for s, d in scored if s >= threshold][:limit]
    return Result(ids=out, scores={d.doc_id: s for s, d in scored}, gated=gated)


VARIANTS = {
    "baseline": lambda ctx, q, c: baseline_recall(ctx, q, c, limit=30),
    "baseline_fixjoint": lambda ctx, q, c: baseline_recall(ctx, q, c, limit=30, fix_joint=True),
    "minimal": lambda ctx, q, c: minimal_recall(ctx, q, c, limit=8),
    "bm25_only": lambda ctx, q, c: hybrid_recall(ctx, q, c, use_entity=False,
                                                 use_time=False, use_bigram=False),
    "bm25_entity": lambda ctx, q, c: hybrid_recall(ctx, q, c, use_time=False,
                                                   use_bigram=False),
    "hybrid3": lambda ctx, q, c: hybrid_recall(ctx, q, c),
    "hybrid4": lambda ctx, q, c: hybrid_recall(ctx, q, c, use_entity=True, use_time=True,
                                               use_bigram=True),
    "hybrid4_norrf": lambda ctx, q, c: hybrid_recall(ctx, q, c, use_rrf=False),
    "baishou_shortcircuit": baishou_shortcircuit,
    "baishou_phrase_like": baishou_phrase_like,
    "bigram": bigram_recall,
}


# ─────────────────── 五、推荐配置（实验定稿，供主程序参考） ───────────────────
RECOMMENDED = Cfg(
    k1=0.9,                 # BM25 词频饱和
    b=0.5,                  # BM25 长度归一
    field_event=1.0, field_tags=0.5, field_joint=0.3,
    drop_stopwords=True, drop_noise=True, drop_nickname=True,
    max_df_ratio=0.10,      # 丢弃出现在 >10% 语料里的词
    gate_mode="ratio", gate_value=0.5,   # 词路闸门 = 本批最高分 × 0.5（随语料自动缩放）
    core_n=3, supp_n=5, min_keep=1,
    use_bigram=False,       # 字二元消融为净负收益，默认关
    tag_gate=3.5,           # tag IDF 门槛
)


def recommended_recall(ctx: Ctx, query: str) -> Result:
    return hybrid_recall(ctx, query, RECOMMENDED)
