class PluginRegistry:
    def __init__(self):
        """插件注册表：插件 / 触发型 / 接口型三张表"""
        self._plugins = {}
        self._triggers = {}
        self._interfaces = {}

    def add(self, plugin, ctx):
        """注册插件及其全部工具"""
        pid = getattr(plugin, "id", "") or ""
        if not pid:
            return
        self._plugins[pid] = (plugin, ctx)
        for tool in plugin.trigger_tools() or []:
            name = getattr(tool, "name", "") or ""
            if name:
                self._triggers[name] = (tool, ctx)
        for tool in plugin.interface_tools() or []:
            name = getattr(tool, "name", "") or ""
            if name:
                self._interfaces[name] = (tool, ctx)

    def plugin_ids(self):
        """返回已注册插件 id 列表"""
        return list(self._plugins.keys())

    def plugins(self):
        """返回已注册插件实例列表"""
        return [p for p, _ in self._plugins.values()]

    def triggers(self):
        """返回全部触发型工具"""
        return [t for t, _ in self._triggers.values()]

    def trigger_names(self):
        """返回全部触发型工具名"""
        return list(self._triggers.keys())

    def has_trigger(self, name):
        """判断触发型工具是否存在"""
        return name in self._triggers

    def trigger_schemas(self):
        """返回全部触发型工具 schema"""
        return [t.build_schema() for t in self.triggers()]

    def dispatch(self, name, arguments):
        """语音链路按名分发执行"""
        item = self._triggers.get(name)
        if not item:
            return None
        return item[0].handle(arguments or {}, item[1])

    def dispatch_qq(self, name, arguments, qq_context):
        """QQ 链路按名分发执行"""
        item = self._triggers.get(name)
        if not item:
            return None
        return item[0].handle_qq(arguments or {}, qq_context, item[1])

    def set_username(self, username):
        """向全部触发型工具注入用户名"""
        for tool, _ in self._triggers.values():
            tool.set_username(username)

    def set_context(self, context):
        """向全部触发型工具注入上下文"""
        for tool, _ in self._triggers.values():
            tool.set_context(context)

    def interface(self, name):
        """按名获取接口型工具"""
        item = self._interfaces.get(name)
        return item[0] if item else None

    def interface_names(self):
        """返回全部接口型工具名"""
        return list(self._interfaces.keys())

    def call(self, name, **kwargs):
        """按名调用接口型工具"""
        item = self._interfaces.get(name)
        if not item:
            return None
        return item[0].call(item[1], **kwargs)

    def prompt_hints(self):
        """汇总插件与触发型工具的引导文案"""
        hints = []
        for plugin, _ in self._plugins.values():
            text = (plugin.prompt_hint() or "").strip()
            if text:
                hints.append(text)
        for tool, _ in self._triggers.values():
            text = (getattr(tool, "prompt_hint", "") or "").strip()
            if text:
                hints.append(text)
        return hints
