# -*- coding: utf-8 -*-
# func/database/store/searching.py
# 从用户消息提取知识库检索 keys（tool_choice 强制调用，不思考）

import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.search.port import get_search_llm


@singleton
class CatLearnSearching:
    """知识库检索 keys 提取器（单例）

    - 从 database_core 获得用户信息（当前消息文本）；
    - 用 LLM tool_choice（不思考）提取针对性 keys；
    - 禁止输出过于宽泛的概念（游戏/战争/家庭等），找不到针对性索引则跳过。
    """

    TOOL_NAME = "extract_search_keys"

    def __init__(self):
        self.log = DefaultLog().getLogger()

    @classmethod
    def _build_tools(cls) -> list:
        return [{
            "type": "function",
            "function": {
                "name": cls.TOOL_NAME,
                "description": (
                    "从用户消息中提取用于知识库检索的针对性关键词。"
                    "必须专有名词优先、名称优先（如 原神、米哈游、Minecraft、某个人名/作品名）。"
                    "禁止输出过于宽泛的名词概念（如 游戏、战争、家庭、学习、技术）。"
                    "如果实在找不到有针对性的关键词，skip 填 true。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "针对性检索关键词列表（1~5 个）",
                        },
                        "skip": {
                            "type": "boolean",
                            "description": "找不到有针对性关键词时填 true",
                        },
                    },
                    "required": ["keys", "skip"],
                },
            },
        }]

    def extract_keys(self, text: str) -> list:
        """提取检索 keys，找不到针对性索引返回空列表（调用方应跳过检索）"""
        text = (text or "").strip()
        if not text:
            return []
        llm = get_search_llm()
        if llm is None or not llm.client:
            self.log.error("搜索模块 LLM 不可用，无法提取 keys")
            return []

        messages = [
            {
                "role": "system",
                "content": (
                    "你是知识库检索关键词提取器。只提取专有名词、名称，"
                    "禁止宽泛概念（游戏、战争、家庭、学习等）。找不到就跳过。"
                ),
            },
            {"role": "user", "content": text},
        ]
        resp = llm.chat(
            messages,
            tools=self._build_tools(),
            tool_choice={"type": "function", "function": {"name": self.TOOL_NAME}},
        )
        return self._parse(resp)

    def _parse(self, resp) -> list:
        if not resp or not getattr(resp, "choices", None):
            return []
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name != self.TOOL_NAME:
                    continue
                args = json.loads(tc.function.arguments or "{}")
                if args.get("skip"):
                    return []
                keys = args.get("keys") or []
                out = []
                for k in keys:
                    k = str(k).strip()
                    if k and k not in out:
                        out.append(k)
                return out[:5]
        except Exception:
            self.log.exception("解析检索 keys 失败")
        return []
