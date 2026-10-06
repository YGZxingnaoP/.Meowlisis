# -*- coding: utf-8 -*-
"""养猪游戏：交易数学（纯函数）。"""


def estimate_price(cfg, book, species_id, seller_affinity):
    """当前估价 = 基础单价 × (1 + 卖方好感度 / 好感度上限)。"""
    sp = book.get(species_id)
    if not sp:
        return 0.0
    base = float(sp.get("base_price") or 0)
    amax = max(1.0, float(cfg.affinity_max))
    return base * (1.0 + float(seller_affinity or 0) / amax)


def max_count(cfg, book, species_id, seller_count):
    """单笔数量上限 = min(猪种上限, 卖方持有量)。"""
    sp = book.get(species_id)
    if not sp:
        return 0
    try:
        limit = int(sp.get("trade_count_max") or 0)
    except Exception:
        limit = 0
    return max(0, min(limit, int(seller_count or 0)))


def price_cap(cfg, book, species_id, seller_affinity):
    """单价上限 = min(硬上限, 估价 × 倍数上限)。"""
    est = estimate_price(cfg, book, species_id, seller_affinity)
    cap = min(float(cfg.trade_single_price_cap),
              est * float(cfg.trade_price_multiplier_max))
    return max(0.0, cap), est


def skip_threshold(cfg, book, species_id, seller_affinity):
    """超高价阈值：达到即直接成交，跳过卖方。"""
    est = estimate_price(cfg, book, species_id, seller_affinity)
    return est * float(cfg.trade_skip_seller_multiplier)


def fail_prob(cfg, seller_affinity):
    """卖方好感度过高导致的交易失败概率。"""
    th = float(cfg.trade_fail_affinity_threshold)
    aff = float(seller_affinity or 0)
    if aff <= th:
        return 0.0
    p = (aff - th) * float(cfg.trade_fail_prob_per_point)
    return max(0.0, min(float(cfg.trade_fail_prob_max), p))
