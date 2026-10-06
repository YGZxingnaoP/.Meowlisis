# -*- coding: utf-8 -*-
"""养猪游戏：运行器（不依赖主链路，插件与本地测试共用）。

- 零 LLM：口令识别、指令解析、玩法执行全部本地完成；
- 只依赖注入的 ctx（需要 ctx.napcat() / ctx.config / ctx.log / ctx.llm()），
  因此本地测试器可以用一个假 ctx 直接跑真实流程。
"""

import os

from ..text import commands
from ..text import parse
from ..view import render
from ..text import rules
from .config import PigConfig
from .engine import Engine
from ..llm.comment import PigLLM
from .species import SpeciesBook
from .store import Store


class PigRunner:
    """配置 / 猪种表 / 存档 / 引擎 / LLM / 渲染。"""

    def __init__(self, ctx, base_dir, data_dir=None):
        self.ctx = ctx
        self.base = base_dir
        self.cfg = PigConfig(getattr(ctx, "config", {}) or {})
        self.assets_dir = os.path.join(base_dir, str(self.cfg.assets_dir))
        self.data_dir = data_dir or os.path.join(base_dir, str(self.cfg.data_dir))
        os.makedirs(self.data_dir, exist_ok=True)
        self.cache_dir = os.path.join(self.data_dir, "cache")   # 卡片图落盘目录
        self.book = SpeciesBook(self.assets_dir)
        self.store = Store(self.data_dir)
        self.llm = PigLLM(ctx, self.cfg)
        self.engine = Engine(self)

    # ---------- 图片 ----------
    def pig_image(self, species_id):
        return render.pig_image(self.cfg, self.book, species_id)

    def scene_image(self, scene):
        return render.scene_image(self.cfg, scene)

    # ---------- 接管判定 ----------
    def accept(self, text, qq_context, at_self=True):
        """是否接管这条消息（口令前缀 + 群聊需 @）"""
        t = str(text or "").strip()
        if not t:
            return False
        if not parse.has_prefix(t, self.cfg.prefixes()):
            return False
        if str((qq_context or {}).get("message_type") or "") == "group" and not at_self:
            return False
        return True

    # ---------- 核心接管入口 ----------
    def route(self, text, qq_context, at_self=True):
        """QQ 消息接管：返回 True 表示已处理（主链路应终止后续流程）。"""
        qq_context = dict(qq_context or {})
        if not self.accept(text, qq_context, at_self):
            return False
        try:
            tool, args, _body = commands.parse_command(text, self.cfg.prefixes())
            if tool is None:
                # 只说了口令 / 认不出指令 → 回指令字典
                render.send(self.ctx, qq_context,
                            {"text": rules.MENU, "card": rules.command_card()},
                            assets_dir=self.assets_dir, cache_dir=self.cache_dir)
                return True
            res = self.engine.handle(tool, args or {}, qq_context)
            render.send(self.ctx, qq_context, res,
                        assets_dir=self.assets_dir, cache_dir=self.cache_dir)
            return True
        except Exception:
            try:
                self.ctx.log.exception("养猪游戏：处理指令失败 %s" % str(text)[:30])
            except Exception:
                pass
            return False
