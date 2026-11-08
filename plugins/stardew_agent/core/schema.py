# -*- coding: utf-8 -*-
"""星露谷 AI 玩家：GUI 配置面板 schema（纯数据）。"""

PLUGIN = {
    "id": "stardew_agent",
    "title": "星露谷 AI 玩家",
    "version": "0.6.0",
    "group": "game",
    "emoji": "\U0001F33E",          # 🌾
    "default_enabled": False,
}

FIELDS = [
    {"key": "enabled", "label": "启用星露谷插件", "type": "check", "default": False,
     "help": "关闭后群里所有「星露谷 …」指令都不再响应，角色也不会自己玩"},

    {"key": "qq_prefix", "label": "群指令前缀", "type": "text", "default": "星露谷",
     "help": "消息以此开头才接管，例如「星露谷 状态」；未命中前缀时不插手任何聊天"},

    {"key": "bridge_url", "label": "mod 接口地址", "type": "text",
     "default": "http://127.0.0.1:8766",
     "help": "移植后的执行层只监听本机；MCP 在 18080，插件用的 REST 在 8766（8765 被主程序字幕占用）"},

    {"key": "timeout", "label": "桥接超时（秒）", "type": "num", "default": 5,
     "min": 1, "max": 30, "step": 1},

    {"key": "persona", "label": "角色名（写日记用）", "type": "text", "default": "",
     "help": "留空则用主程序当前 AI 名字"},

    {"key": "instance_label", "label": "实例标记（联机用）", "type": "text", "default": "",
     "help": "多开时各实例填不同值，存档目录会分开；留空就是主号"},

    # ===== 插件自己的面板 =====
    {"key": "dashboard.enabled", "label": "启用插件网页面板", "type": "check", "default": True,
     "help": "插件自己起一个本地只读面板：日记 / 待办 / 计划图谱 / 日志 / 记忆 / 习惯"},
    {"key": "dashboard.port", "label": "面板端口", "type": "num", "default": 8760,
     "min": 1024, "max": 65535, "step": 1,
     "help": "浏览器打开 http://127.0.0.1:<端口>/；和 mod 的 8756 分开"},

    # ===== 自主 =====
    {"key": "autonomy.enabled", "label": "自己安排一天", "type": "check", "default": True,
     "help": "开始玩之后，角色会自己评估、做计划、执行；关闭后只听建议"},
    {"key": "autonomy.auto_start", "label": "加载插件就自动开始玩", "type": "check", "default": False},
    {"key": "autonomy.llm", "label": "让模型参与计划 / 日记 / 记忆总结", "type": "check", "default": True,
     "help": "关闭后全部走规则兜底，不烧 token，但角色会笨一些"},
    {"key": "autonomy.pace", "label": "干活节奏", "type": "select",
     "options": [{"value": "relaxed", "label": "放松（有娱乐，不硬撑）"},
                 {"value": "normal", "label": "正常"},
                 {"value": "busy", "label": "勤奋（多干活，少休息）"}],
     "default": "relaxed"},
    {"key": "autonomy.long_term", "label": "长线目标的初始方向", "type": "text",
     "default": "把农场经营好、多赚点钱、和镇上的人熟起来",
     "help": "逗号分隔；第一次生成规划树时用，之后以 plans/long_term.json 为准"},
    {"key": "autonomy.sleep_hour", "label": "几点回家睡觉", "type": "num", "default": 22,
     "min": 18, "max": 26, "step": 1, "help": "按游戏内时间；26 表示凌晨 2 点"},
    {"key": "autonomy.energy_floor", "label": "体力下限（%）", "type": "num", "default": 8,
     "min": 0, "max": 60, "step": 1},
    {"key": "autonomy.narrate_minutes", "label": "主动说话的间隔（分钟）", "type": "num", "default": 2,
     "min": 0, "max": 180, "step": 1, "help": "0 表示只在换天/计划/失败时说话"},
    {"key": "autonomy.idle_seconds", "label": "没事干时的等待（秒）", "type": "num", "default": 12,
     "min": 3, "max": 120, "step": 1},
    {"key": "autonomy.farm_vision", "label": "农场地块太碎时允许看截图定田", "type": "check", "default": True,
     "help": "平时不传图；只有规则算不出矩形时才截一张"},

    # ===== 重要输入询问 =====
    {"key": "user_input.enabled", "label": "重要输入先问用户", "type": "check", "default": True,
     "help": "起名、职业选择等先通过 QQ/TTS 问；等待期间停止操作，超时自己决定"},
    {"key": "user_input.timeout_seconds", "label": "等待回复秒数", "type": "num", "default": 60,
     "min": 15, "max": 300, "step": 5},

    # ===== 起名 / 改名 =====
    {"key": "naming.ask_user", "label": "起名时先问用户", "type": "check", "default": True,
     "help": "新动物/孩子要起名时，先通过 QQ/TTS 问你；超时用兜底名字"},
    {"key": "naming.timeout_seconds", "label": "等名字的秒数", "type": "num", "default": 60,
     "min": 15, "max": 300, "step": 5},
    {"key": "naming.fallback", "label": "超时备用名（可留空）", "type": "text", "default": "",
     "help": "留空时角色根据记忆/经历自己起名；只有模型也失败时才用这里的字"},

    # ===== 规划 =====
    {"key": "plans.max_roots", "label": "长线规划最多几个根目标", "type": "num", "default": 3,
     "min": 1, "max": 5, "step": 1},
    {"key": "plans.max_leaves", "label": "当日计划最多几条叶子", "type": "num", "default": 10,
     "min": 4, "max": 20, "step": 1},

    # ===== 记忆 / 习惯 =====
    {"key": "memory.recall", "label": "每次召回多少条记忆 tips", "type": "num", "default": 8,
     "min": 2, "max": 30, "step": 1},
    {"key": "tips.enabled", "label": "启用长期记忆 tips", "type": "check", "default": True,
     "help": "每晚从日志里提炼长期有价值的信息；一个季节一个 JSON"},
    {"key": "habits.enabled", "label": "启用生活习惯", "type": "check", "default": True,
     "help": "每 7 天总结一次，只作为轻量提示，不限制角色"},
    {"key": "habits.affect_plan", "label": "习惯参与计划加权", "type": "check", "default": True},

    # ===== 分享 / 反馈 =====
    {"key": "feedback.enabled", "label": "做完了说一句 / 主动分享", "type": "check", "default": True},
    {"key": "feedback.share_images", "label": "分享时附一张游戏截图", "type": "check", "default": True,
     "help": "需要 mod 的 screen 截图；失败就只发文字"},
    {"key": "feedback.share_minutes", "label": "两条分享最短间隔（分钟）", "type": "num",
     "default": 60, "min": 10, "max": 1440, "step": 5,
     "help": "防止 QQ 被农场日常刷屏"},
    {"key": "feedback.share_max_per_day", "label": "每天最多分享几次", "type": "num",
     "default": 1, "min": 0, "max": 20, "step": 1, "help": "由角色自己判断要不要发；这里只限上限"},
    {"key": "share.groups", "label": "分享到哪些群（群号，可多个）", "type": "list", "default": [],
     "help": "每行一个；留空=发到最近说话的会话"},
    {"key": "share.users", "label": "分享给哪些人（QQ 号，可多个）", "type": "list", "default": []},
    {"key": "broadcast.danmaku", "label": "自言自语同步到直播间弹幕", "type": "check", "default": False},
    {"key": "broadcast.tts", "label": "自言自语同时走 TTS", "type": "check", "default": False},

    # ===== 性格 =====
    {"key": "traits.diligence", "label": "性格 · 勤劳", "type": "num", "default": 0.6,
     "min": 0, "max": 1, "step": 0.1},
    {"key": "traits.sociability", "label": "性格 · 爱交际", "type": "num", "default": 0.5,
     "min": 0, "max": 1, "step": 0.1},
    {"key": "traits.curiosity", "label": "性格 · 好奇", "type": "num", "default": 0.5,
     "min": 0, "max": 1, "step": 0.1},
    {"key": "traits.thrift", "label": "性格 · 在乎钱", "type": "num", "default": 0.5,
     "min": 0, "max": 1, "step": 0.1},

    # ===== 发型 / 配饰（不做整套皮肤，只保留两个游戏内编号）=====
    {"key": "appearance.hair_style", "label": "当前发型编号", "type": "num", "default": 0,
     "min": 0, "max": 200, "step": 1,
     "help": "对应游戏 hairstyles 表；0 表示不改"},
    {"key": "appearance.accessory", "label": "当前配饰编号", "type": "num", "default": 0,
     "min": 0, "max": 200, "step": 1,
     "help": "对应游戏 accessories 表；0 表示不改。整套皮肤/衣服替换已删除"},
]
