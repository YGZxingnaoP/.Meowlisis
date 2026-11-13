# -*- coding: utf-8 -*-
"""蔚蓝色图插件（image_factory）。

关键词：`Meowlisis蔚蓝色图 [角色] [张数]`（前缀可在插件配置里改）

· 主题固定蔚蓝档案；不给角色就随机挑不同角色，给了角色就只画她；
· 角色 danbooru tag 先查缓存/在线（`shiroko (blue archive)`），查不到跳过，不阻塞；
· 出图固定 MOSS-Image 8 步 DMD（与官方工作流开关开启档一致）；
· 所有图片打包成一条 QQ 聊天记录（合并转发），失败退回逐张发送。

不写钩子：内核自启、织图、取 tag、凑包都在本插件 core/ 内自包含。
"""

from .core.app import BlueArchiveApp


class Plugin:
    """蔚蓝色图插件入口：关键词拦截 + 生命周期。"""
    id = "image_factory"
    title = "蔚蓝色图"
    version = "2.0.0"
    default_enabled = True

    def __init__(self):
        """初始化插件状态。"""
        self._app = None

    def trigger_tools(self):
        """纯关键词拦截，不给 LLM 注册工具"""
        return []

    def interface_tools(self):
        """不提供界面工具。"""
        return []

    def prompt_hint(self):
        """不注入提示词。"""
        return ""

    def setup(self, ctx):
        """读取配置并创建出图应用。"""
        self._app = BlueArchiveApp(ctx, ctx.config)
        ctx.log.info("[image_factory] 已就绪：关键词 %r，张数上限 %d，8 步 DMD"
                     % (self._app.cfg.trigger, self._app.cfg.max_images))

    def teardown(self):
        """释放内核与应用资源。"""
        if self._app is not None:
            try:
                self._app.comfy.teardown()
            except Exception:
                pass
        self._app = None

    def route_qq(self, text, qq_context, nickname=""):
        """返回 True = 已接管；框架随后不再走主链路回复"""
        if self._app is None:
            return False
        ctx = dict(qq_context or {})
        if nickname:
            ctx.setdefault("nickname", nickname)
        try:
            return bool(self._app.handle(text, ctx))
        except Exception:
            self._app.log.exception("[image_factory] route_qq 异常")
            return False


PLUGIN = Plugin()
