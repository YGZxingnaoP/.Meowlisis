# -*- coding: utf-8 -*-
# 企业级文件分析工具：文件截取（按字符区间）

import os
from typing import Dict

from func.log.default_log import DefaultLog
from func.catbrain.txt_reader.path_guard import MeowPathGuard


class MeowFileSliceTool:
    """文件截取工具：按字符偏移区间截取文件片段"""

    TOOL_NAME = "slice_file"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.guard = MeowPathGuard()

    def run(self, path: str, start: int = 0, length: int = 2000) -> str:
        """从字符偏移 start 开始截取 length 个字符"""
        abs_path = self.guard.resolve(path)
        if not abs_path or not os.path.isfile(abs_path):
            return f"错误：文件不存在或不可访问: {path}"
        if start < 0:
            start = 0
        if length <= 0:
            length = 2000
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            self.log.exception(f"截取文件失败: {path}")
            return f"错误：读取文件失败: {path}"
        total = len(content)
        if start >= total:
            return f"错误：起始偏移 {start} 超出文件总字符数 {total}"
        piece = content[start:start + length]
        header = f"[文件:{path} 字符{start}-{start + len(piece)}/共{total}字符]"
        return header + "\n" + piece

    def build_tool(self) -> Dict:
        """构建 function calling 工具定义"""
        return {
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "按字符偏移区间截取文件片段，用于读取大文件的某一段",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                        "start": {"type": "integer", "description": "起始字符偏移，默认0"},
                        "length": {"type": "integer", "description": "截取字符数，默认2000"}
                    },
                    "required": ["path"]
                }
            }
        }
