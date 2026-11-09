# -*- coding: utf-8 -*-
# func/pipeline/llm_toolbox.py

from func.log.default_log import DefaultLog

_SCHEMAS = None
_MEMORY_ANALYSIS = None


def _memory_analysis():
    """懒加载记忆文本阅读工具集合（txt_reader，已实现，不重复造）"""
    global _MEMORY_ANALYSIS
    if _MEMORY_ANALYSIS is None:
        from func.catbrain.txt_reader.file_analysis import MeowFileAnalysis
        _MEMORY_ANALYSIS = MeowFileAnalysis()
    return _MEMORY_ANALYSIS


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

    # ==================== 记忆文本阅读工具（导演规划用） ====================
    def get_memory_schemas(self):
        """记忆文本阅读工具的 schema（list_files / read_file / slice_file / keyword_locate / jieba_segment）"""
        try:
            return _memory_analysis().build_tools()
        except Exception:
            self.log.exception("获取记忆阅读工具定义失败")
            return []

    def dispatch_memory_tool(self, name: str, arguments):
        """执行记忆文本阅读工具，返回文本结果（arguments 为原始 JSON 字符串）"""
        try:
            return _memory_analysis().dispatch(name, arguments)
        except Exception:
            self.log.exception(f"记忆阅读工具执行失败: {name}")
            return f"错误：工具执行异常 {name}"

    def attach_tool_hint(self, system_prompt: str) -> str:
        hint = self.get_tool_hint()
        return f"{system_prompt}\n\n{hint}" if hint else system_prompt

    def pre_route_plan(self, text: str, username: str):
        try:
            return self._analysis().pre_route_plan(text, username)
        except Exception:
            self.log.exception("本地硬触发判断异常")
            return None

    def hard_trigger(self, name: str, arguments, username: str, text: str = ""):
        """本地规则硬触发：交给 analysis 走「工具触发态 → 角色裁决 → 派发」"""
        try:
            return self._analysis().hard_trigger(name, arguments, username, text)
        except Exception:
            self.log.exception(f"本地规则硬触发派发失败: {name}")
            return ""

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

    # ==================== 父级动作入口（导演主动触发用） ====================
    def entry_catalog(self):
        """父级动作入口目录（name + 一句说明）；只含模块级入口，不含子工具"""
        rows = []
        try:
            for schema in self.get_schemas():
                fn = schema.get("function") or {}
                name = str(fn.get("name") or "")
                if not name:
                    continue
                desc = str(fn.get("description") or "").strip().replace("\n", " ")
                rows.append({"name": name, "description": desc[:180]})
        except Exception:
            self.log.exception("获取父级入口目录失败")
        return rows

    def dispatch_entry(self, name: str, arguments, username: str, text: str = ""):
        """按父级入口名派发（导演主动触发）：只走模块级 dispatch，不碰子工具"""
        try:
            analysis = self._analysis()
            analysis.current_meowid = username
            short_memory = []
            try:
                from func.pipeline.short_memory import ShortMemory
                rows = ShortMemory().load()[-8:]
                short_memory = [{"role": m.get("role"), "content": m.get("content")}
                                for m in rows if m.get("content")]
            except Exception:
                short_memory = []
            try:
                from func.toolbox.get_prompt import TBoxGetPrompt
                system_prompt = TBoxGetPrompt().get_tool_prompt(username, text) or ""
            except Exception:
                system_prompt = ""
            context = {"meowid": username, "text": text,
                       "short_memory": short_memory, "system_prompt": system_prompt}
            return analysis.dispatch(name, arguments or {}, username, context)
        except Exception:
            self.log.exception(f"父级入口派发失败: {name}")
            return f"错误：工具执行异常 {name}"
