# -*- coding: utf-8 -*-
"""养猪游戏插件（NapCat / QQ 链路）—— 关键词本地触发，**不是工具**。

要点：
  · `trigger_tools()` 返回空、`prompt_hint()` 返回空串 → 对主链路 LLM **零负担**；
  · 拦截能力就是插件自己的 `route_qq(text, qq_context, username)` 方法，
    plugin 模块的 `PluginManager.route_qq()` 只负责"把消息递过来"，不掺和任何判定；
  · 接不接、怎么判口令、怎么执行，全部在本方法内的本地逻辑里完成（零 LLM）。
"""

import os

from func.toolbox.plugins.sdk import ToolboxPlugin

from .core.runner import PigRunner


class PigApp(PigRunner):
    """插件内运行器（基类不依赖主链路，便于本地测试共用同一套逻辑）。"""

    def __init__(self, ctx):
        super().__init__(ctx, os.path.dirname(os.path.abspath(__file__)))


class Plugin(ToolboxPlugin):
    id = "pig_game"
    title = "养猪游戏"
    version = "2.2.0"
    default_enabled = True

    def __init__(self):
        self._app = None

    # ---- 不是工具：不给 LLM 注册任何工具，也不追加任何提示词 ----
    def trigger_tools(self):
        return []

    def interface_tools(self):
        return []

    def prompt_hint(self):
        return ""

    # ---- 消息拦截：框架把 QQ 消息递过来，这里自己判定 ----
    def route_qq(self, text, qq_context, username=""):
        """返回 True = 已接管（消息不再走主链路回复）。

        · 没有口令前缀「猪猪游戏」/「养猪游戏」→ 返回 False，完全不插手；
        · 群聊能走到这里，本身就说明已经 @ 了机器人（@ / 关键词触发）。
        """
        if self._app is None:
            return False
        qq_context = dict(qq_context or {})
        if username:
            qq_context.setdefault("username", username)
        return bool(self._app.route(text, qq_context, at_self=True))

    def setup(self, ctx):
        self._app = PigApp(ctx)
        try:
            ctx.log.info("养猪游戏插件已初始化（关键词触发，非工具）：猪种 %d 种，口令 %s，数据目录 %s"
                         % (len(self._app.book.all()), self._app.cfg.prefixes(), self._app.data_dir))
        except Exception:
            pass

    def teardown(self):
        try:
            if self._app is not None:
                self._app.store.save_all()
        except Exception:
            pass
        self._app = None


PLUGIN = Plugin()
