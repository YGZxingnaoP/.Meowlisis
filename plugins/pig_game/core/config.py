# -*- coding: utf-8 -*-
"""养猪游戏：配置读取与默认值（全部可在 config.yml / 配置面板调整）。"""

DEFAULTS = {
    "enabled": True,

    # ---------- 玩家 ----------
    "coins_init": 20,                      # 新玩家初始金币
    "affinity_init": 1,                    # 新玩家初始好感度
    "affinity_max": 20,                    # 好感度上限（范围 0~max）
    "init_pigs": {"super_fat": 5},         # 新玩家初始猪

    # ---------- 体力 ----------
    "stamina_max": 100,
    "stamina_cost": {
        "fake": 5, "steal": 10, "raid": 15, "raid_force": 30,
        "ride": 8, "clean": 5, "dinner": 3, "patrol": 2,
    },
    "affinity_delta": {"ride": -2, "clean": 1, "dinner": 2, "patrol": 0},

    # ---------- 偷猪 ----------
    "steal_max_per_time": 5,               # 单次偷猪上限
    "steal_default_count": 1,              # 未写数量的默认值
    "steal_affinity_discount": 0.6,        # 主人好感度对被偷概率的抑制幅度
    "steal_min_prob": 0.02,

    # ---------- 假扮打卡 ----------
    "fake_steal_ratio": 0.5,               # 窃取对方当日应得产币比例
    "fake_discover_ratio": 0.8,            # 对方好感度对发现率的贡献

    # ---------- 战斗 ----------
    "raid_k": 10.0,                        # 胜率 sigmoid 系数（越小越容易低点反超）
    "raid_random_low": 0.9,
    "raid_random_high": 1.1,
    "raid_take_divisor": 20.0,             # 夺取数量 = |点差| / 该值
    "raid_take_max": 5,                    # 单次抢夺上限

    # ---------- 池塘 ----------
    "pond_cost": 20,                       # 维护费
    "pond_decay_start_days": 3,            # 第几天开始消失
    "pond_decay_ratio": 0.3,               # 每天减少比例
    "pond_clear_days": 7,                  # 第几天清零

    # ---------- 天降猪猪（买猪商店） ----------
    "shop_enabled": True,                  # 商店开不开门
    "shop_daily_limit": 100,               # 每人每个猪种每天最多买几头
    "shop_stamina_cost": 0,                # 买猪花多少体力（0 = 不花）

    # ---------- 交易 ----------
    "trade_skip_seller_multiplier": 1.5,   # 超高价倍数（达到即跳过卖方）
    "trade_price_multiplier_max": 3.0,     # 出价上限 = 估价 × 该值
    "trade_single_price_cap": 9999,        # 单笔单价硬上限
    "trade_fail_affinity_threshold": 12,   # 卖方好感度超过该值开始有失败概率
    "trade_fail_prob_per_point": 0.1,
    "trade_fail_prob_max": 0.9,

    # ---------- 触发 ----------
    # 玩家消息里必须出现其中之一，才会触发养猪游戏（避免"打卡"等词误触发）
    "command_prefix": "猪猪游戏,养猪游戏",

    # ---------- 资源 ----------
    "scenes": ["grass", "farm", "night"],
    "assets_dir": "assets",
    "data_dir": "data",

    # ---------- LLM ----------
    "llm": {"enabled": True, "api_key": "", "base_url": "", "model": "", "temperature": 0.8},
}


class PigConfig:
    """养猪游戏配置对象：属性式读取，缺省回落默认值。"""

    def __init__(self, data=None):
        d = dict(DEFAULTS)
        for k, v in (data or {}).items():
            d[k] = v
        self.raw = d
        for k, v in DEFAULTS.items():
            if k == "llm":
                continue
            setattr(self, k, d.get(k, v))
        llm = dict(DEFAULTS["llm"])
        llm.update(d.get("llm") or {})
        self.llm = llm
        if not isinstance(self.stamina_cost, dict):
            self.stamina_cost = dict(DEFAULTS["stamina_cost"])
        if not isinstance(self.affinity_delta, dict):
            self.affinity_delta = dict(DEFAULTS["affinity_delta"])
        if not isinstance(self.init_pigs, dict) or not self.init_pigs:
            self.init_pigs = dict(DEFAULTS["init_pigs"])
        if isinstance(self.scenes, str):
            self.scenes = [s.strip() for s in self.scenes.replace("，", ",").split(",") if s.strip()]
        if not isinstance(self.scenes, list) or not self.scenes:
            self.scenes = list(DEFAULTS["scenes"])

    # ---------- 便捷读取 ----------
    def stamina(self, key):
        """某行为的体力消耗"""
        try:
            return int((self.stamina_cost or {}).get(key, 0))
        except Exception:
            return 0

    def aff_delta(self, key):
        """某互动的好感度变化"""
        try:
            return int((self.affinity_delta or {}).get(key, 0))
        except Exception:
            return 0

    def prefixes(self):
        """指令前缀列表（玩家消息里必须出现其中之一）"""
        raw = self.command_prefix
        if isinstance(raw, (list, tuple)):
            items = [str(x).strip() for x in raw]
        else:
            items = [s.strip() for s in str(raw or "").replace("，", ",").split(",")]
        items = [s for s in items if s]
        return items or ["猪猪游戏"]
