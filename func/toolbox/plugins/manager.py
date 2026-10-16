import importlib
import os
import sys

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.plugins.loader import PluginLoader
from func.toolbox.plugins.registry import PluginRegistry
from func.toolbox.plugins.sdk import (CHANNEL_MAIN, PluginContext, begin_request,
                                      update_request)


class _TriggerAdapter:
    def __init__(self, manager):
        self.manager = manager

    def build_tools(self):
        return self.manager.trigger_schemas(CHANNEL_MAIN)

    def dispatch(self, name, arguments):
        return self.manager.dispatch(name, arguments)

    def dispatch_qq(self, name, arguments, qq_context):
        return self.manager.dispatch_qq(name, arguments, qq_context)

    def set_meowid(self, meowid):
        begin_request(meowid)

    def set_context(self, context):
        update_request(**(context or {}))


@singleton
class PluginManager:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.registry = PluginRegistry()
        self._loaded = False
        self._adapter = _TriggerAdapter(self)

    def _config(self):
        from func.pipeline.config_reader import ConfigReader
        return ConfigReader().get("plugins", {}) or {}

    def load_all(self):
        if self._loaded:
            return
        self._loaded = True
        cfg = self._config()
        if not cfg.get("enabled", True) or not cfg.get("auto_load", True):
            return
        root = cfg.get("dir", "./plugins")
        if not os.path.isabs(root):
            root = os.path.join(os.getcwd(), root)
        disabled = set(cfg.get("disabled", []) or [])
        self._root = root
        for pid in PluginLoader(root).discover():
            if pid not in disabled:
                self._load_one(root, pid)

    def _load_one(self, root, pid):
        from func.toolbox.plugins import schema_io
        loader = PluginLoader(root)
        plugin = loader.load(pid)
        if plugin is None:
            self.log.warning(f"插件未导出实例: {pid}")
            return
        pcfg = schema_io.ensure_config(os.path.join(root, pid))
        if not pcfg.get("enabled", plugin.default_enabled):
            self.log.info(f"插件已关闭: {pid}")
            return
        ctx = PluginContext(pid, self.log, pcfg)
        plugin.setup(ctx)
        self.registry.add(plugin, ctx)
        self.log.info(f"插件已加载: {pid}")

    def _ensure(self):
        if not self._loaded:
            self.load_all()

    def reload(self, pid):
        self._ensure()
        item = self.registry._plugins.get(pid)
        if item is not None:
            item[0].teardown()
            self.registry.remove(pid)
        for name in ("meowplug_", "meowschema_"):
            sys.modules.pop(name + pid, None)
        importlib.invalidate_caches()
        self._load_one(self._root, pid)

    def adapter(self):
        self._ensure()
        return self._adapter

    def register_into(self, target):
        self._ensure()
        for name in self.registry.trigger_names():
            target.register(name, self._adapter)

    def trigger_schemas(self, channel=None):
        self._ensure()
        return self.registry.trigger_schemas(channel)

    def has_trigger(self, name):
        self._ensure()
        return self.registry.has_trigger(name)

    def dispatch(self, name, arguments):
        self._ensure()
        return self.registry.dispatch(name, arguments)

    def dispatch_qq(self, name, arguments, qq_context):
        self._ensure()
        return self.registry.dispatch_qq(name, arguments, qq_context)

    def call_interface(self, name, **kwargs):
        self._ensure()
        return self.registry.call(name, **kwargs)

    def prompt_hint(self):
        self._ensure()
        hints = self.registry.prompt_hints()
        return ("【插件工具】\n" + "\n".join(hints)) if hints else ""

    def list_plugins(self):
        self._ensure()
        return self.registry.plugin_ids()

    def state_decl(self, plugin_id):
        self._ensure()
        for plugin in self.registry.plugins():
            if plugin.id == plugin_id:
                decl = getattr(plugin, "state_decl", None)
                return decl() if callable(decl) else {}
        return {}

    def match_keyword(self, text):
        self._ensure()
        text = str(text or "")
        for tool in self.registry.triggers():
            for word in (tool.trigger_words or ()):
                if word and word in text:
                    return tool.name, {"request": text}
        return None

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        self._ensure()
        text = str(text or "")
        if not text.strip():
            return False
        for tool in self.registry.triggers():
            if channel not in tool.channels:
                continue
            if tool.route_text(text, meowid, channel):
                return True
        return False

    def route_qq(self, channel, text, qq_context=None, nickname=""):
        self._ensure()
        text = str(text or "")
        if not text.strip():
            return False
        for plugin in self.registry.plugins():
            handler = getattr(plugin, "route_qq", None)
            if not callable(handler):
                continue
            if handler(text, dict(qq_context or {}), str(nickname or "")):
                self.log.info(f"[插件] {plugin.id} 接管 {channel}: {text[:30]}")
                return True
        return False
