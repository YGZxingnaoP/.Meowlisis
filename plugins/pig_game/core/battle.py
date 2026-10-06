# -*- coding: utf-8 -*-
"""养猪游戏：战斗数学（纯函数）。

魔法猪为"整队加成"：加值 = 非魔法猪点数 × Σ(魔法猪 team_bonus)，是固定加值，不乘在总分上。
"""

import math
import random


def team_points(cfg, book, squad):
    """计算一支部队的点数，返回 (总点数, 明细)。"""
    base = 0.0          # 非魔法猪点数
    magic_self = 0.0    # 魔法猪自身点数
    bonus_rate = 0.0    # 魔法猪整队加成系数之和（每个魔法猪种计一次）
    for sid, cnt in (squad or {}).items():
        sp = book.get(sid)
        if not sp:
            continue
        try:
            cnt = int(cnt or 0)
        except Exception:
            cnt = 0
        if cnt <= 0:
            continue
        atk = float(sp.get("attack") or 0)
        if sp.get("type") == "magic":
            magic_self += atk * cnt
            bonus_rate += float(sp.get("team_bonus") or 0)
        else:
            base += atk * cnt
    bonus = base * bonus_rate
    raw = base + magic_self + bonus
    mult = random.uniform(float(cfg.raid_random_low), float(cfg.raid_random_high))
    detail = {"base": base, "magic_self": magic_self, "bonus": bonus,
              "raw": raw, "mult": mult, "total": raw * mult}
    return raw * mult, detail


def win_prob(cfg, a_points, b_points):
    """攻方胜率：点数接近时低点方也有机会翻盘。"""
    k = max(0.001, float(cfg.raid_k))
    try:
        return 1.0 / (1.0 + math.exp(-(a_points - b_points) / k))
    except Exception:
        return 0.5


def take_count(cfg, delta):
    """按领先点数换算夺取数量。"""
    try:
        n = int(round(abs(delta) / max(1.0, float(cfg.raid_take_divisor))))
    except Exception:
        n = 1
    return max(1, min(int(cfg.raid_take_max), n))
