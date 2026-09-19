import os

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.plugins.loader import PluginLoader
from func.toolbox.plugins.registry import PluginRegistry
from func.toolbox.plugins.sdk import PluginContext


class _TriggerAdapter:
    def __init__(self, manager):
        """触发型工具适配器：对接现有模块入口约定"""
        self.manager = manager

    def build_tools(self):
        """返回全部插件触发型工具 schema"""
        return self.manager.trigger_schemas()

    def dispatch(self, name, arguments):
        """按工具名执行语音链路"""
        return self.manager.dispatch(name, arguments)

    def dispatch_qq(self, name, arguments, qq_context):
        """按工具名执行 QQ 链路"""
        return self.manager.dispatch_qq(name, arguments, qq_context)

    def set_username(self, username):
        """注入当前用户名"""
        self.manager.set_username(username)

    def set_context(self, context):
        """注入调用上下文"""
        self.manager.set_context(context)


@singleton
class PluginManager:
    def __init__(self):
        """插件管理器：启动加载、注册到分析链路、统一分发"""
        self.log = DefaultLog().getLogger()
        self.registry = PluginRegistry()
        self._loaded = False
        self._adapter = _TriggerAdapter(self)

    def _config(self):
        """读取 plugins 配置节点"""
        try:
            from func.pipeline.config_reader import ConfigReader
            return ConfigReader().get("plugins", {}) or {}
        except Exception:
            return {}

    def load_all(self):
        """按配置加载全部插件"""
        if self._loaded:
            return
        self._loaded = True
        cfg = self._config()
        if not cfg.get("enabled", True):
            self.log.info("插件系统未启用")
            return
        if not cfg.get("auto_load", True):
            return
        root = cfg.get("dir", "./plugins")
        if not os.path.isabs(root):
            root = os.path.join(os.getcwd(), root)
        from func.toolbox.plugins import schema_io
        disabled = set(cfg.get("disabled", []) or [])
        loader = PluginLoader(root)
        for pid in loader.discover():
            if pid in disabled:
                continue
            try:
                plugin = loader.load(pid)
                if plugin is None:
                    self.log.warning(f"插件未导出实例: {pid}")
                    continue
                pdir = os.path.join(root, pid)
                pcfg = schema_io.ensure_config(pdir)
                if not pcfg.get("enabled", getattr(plugin, "default_enabled", True)):
                    self.log.info(f"插件已关闭: {pid}")
                    continue
                ctx = PluginContext(pid, self.log, pcfg)
                plugin.setup(ctx)
                self.registry.add(plugin, ctx)
                self.log.info(f"插件已加载: {pid}")
            except Exception:
                self.log.exception(f"加载插件失败: {pid}")
                if cfg.get("fail_fast", False):
                    raise

    def _ensure(self):
        """确保插件已加载"""
        if not self._loaded:
            self.load_all()

    def adapter(self):
        """返回触发型工具适配器"""
        self._ensure()
        return self._adapter

    def register_into(self, target):
        """把触发型工具注册到目标分析器"""
        self._ensure()
        for name in self.registry.trigger_names():
            target.register(name, self._adapter)

    def trigger_schemas(self):
        """返回全部触发型工具 schema"""
        self._ensure()
        return self.registry.trigger_schemas()

    def has_trigger(self, name):
        """判断是否为插件触发型工具"""
        self._ensure()
        return self.registry.has_trigger(name)

    def dispatch(self, name, arguments):
        """语音链路分发"""
        self._ensure()
        return self.registry.dispatch(name, arguments)

    def dispatch_qq(self, name, arguments, qq_context):
        """QQ 链路分发"""
        self._ensure()
        return self.registry.dispatch_qq(name, arguments, qq_context)

    def set_username(self, username):
        """注入当前用户名"""
        self._ensure()
        self.registry.set_username(username)

    def set_context(self, context):
        """注入调用上下文"""
        self._ensure()
        self.registry.set_context(context)

    def call_interface(self, name, **kwargs):
        """按名调用接口型工具"""
        self._ensure()
        return self.registry.call(name, **kwargs)

    def prompt_hint(self):
        """汇总插件引导文案"""
        self._ensure()
        hints = self.registry.prompt_hints()
        if not hints:
            return ""
        return "【插件工具】\n" + "\n".join(hints)

    def list_plugins(self):
        """返回已加载插件 id 列表"""
        self._ensure()
        return self.registry.plugin_ids()

    def state_decl(self, plugin_id):
        """取插件声明的能力位（标准接口 state_decl()）；无声明返回 {}"""
        self._ensure()
        try:
            for plugin in self.registry.plugins():
                if getattr(plugin, "id", "") == plugin_id:
                    decl = getattr(plugin, "state_decl", None)
                    return (decl() if callable(decl) else {}) or {}
        except Exception:
            self.log.exception("读取插件状态声明失败")
        return {}

    def match_keyword(self, text):
        """关键词硬触发：返回 (工具名, 参数) 或 None"""
        self._ensure()
        text = str(text or "")
        if not text:
            return None
        for tool in self.registry.triggers():
            words = getattr(tool, "trigger_words", None) or ()
            for word in words:
                if word and word in text:
                    return getattr(tool, "name", ""), {"request": text}
        return None

    def route_text(self, text, username=""):
        """会话拦截：交给声明了 route_text 的触发型工具，命中返回 True"""
        self._ensure()
        for tool in self.registry.triggers():
            handler = getattr(tool, "route_text", None)
            if not callable(handler):
                continue
            try:
                if handler(text, username):
                    return True
            except Exception:
                self.log.exception("插件会话拦截失败")
        return False
