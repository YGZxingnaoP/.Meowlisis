# -*- coding: utf-8 -*-
# func/pipeline/llm_toolbox.py

from func.log.default_log import DefaultLog

_SCHEMAS = None


class ToolCallAccumulator:
    def __init__(self):
        self._calls = {}

    def add(self, delta_tool_calls):
        for tc in delta_tool_calls:
            idx = tc.index
            if idx not in self._calls:
                self._calls[idx] = {"id": "", "name": "", "arguments": ""}
            if tc.id:
                self._calls[idx]["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    self._calls[idx]["name"] = tc.function.name
                if tc.function.arguments:
                    self._calls[idx]["arguments"] += tc.function.arguments

    def has_calls(self) -> bool:
        return any(c["name"] for c in self._calls.values())

    def payload(self):
        out = []
        for idx in sorted(self._calls.keys()):
            c = self._calls[idx]
            if not c["name"]:
                continue
            out.append({
                "id": c["id"] or f"call_{idx}",
                "type": "function",
                "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
            })
        return out


class LLMToolboxBridge:
    def __init__(self):
        self.log = DefaultLog().getLogger()

    def merge_enabled(self) -> bool:
        try:
            from func.toolbox.config import TBoxConfig
            return bool(TBoxConfig().fast_reply_direct_tool)
        except Exception:
            return False

    def _analysis(self):
        from func.toolbox.toolbox_core import TBoxCore
        return TBoxCore().analysis

    def get_schemas(self):
        global _SCHEMAS
        if _SCHEMAS is None:
            try:
                _SCHEMAS = self._analysis().build_tools()
            except Exception:
                self.log.exception("获取 toolbox 工具定义失败")
                return []
        return _SCHEMAS

    def get_tool_hint(self) -> str:
        try:
            from func.toolbox.plugins.manager import PluginManager
            plugin_hint = PluginManager().prompt_hint()
        except Exception:
            plugin_hint = ""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_tool_hint_prompt(plugin_hint)
        except Exception:
            self.log.exception("获取工具决策前置词失败")
            return ""

    def attach_tool_hint(self, system_prompt: str) -> str:
        hint = self.get_tool_hint()
        return f"{system_prompt}\n\n{hint}" if hint else system_prompt

    def pre_route_plan(self, text: str, username: str):
        try:
            return self._analysis().pre_route_plan(text, username)
        except Exception:
            self.log.exception("本地硬触发判断异常")
            return None

    def pre_route(self, text: str, username: str) -> bool:
        try:
            return bool(self._analysis().pre_route(text, username))
        except Exception:
            self.log.exception("本地硬触发异常")
            return False

    def dispatch(self, name: str, arguments: dict, username: str = None, context: dict = None):
        return self._analysis().dispatch(name, arguments, username, context)

    def handle_tool_calls(self, calls, username: str, text: str = ""):
        norm = []
        for c in (calls or []):
            fn = c.get("function") or {}
            name = fn.get("name") or c.get("name") or ""
            if name:
                # 保留 tool_call_id：QQ 链路内部子工具循环要把结果作为 role=tool
                # 回灌给模型，缺 id 会被 OpenAI 兼容接口直接拒绝。
                norm.append({"id": c.get("id") or "",
                             "name": name,
                             "arguments": fn.get("arguments", c.get("arguments"))})
        return self._analysis().handle_tool_calls(norm, username, text)
