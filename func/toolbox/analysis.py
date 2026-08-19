# -*- coding: utf-8 -*-
# func/toolbox/analysis.py
# 父级 toolcalls：注册触发型工具，由 AI 决策参数与 start

import json
from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig


class TBoxAnalysis:
    """父级 toolcalls 分析类：维护触发型工具注册表，AI 决策选择并开启工具"""

    TOOL_NAME = "use_tool"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self.llm = None
        self._tools = {}
        self._register_napcat_sender()

    def _register_napcat_sender(self):
        """注册 NapCat 主动发送触发模块（发送消息 / 发送文件）"""
        try:
            from func.toolbox.napcat.active_sender.sender import TBSender
            sender = TBSender()
            for tool_schema in sender.build_tools():
                name = tool_schema.get("function", {}).get("name")
                if name:
                    self.register(name, sender)
        except Exception:
            self.log.exception("注册 NapCat 主动发送工具失败")

    def _ensure_llm(self):
        """懒加载 toolbox 独立 LLM 客户端"""
        if self.llm is None:
            if self.config.llm_type == "aliyun":
                from func.toolbox.port.aliyun import TBoxAliyunLLM
                self.llm = TBoxAliyunLLM()
            else:
                from func.toolbox.port.deepseek import TBoxDeepSeekLLM
                self.llm = TBoxDeepSeekLLM()
        return self.llm

    def register(self, name: str, tool):
        """注册一个触发型工具到父级 toolcalls 注册表"""
        self._tools[name] = tool

    def build_tools(self) -> List[Dict]:
        """构建父级 toolcalls 工具定义（use_tool + 各注册工具的具体 schema）"""
        names = list(self._tools.keys())
        if names:
            tool_name_schema = {"type": "string", "enum": names}
        else:
            tool_name_schema = {"type": "string"}
        schemas = [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "根据用户意图选择一个已注册的触发型工具并开启使用",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            **tool_name_schema,
                            "description": "要开启的工具名称",
                        },
                        "arguments": {
                            "type": "object",
                            "description": "工具执行参数",
                        },
                        "start": {
                            "type": "boolean",
                            "description": "是否立即开启执行，默认 true",
                        },
                    },
                    "required": ["tool_name", "start"],
                },
            },
        }]
        # 合并各注册工具的具体 schema（同一工具对象只展开一次）
        seen_tools = set()
        for tool in self._tools.values():
            if id(tool) in seen_tools:
                continue
            seen_tools.add(id(tool))
            if hasattr(tool, "build_tools"):
                schemas.extend(tool.build_tools())
        return schemas

    def force_tool_choice(self) -> str:
        """构建强制使用父级工具的 tool_choice"""
        return "required"

    def decide(self, text: str, username: str):
        """接收输入内容，由 AI 决策调用哪个工具并开启（保留实现，后续完善）"""
        self.log.info(f"父级 toolcalls 决策待完善: username={username}, text={text[:50]}...")

    def dispatch(self, tool_name: str, arguments: Dict, start: bool):
        """按工具名与参数执行对应工具（保留实现，后续完善）"""
        tool = self._tools.get(tool_name)
        if not tool:
            return f"错误：未知工具 {tool_name}"
        if hasattr(tool, "dispatch"):
            return tool.dispatch(tool_name, arguments or {})
        return None
