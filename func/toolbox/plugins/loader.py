import importlib.util
import os
import sys


class PluginLoader:
    def __init__(self, root):
        """插件加载器：按目录发现并动态导入插件"""
        self.root = root

    def discover(self):
        """扫描插件目录，返回含 plugin.py 的插件 id 列表"""
        if not self.root or not os.path.isdir(self.root):
            return []
        ids = []
        for name in sorted(os.listdir(self.root)):
            if name.startswith("_") or name.startswith("."):
                continue
            path = os.path.join(self.root, name)
            if os.path.isdir(path) and os.path.isfile(os.path.join(path, "plugin.py")):
                ids.append(name)
        return ids

    def load(self, plugin_id):
        """导入单个插件并返回其实例"""
        path = os.path.join(self.root, plugin_id, "plugin.py")
        module_name = "meowplug_" + str(plugin_id)
        if self.root not in sys.path:
            sys.path.insert(0, self.root)
        spec = importlib.util.spec_from_file_location(
            module_name, path, submodule_search_locations=[os.path.dirname(path)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        plugin = getattr(module, "PLUGIN", None)
        if plugin is None:
            cls = getattr(module, "Plugin", None)
            if cls is not None:
                plugin = cls()
        return plugin
