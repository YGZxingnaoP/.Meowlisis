# -*- coding: utf-8 -*-
"""Meowlisis 梗库插件：GUI 配置面板 schema（纯数据）。

字段类型与现有插件一致：check / text / num / select / list。
配置保存在 plugins/meme_wiki/config.yml，保存后重启或重载插件生效。
"""

PLUGIN = {
    "id": "meme_wiki",
    "title": "Meowlisis 梗库",
    "version": "1.0.0",
    "group": "social",
    "emoji": "\U0001F4DA",          # 📚
    "default_enabled": True,
}

FIELDS = [
    {"key": "enabled", "label": "启用梗库", "type": "check", "default": True,
     "help": "关闭后 QQ 私聊/群聊都不再处理梗库指令和召回"},

    {"key": "add_prefix", "label": "加梗触发词", "type": "text", "default": "Meowlisis梗",
     "help": "消息以它开头时，后面写「词 描述：... 接法：...」"},

    {"key": "query_prefix", "label": "查梗触发词", "type": "text", "default": "Meowlisis查梗",
     "help": "不加词 = 把整个梗库转成 Markdown；加词 = 只发匹配的条目"},

    {"key": "recall_threshold", "label": "召回阈值", "type": "num", "default": 0.45,
     "min": 0.05, "max": 1.0, "step": 0.05,
     "help": "消息和梗的重合度达到该值才召回；越高越保守"},

    {"key": "recall_top_k", "label": "最多召回几条", "type": "num", "default": 3,
     "min": 1, "max": 5, "step": 1},

    {"key": "history_rounds", "label": "带给角色的对话轮数", "type": "num", "default": 6,
     "min": 0, "max": 20, "step": 1,
     "help": "召回命中后，把最近多少轮短期记忆一起交给角色模型"},

    {"key": "max_desc_chars", "label": "单条梗字数上限", "type": "num", "default": 500,
     "min": 20, "max": 2000, "step": 10},

    {"key": "max_reply_chars", "label": "角色回复字数上限", "type": "num", "default": 120,
     "min": 20, "max": 500, "step": 10},

    {"key": "cooldown_seconds", "label": "召回冷却(秒)", "type": "num", "default": 8,
     "min": 0, "max": 3600, "step": 1,
     "help": "同一会话两次召回生成之间的最小间隔"},

    {"key": "allow_add", "label": "谁能加梗", "type": "select", "default": "all",
     "options": [{"value": "all", "label": "所有人"},
                 {"value": "admin", "label": "仅管理员"},
                 {"value": "off", "label": "禁止加梗"}]},

    {"key": "admin_qqs", "label": "管理员 QQ 号", "type": "list", "default": [],
     "help": "删除梗需要这里的 QQ 号；留空 = 删除功能关闭"},

    {"key": "max_entries", "label": "最多条数", "type": "num", "default": 5000,
     "min": 10, "max": 100000, "step": 100},

    {"key": "reply_with_at", "label": "群聊回复时 @ 提问人", "type": "check", "default": False},

    {"key": "write_memory", "label": "召回回复写入短期记忆", "type": "check", "default": True,
     "help": "插件接管本次回复时，把用户消息和角色回复按 QQ 记忆类型写回"},
]
