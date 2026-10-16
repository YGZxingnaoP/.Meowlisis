# -*- coding: utf-8 -*-
"""养猪游戏：GUI 配置面板 schema（纯数据）。"""

PLUGIN = {
    "id": "pig_game",
    "title": "养猪游戏",
    "version": "1.0.0",
    "group": "game",
    "emoji": "\U0001F437",          # 🐷
    "default_enabled": True,
}

FIELDS = [
    {"key": "enabled", "label": "启用养猪游戏", "type": "check", "default": True,
     "help": "关闭后所有养猪指令都不再响应"},

    {"key": "command_prefix", "label": "指令口令前缀（逗号分隔）", "type": "text",
     "default": "猪猪游戏,养猪游戏",
     "help": "玩家消息里必须出现其中之一才会触发游戏，例如「猪猪游戏 打卡」；"
             "不带口令时插件不响应（只回一句提示），避免和普通聊天/其它机器人抢词"},

    # ---------- 玩家 ----------
    {"key": "coins_init", "label": "新玩家初始金币", "type": "num", "default": 20,
     "min": 0, "max": 99999, "step": 1},
    {"key": "affinity_init", "label": "新玩家初始好感度", "type": "num", "default": 1,
     "min": 0, "max": 20, "step": 1},
    {"key": "affinity_max", "label": "好感度上限", "type": "num", "default": 20,
     "min": 1, "max": 100, "step": 1},

    # ---------- 体力 ----------
    {"key": "stamina_max", "label": "每日体力上限", "type": "num", "default": 100,
     "min": 10, "max": 999, "step": 1},
    {"key": "stamina_cost.steal", "label": "偷猪消耗体力", "type": "num", "default": 10,
     "min": 0, "max": 100, "step": 1},
    {"key": "stamina_cost.fake", "label": "假扮打卡消耗体力", "type": "num", "default": 5,
     "min": 0, "max": 100, "step": 1},
    {"key": "stamina_cost.raid", "label": "抢猪消耗体力", "type": "num", "default": 15,
     "min": 0, "max": 100, "step": 1},
    {"key": "stamina_cost.raid_force", "label": "强制抢猪消耗体力", "type": "num", "default": 30,
     "min": 0, "max": 100, "step": 1},
    {"key": "stamina_cost.ride", "label": "骑猪消耗体力", "type": "num", "default": 8,
     "min": 0, "max": 100, "step": 1},
    {"key": "stamina_cost.clean", "label": "打扫猪圈消耗体力", "type": "num", "default": 5,
     "min": 0, "max": 100, "step": 1},
    {"key": "stamina_cost.dinner", "label": "共进晚餐消耗体力", "type": "num", "default": 3,
     "min": 0, "max": 100, "step": 1},
    {"key": "stamina_cost.patrol", "label": "巡视猪圈消耗体力", "type": "num", "default": 2,
     "min": 0, "max": 100, "step": 1},

    # ---------- 偷猪 ----------
    {"key": "steal_max_per_time", "label": "偷猪单次上限", "type": "num", "default": 5,
     "min": 1, "max": 50, "step": 1},
    {"key": "steal_default_count", "label": "偷猪默认数量", "type": "num", "default": 1,
     "min": 1, "max": 50, "step": 1},
    {"key": "steal_min_prob", "label": "偷猪最低成功率", "type": "num", "default": 0.02,
     "min": 0, "max": 1, "step": 0.01},
    {"key": "steal_affinity_discount", "label": "好感度抑制被偷幅度", "type": "num", "default": 0.6,
     "min": 0, "max": 1, "step": 0.05,
     "help": "主人好感度满值时，被偷概率最多降低该比例"},

    # ---------- 假扮 ----------
    {"key": "fake_steal_ratio", "label": "假扮窃取产币比例", "type": "num", "default": 0.5,
     "min": 0, "max": 1, "step": 0.05},
    {"key": "fake_discover_ratio", "label": "假扮发现率系数", "type": "num", "default": 0.8,
     "min": 0, "max": 1, "step": 0.05},

    # ---------- 战斗 ----------
    {"key": "raid_k", "label": "战斗系数 K", "type": "num", "default": 10.0,
     "min": 1, "max": 100, "step": 1,
     "help": "越小越容易低点数反超"},
    {"key": "raid_random_low", "label": "战斗随机下限", "type": "num", "default": 0.9,
     "min": 0.1, "max": 1, "step": 0.05},
    {"key": "raid_random_high", "label": "战斗随机上限", "type": "num", "default": 1.1,
     "min": 1, "max": 3, "step": 0.05},
    {"key": "raid_take_max", "label": "单次抢夺上限", "type": "num", "default": 5,
     "min": 1, "max": 50, "step": 1},
    {"key": "raid_take_divisor", "label": "抢夺换算除数", "type": "num", "default": 20.0,
     "min": 1, "max": 200, "step": 1,
     "help": "夺取数量 = round(|点差| / 该值)"},

    # ---------- 池塘 ----------
    {"key": "pond_cost", "label": "池塘维护费", "type": "num", "default": 20,
     "min": 0, "max": 9999, "step": 1},
    {"key": "pond_decay_start_days", "label": "开始消失天数", "type": "num", "default": 3,
     "min": 1, "max": 30, "step": 1},
    {"key": "pond_decay_ratio", "label": "每天消失比例", "type": "num", "default": 0.3,
     "min": 0.05, "max": 1, "step": 0.05},
    {"key": "pond_clear_days", "label": "全部消失天数", "type": "num", "default": 7,
     "min": 1, "max": 60, "step": 1},

    # ---------- 天降猪猪（买猪商店） ----------
    {"key": "shop_enabled", "label": "开启「天降猪猪」商店", "type": "check", "default": True,
     "help": "关闭后「天降猪猪」不再响应"},
    {"key": "shop_daily_limit", "label": "每个猪种每天限购", "type": "num", "default": 100,
     "min": 0, "max": 9999, "step": 1,
     "help": "按猪种分别计数，每天刷新；0 = 不限购。卖什么、卖多少由各猪种 "
             "species.json 里的 shop_price 决定（0 = 不上架）"},
    {"key": "shop_stamina_cost", "label": "买猪消耗体力", "type": "num", "default": 0,
     "min": 0, "max": 100, "step": 1,
     "help": "0 = 不花体力，纯金币购买"},

    # ---------- 交易 ----------
    {"key": "trade_skip_seller_multiplier", "label": "超高价跳过卖方倍数", "type": "num",
     "default": 1.5, "min": 1, "max": 10, "step": 0.1,
     "help": "出价 ≥ 估价 × 该值 时直接成交，无需卖方确认"},
    {"key": "trade_fail_affinity_threshold", "label": "卖方好感度失败阈值", "type": "num",
     "default": 12, "min": 0, "max": 100, "step": 1,
     "help": "卖方好感度超过该值后，交易按概率失败"},
    {"key": "trade_fail_prob_per_point", "label": "每点好感度失败率", "type": "num",
     "default": 0.1, "min": 0, "max": 1, "step": 0.05},
    {"key": "trade_fail_prob_max", "label": "交易失败率上限", "type": "num",
     "default": 0.9, "min": 0, "max": 1, "step": 0.05},
    {"key": "trade_price_multiplier_max", "label": "出价上限倍数", "type": "num",
     "default": 3.0, "min": 1, "max": 20, "step": 0.5,
     "help": "单价上限 = 估价 × 该值"},
    {"key": "trade_single_price_cap", "label": "单价硬上限", "type": "num",
     "default": 9999, "min": 1, "max": 999999, "step": 1},

    # ---------- 资源 ----------
    {"key": "scenes", "label": "猪圈场景（逗号分隔）", "type": "text",
     "default": "grass,farm,night",
     "help": "对应 assets/scene_<名字>.png，玩家可用「设置猪圈场景」切换"},
    {"key": "assets_dir", "label": "图片目录", "type": "text", "default": "assets"},

    # ---------- LLM ----------
    {"key": "llm.enabled", "label": "启用 LLM 点评", "type": "check", "default": True,
     "help": "关闭后用模板文案兜底"},
    {"key": "llm.provider", "label": "接口平台", "type": "select", "default": "deepseek",
     "options": [{"value": "deepseek", "label": "DeepSeek"},
                 {"value": "aliyun", "label": "阿里云"},
                 {"value": "gemini", "label": "Gemini"},
                 {"value": "openai", "label": "OpenAI"}]},
    {"key": "llm.api_key", "label": "API Key", "type": "password", "default": "",
     "help": "留空则复用 toolbox 的 LLM 端口"},
    {"key": "llm.base_url", "label": "Base URL", "type": "text", "default": "",
     "help": "留空用平台默认"},
    {"key": "llm.model", "label": "模型", "type": "text", "default": "",
     "help": "留空用平台默认"},
    {"key": "llm.temperature", "label": "温度", "type": "num", "default": 0.8,
     "min": 0, "max": 2, "step": 0.1},
]
