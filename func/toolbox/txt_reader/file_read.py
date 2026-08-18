# -*- coding: utf-8 -*-
# 企业级文件分析工具：文件读取（支持行范围）

import os
from typing import Dict

from func.log.default_log import DefaultLog
from func.toolbox.txt_reader.path_guard import MeowPathGuard


class MeowFileReadTool:
    """文件读取工具：按行范围读取文本文件内容"""

    TOOL_NAME = "read_file"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.guard = MeowPathGuard()

    def run(self, path: str, start_line: int = 1, end_line: int = 0) -> str:
        """读取文件指定行范围（end_line 为 0 表示读到末尾）"""
        abs_path = self.guard.resolve(path)
        if not abs_path or not os.path.isfile(abs_path):
            return f"错误：文件不存在或不可访问: {path}"
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            self.log.exception(f"读取文件失败: {path}")
            return f"错误：读取文件失败: {path}"
        total = len(lines)
        if start_line < 1:
            start_line = 1
        if end_line <= 0 or end_line > total:
            end_line = total
        if start_line > total:
            return f"错误：起始行 {start_line} 超出文件总行数 {total}"
        selected = lines[start_line - 1:end_line]
        header = f"[文件:{path} 第{start_line}-{end_line}行/共{total}行]"
        return header + "\n" + "".join(selected)

    def build_tool(self) -> Dict:
        """构建 function calling 工具定义"""
        return {
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "读取文本文件的指定行范围内容，用于分段阅读记忆文件",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径，如 character/memory/2024-01-01.txt"},
                        "start_line": {"type": "integer", "description": "起始行号（从1开始），默认1"},
                        "end_line": {"type": "integer", "description": "结束行号（包含），0表示读到末尾"}
                    },
                    "required": ["path"]
                }
            }
        }
