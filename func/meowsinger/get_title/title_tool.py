# -*- coding: utf-8 -*-
# func/meowsinger/get_title/title_tool.py
# 歌名提取工具定义与解析（function calling，非 tool_choice）
import json


class MeowTitleTool:
    """歌名提取工具：判断用户消息是否包含确定歌名"""

    TOOL_NAME = "extract_song_title"

    def build_tool(self):
        return {
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "从用户消息中提取要演唱或点播的歌曲名。"
                    "只有能确定具体歌名时才调用，歌名模糊或没有歌名时 has_song 填 false。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "has_song": {"type": "boolean", "description": "是否包含确定的歌名"},
                        "song_title": {"type": "string", "description": "确定的歌名，如 浪人琵琶、Avid"},
                    },
                    "required": ["has_song", "song_title"],
                },
            },
        }

    @staticmethod
    def parse(resp):
        if not resp or not getattr(resp, "choices", None):
            return None
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name != MeowTitleTool.TOOL_NAME:
                    continue
                args = json.loads(tc.function.arguments or "{}")
                if not args.get("has_song"):
                    return None
                title = str(args.get("song_title") or "").strip()
                return title or None
        except Exception:
            pass
        return None
