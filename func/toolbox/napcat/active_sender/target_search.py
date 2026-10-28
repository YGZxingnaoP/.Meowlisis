# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/target_search.py
# 目标搜索：把「用户说的名字」和「好友 / 群 列表」做归一化 + 打分 + 排序，供
# QQ 链路内部（subtools.find_friend / find_group）在拉取列表后先筛选再匹配。
#
# 匹配级别（分数由高到低）：
#   exact    原样全等
#   norm     归一化全等（全角/大小写/空格/标点/emoji 差异）
#   prefix   归一化前缀
#   pinyin   拼音或首字母全等（qlrr / qilerongrong，仅纯字母查询）
#   contains 包含（长出来的部分太长会自动降分，避免「小王」命中「小王的朋友」）
#   similar  相似度（错字/缺字），永不自动发，只作为追问候选
#
# 纯函数、无 I/O。pypinyin / rapidfuzz 是软依赖：缺了就自动跳过对应能力。

import re
import unicodedata
from typing import Callable, Iterable, List, Tuple

try:      # 软依赖：拼音 / 首字母匹配
    from pypinyin import lazy_pinyin
except Exception:   # pragma: no cover
    lazy_pinyin = None

# 归一化时要抹掉的差异：空白、全角空格、常见标点与装饰符
_PUNCT = re.compile(r"[\s\u3000·・,，。.、\-_/\\|()（）\[\]【】<>《》+*~!！?？:：;；'\"“”‘’]")

LEVEL_SCORE = {
    "exact": 1.00,
    "norm": 0.97,
    "homophone": 0.95,   # 中文同音（其乐荣荣 ≈ 其乐容容），拼音全等
    "prefix": 0.93,
    "pinyin": 0.90,      # 字母查询命中全拼 / 首字母
    "pinyin_prefix": 0.87,
    "contains": 0.88,
    "similar": 0.00,     # 按相似度比例给分，上限 0.84
}

# 级别优先级：用来判断「第一名是不是真的比第二名强」，比纯分数更可靠
LEVEL_RANK = {
    "exact": 7, "norm": 6, "homophone": 5, "prefix": 4, "pinyin": 3,
    "pinyin_prefix": 2, "contains": 1, "similar": 0,
}

# 这些级别可以「自己定」直接发送；contains 另有额外条件，similar / 拼音前缀 交追问
AUTO_LEVELS = ("exact", "norm", "homophone", "prefix", "pinyin")
# 第一名领先第二名多少分才敢自己定（级别不同则无需比分数）
GAP = 0.08

_CACHE: dict = {}


def normalize(text) -> str:
    """归一化：全角转半角 + 去空白/标点/装饰符 + 小写"""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = _PUNCT.sub("", s)
    return s.strip().lower()


def _pinyin_forms(text: str) -> Tuple[str, str]:
    """返回 (全拼, 首字母)；没有 pypinyin 时返回空串"""
    if lazy_pinyin is None:
        return "", ""
    key = "py:" + text
    if key in _CACHE:
        return _CACHE[key]
    try:
        parts = lazy_pinyin(text)
    except Exception:
        parts = []
    full = "".join(parts).lower()
    initials = "".join(p[0] for p in parts if p).lower()
    _CACHE[key] = (full, initials)
    return full, initials


def _similarity(a: str, b: str) -> float:
    """字符级相似度（纯 stdlib，保证中文按字符比较；rapidfuzz 对中文会给错分数）"""
    if not a or not b:
        return 0.0
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def _coverage(query: str, name: str) -> float:
    """查询字符按顺序命中候选名的比例（「上理电竞」→ 上理GM电竞… 命中 4/4）

    中文里这比编辑距离更贴近人的直觉：字都在、顺序对，就算很像。
    """
    if not query or not name:
        return 0.0
    idx, hit = 0, 0
    for ch in query:
        pos = name.find(ch, idx)
        if pos >= 0:
            hit += 1
            idx = pos + 1
    return hit / len(query)


