# -*- coding: utf-8 -*-
# 企业级文件分析工具集合：统一注册与分发（供价值观更新等模块的 LLM 工具调用）

import json
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.toolbox.txt_reader.file_list import MeowFileListTool
from func.toolbox.txt_reader.file_read import MeowFileReadTool
from func.toolbox.txt_reader.file_slice import MeowFileSliceTool
from func.toolbox.txt_reader.keyword_locate import MeowKeywordLocateTool
from func.toolbox.txt_reader.jieba_segment import MeowJiebaSegmentTool


class MeowFileAnalysis:
    """文件分析工具集合：聚合各文件工具并提供统一的 tools 定义与执行分发"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.file_list = MeowFileListTool()
        self.file_read = MeowFileReadTool()
        self.file_slice = MeowFileSliceTool()
        self.keyword_locate = MeowKeywordLocateTool()
        self.jieba_segment = MeowJiebaSegmentTool()
        # 工具名 → 工具实例的映射（供分发使用）
        self._tools = {
            self.file_list.TOOL_NAME: self.file_list,
            self.file_read.TOOL_NAME: self.file_read,
            self.file_slice.TOOL_NAME: self.file_slice,
            self.keyword_locate.TOOL_NAME: self.keyword_locate,
            self.jieba_segment.TOOL_NAME: self.jieba_segment,
        }

    def build_tools(self) -> List[Dict]:
        """构建全部文件分析工具的 tools 定义"""
        return [t.build_tool() for t in self._tools.values()]

    def dispatch(self, name: str, arguments: str) -> str:
        """按工具名与 JSON 参数执行对应工具，返回文本结果"""
        tool = self._tools.get(name)
        if not tool:
            return f"错误：未知工具 {name}"
        try:
            args = json.loads(arguments) if arguments else {}
        except Exception:
            return f"错误：工具参数不是合法 JSON: {arguments}"
        try:
            return tool.run(**args)
        except TypeError as e:
            return f"错误：工具参数不匹配: {e}"
        except Exception:
            self.log.exception(f"文件分析工具执行失败: {name}")
            return f"错误：工具执行异常: {name}"
