from func.toolbox.plugins.sdk import CHANNEL_QQ


class PluginRegistry:
    def __init__(self):
        self._plugins = {}
        self._triggers = {}
        self._interfaces = {}

    def add(self, plugin, ctx):
        pid = plugin.id
        triggers = plugin.trigger_tools()
        interfaces = plugin.interface_tools()
        self._plugins[pid] = (plugin, ctx, triggers, interfaces)
        for tool in triggers:
            self._triggers[tool.name] = (tool, ctx)
        for tool in interfaces:
            self._interfaces[tool.name] = (tool, ctx)

    def remove(self, pid):
        item = self._plugins.pop(pid, None)
        if item is None:
            return
        for tool in item[2]:
            self._triggers.pop(tool.name, None)
        for tool in item[3]:
            self._interfaces.pop(tool.name, None)

    def plugin_ids(self):
        return list(self._plugins)

    def plugins(self):
        return [item[0] for item in self._plugins.values()]

    def triggers(self):
        return [tool for tool, _ in self._triggers.values()]

    def trigger_names(self):
        return list(self._triggers)

    def has_trigger(self, name):
        return name in self._triggers

    def trigger_schemas(self, channel=None):
        return [tool.build_schema() for tool, _ in self._triggers.values()
                if channel is None or channel in tool.channels]

    def dispatch(self, name, arguments):
        item = self._triggers.get(name)
        if item is None:
            return None
        return item[0].handle(arguments or {}, item[1])

    def dispatch_qq(self, name, arguments, qq_context):
        item = self._triggers.get(name)
        if item is None:
            return None
        tool, ctx = item
        if CHANNEL_QQ not in tool.channels:
            return None
        return tool.handle_qq(arguments or {}, qq_context, ctx)

    def interface(self, name):
        item = self._interfaces.get(name)
        return item[0] if item else None

    def interface_names(self):
        return list(self._interfaces)

    def call(self, name, **kwargs):
        item = self._interfaces.get(name)
        if item is None:
            return None
        return item[0].call(item[1], **kwargs)

    def prompt_hints(self):
        hints = []
        for item in self._plugins.values():
            text = (item[0].prompt_hint() or "").strip()
            if text:
                hints.append(text)
        for tool, _ in self._triggers.values():
            text = (tool.prompt_hint or "").strip()
            if text:
                hints.append(text)
        return hints
