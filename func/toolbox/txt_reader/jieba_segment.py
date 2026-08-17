# -*- coding: utf-8 -*-
# func/tools/analysis/jieba_segment.py
# 企业级文件分析工具：jieba 中文分词

from typing import Dict, List

from func.log.default_log import DefaultLog


class MeowJiebaSegmentTool:
    """jieba 分词工具：对文本进行中文分词，用于语义分析辅助"""

    TOOL_NAME = "jieba_segment"

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def run(self, text: str, top_n: int = 30) -> str:
        """对文本分词并按词频返回前 N 个词"""
        if not text:
            return "错误：文本不能为空"
        try:
            import jieba.analyse
            words = jieba.analyse.extract_tags(text, topK=top_n, withWeight=True)
        except Exception:
            self.log.exception("jieba 分词失败")
            return "错误：分词失败"
        if not words:
            return "未提取到有效词语"
        return "、".join([f"{w}({round(s, 3)})" for w, s in words])

    def segment(self, text: str) -> List[str]:
        """普通分词接口（供检索相似度计算使用，过滤单字与空白）"""
        if not text:
            return []
        try:
            import jieba
            return [w for w in jieba.cut(text) if len(w.strip()) > 1]
        except Exception:
            self.log.exception("jieba 分词失败")
            return []

    def build_tool(self) -> Dict:
        """构建 function calling 工具定义"""
        return {
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "对一段文本进行中文分词并提取关键词（TF-IDF），用于理解记忆内容重点",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "要分词的文本"},
                        "top_n": {"type": "integer", "description": "返回的关键词数量，默认30"}
                    },
                    "required": ["text"]
                }
            }
        }