def score(query, name) -> Tuple[float, str]:
    """给「查询 → 候选名」打分，返回 (分数, 级别)"""
    q = str(query or "").strip()
    n = str(name or "").strip()
    if not q or not n:
        return 0.0, ""
    if q == n:
        return LEVEL_SCORE["exact"], "exact"
    nq, nn = normalize(q), normalize(n)
    if not nq or not nn:
        return 0.0, ""
    if nq == nn:
        return LEVEL_SCORE["norm"], "norm"
    if nn.startswith(nq):
        return LEVEL_SCORE["prefix"], "prefix"
    if nq in nn or nn in nq:
        # 包含命中：长出来的部分越多越不可信（「小王」vs「小王的朋友」）
        extra = abs(len(nn) - len(nq))
        return max(0.60, LEVEL_SCORE["contains"] - 0.02 * max(0, extra - 2)), "contains"
    # 拼音：字母查询（qlrr / qilerongrong）命中全拼或首字母
    if re.fullmatch(r"[a-z]+", nq):
        full, initials = _pinyin_forms(nn)
        if full and (nq == full or nq == initials):
            return LEVEL_SCORE["pinyin"], "pinyin"
        if full and (full.startswith(nq) or nq.startswith(full)):
            return LEVEL_SCORE["pinyin_prefix"], "pinyin_prefix"
    else:
        # 中文同音字（其乐荣荣 ≈ 其乐容容）：拼音全等才算，首字母只作弱提示
        q_full, q_ini = _pinyin_forms(nq)
        if q_full:
            n_full, n_ini = _pinyin_forms(nn)
            if n_full and q_full == n_full:
                return LEVEL_SCORE["homophone"], "homophone"
            if len(nq) >= 4 and q_ini and n_ini and q_ini == n_ini:
                return LEVEL_SCORE["pinyin_prefix"], "pinyin_prefix"
    sim = _similarity(nq, nn)
    # 中文长名：字符覆盖率比编辑距离更贴近直觉（上理电竞 → 上理GM电竞…）
    if len(nq) >= 3:
        sim = max(sim, 0.9 * _coverage(nq, nn))
    return round(0.85 * sim, 4), "similar"


def rank(query, items: Iterable, name_of: Callable, limit: int = 5
         ) -> List[Tuple[float, str, str, object]]:
    """按分数排序取前 limit 个，返回 [(分数, 级别, 名字, item)]"""
    scored = []
    for item in items or []:
        name = str(name_of(item) or "").strip()
        s, level = score(query, name)
        if s > 0:
            scored.append((s, level, name, item))
    scored.sort(key=lambda x: (-x[0], len(x[2])))
    return scored[:limit]


def pick(query, items: Iterable, name_of: Callable, limit: int = 5
         ) -> Tuple[object, List[Tuple[float, str]]]:
    """匹配并决定是否可以直接用：返回 (命中的 item 或 None, 候选 [(分数, 名字)])

    - 精确 / 归一化 / 前缀 / 拼音 级别，且明显强于第二名 → 返回 item（可直接发）；
    - 包含级别：查询 ≥2 字且只多出「不超过查询本身长度」时才直接用，否则追问；
    - 相似度级别（错字/缺字）与拼音前缀：永不自动发，只把候选交给追问。
    """
    ranked = rank(query, items, name_of, limit)
    if not ranked:
        return None, []
    best_score, best_level, best_name, best_item = ranked[0]
    second_score, second_level = (ranked[1][0], ranked[1][1]) if len(ranked) > 1 else (0.0, "")
    second_rank = LEVEL_RANK.get(second_level, -1)
    decisive = (LEVEL_RANK.get(best_level, 0) > second_rank) or \
               ((best_score - second_score) >= GAP)
    candidates = [(s, n) for s, _l, n, _i in ranked]
    if best_level in AUTO_LEVELS and decisive:
        return best_item, candidates
    if best_level == "contains" and decisive:
        nq, nn = normalize(query), normalize(best_name)
        extra = len(nn) - len(nq)
        if len(nq) >= 2 and extra <= max(1, len(nq)):
            return best_item, candidates
    return None, candidates
