# -*- coding: utf-8 -*-
# 企业级文件分析工具：目录文件列表（支持按修改时间排序）

import os
import datetime
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.catbrain.txt_reader.path_guard import MeowPathGuard


class MeowFileListTool:
    """文件列表工具：列出目录下的文件信息，可按修改时间从新到旧排序"""

    TOOL_NAME = "list_files"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.guard = MeowPathGuard()

    def run(self, directory: str, newest_first: bool = True) -> str:
        """列出目录文件（返回文件名+修改时间+大小，默认从新到旧）"""
        abs_dir = self.guard.resolve(directory)
        if not abs_dir or not os.path.isdir(abs_dir):
            return f"错误：目录不存在或不可访问: {directory}"
        items: List[Dict] = []
        for name in os.listdir(abs_dir):
            full = os.path.join(abs_dir, name)
            if os.path.isfile(full):
                st = os.stat(full)
                items.append({
                    "name": name,
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                })
        items.sort(key=lambda x: x["mtime"], reverse=newest_first)
        if not items:
            return f"目录为空: {directory}"
        lines = []
        for it in items:
            ts = datetime.datetime.fromtimestamp(it["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"{it['name']} | 修改时间:{ts} | 大小:{it['size']}B")
        return "\n".join(lines)

    def build_tool(self) -> Dict:
        """构建 function calling 工具定义"""
        return {
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "列出指定目录下的所有文件（含修改时间与大小），用于了解有哪些记忆文件可分析",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "目录路径，如 character/memory"},
                        "newest_first": {"type": "boolean", "description": "是否按修改时间从新到旧排序，默认true"}
                    },
                    "required": ["directory"]
                }
            }
        }
