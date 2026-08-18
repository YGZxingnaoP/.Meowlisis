# -*- coding: utf-8 -*-
# 企业级文件分析工具：关键词定位（返回行号与上下文）

import os
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.toolbox.txt_reader.path_guard import MeowPathGuard


class MeowKeywordLocateTool:
    """关键词定位工具：在文件中搜索关键词并返回命中行号与上下文"""

    TOOL_NAME = "keyword_locate"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.guard = MeowPathGuard()

    def run(self, path: str, keyword: str, context_lines: int = 1, max_hits: int = 20) -> str:
        """搜索关键词，返回每个命中位置的行号、行内容与上下文"""
        abs_path = self.guard.resolve(path)
        if not abs_path or not os.path.isfile(abs_path):
            return f"错误：文件不存在或不可访问: {path}"
        if not keyword:
            return "错误：关键词不能为空"
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            self.log.exception(f"关键词定位失败: {path}")
            return f"错误：读取文件失败: {path}"
        hits: List[str] = []
        for idx, line in enumerate(lines):
            if keyword in line:
                start = max(0, idx - context_lines)
                end = min(len(lines), idx + context_lines + 1)
                block = "".join(lines[start:end]).rstrip("\n")
                hits.append(f"第{idx + 1}行:\n{block}")
                if len(hits) >= max_hits:
                    break
        if not hits:
            return f"未找到关键词「{keyword}」: {path}"
        return f"[文件:{path} 关键词「{keyword}」命中{len(hits)}处]\n" + "\n---\n".join(hits)

    def build_tool(self) -> Dict:
        """构建 function calling 工具定义"""
        return {
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "在文件中搜索关键词，返回命中行号与上下文，用于快速定位相关记忆",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                        "keyword": {"type": "string", "description": "要搜索的关键词"},
                        "context_lines": {"type": "integer", "description": "命中行前后附加的上下文行数，默认1"},
                        "max_hits": {"type": "integer", "description": "最多返回的命中数，默认20"}
                    },
                    "required": ["path", "keyword"]
                }
            }
        }
