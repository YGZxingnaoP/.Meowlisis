# -*- coding: utf-8 -*-
# func/toolbox/danmaku/reply/read_aloud.py
# 弹幕朗读模板（普通弹幕 / SC 专属），供 reply_engine 组装朗读文本

import random


class TBDanmakuReadAloud:
    """弹幕朗读文案模板与随机选择

    - 普通弹幕：3 种模板，支持固定一种或随机；
    - SC：2 种模板，每个都读，随机选择（不做固定配置）。
    """

    # 普通弹幕朗读模板
    NORMAL_TEMPLATES = {
        "template1": "{username}说:{content}",
        "template2": "{content}，来自{username}",
        "template3": "我来看看，{username}说：{content}",
    }

    # SC 专属朗读模板（每个都读，随机）
    SC_TEMPLATES = [
        "感谢{username}的sc，{content}",
        "{username}的sc说，{content}",
    ]

    def __init__(self, read_aloud_mode: str = "random"):
        self.mode = str(read_aloud_mode or "random").strip().lower()

    def render_normal(self, username: str, content: str) -> str:
        """按配置模式生成普通弹幕朗读文本"""
        username = username or "用户"
        content = content or ""
        if self.mode in self.NORMAL_TEMPLATES:
            tmpl = self.NORMAL_TEMPLATES[self.mode]
        else:
            # random（含未知配置兜底）
            tmpl = random.choice(list(self.NORMAL_TEMPLATES.values()))
        return tmpl.format(username=username, content=content)

    @staticmethod
    def render_sc(username: str, content: str) -> str:
        """生成 SC 朗读文本（每个都读，随机模板）"""
        username = username or "用户"
        content = content or ""
        tmpl = random.choice(TBDanmakuReadAloud.SC_TEMPLATES)
        return tmpl.format(username=username, content=content)
