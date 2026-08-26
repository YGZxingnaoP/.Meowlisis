# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/meowsongs_core.py
# meowsongs 触发型工具入口：父级浅层触发 → 即兴哼唱片段播放
from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig
from func.toolbox.meowsongs.impromptu_sing.impromptu_sing import TBImpromptuSing


@singleton
class TBMeowSongsCore:
    """即兴哼唱工具入口：analysis 只负责决定调用，输出由本模块负责"""

    TOOL_NAME = "impromptu_sing"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self._username = ""

    def set_username(self, username):
        self._username = username or ""

    def build_tools(self) -> List[Dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "用户想听你哼唱一段歌曲时调用。用户想听角色唱歌的时候调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "用户的哼唱需求原文",
                        },
                    },
                    "required": ["request"],
                },
            },
        }]

    def dispatch(self, name, arguments):
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        if not self.config.enabled:
            return "即兴哼唱未启用"
        request = (arguments or {}).get("request", "") or ""
        return TBImpromptuSing().run(request, self._username)

    def dispatch_qq(self, name, arguments, qq_context):
        """QQ 场景：本机播放 + 通过 NapCat 语音发送片段"""
        if name != self.TOOL_NAME or not self.config.enabled:
            return None
        request = (arguments or {}).get("request", "") or ""
        result = TBImpromptuSing().run(request, self._username, with_lyric=False)
        slice_path = TBImpromptuSing().last_slice_path
        if slice_path and qq_context:
            self._send_qq_voice(qq_context, slice_path, result)
        return result

    @staticmethod
    def _send_qq_voice(qq_context, slice_path, result):
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            core = TBNapCatCore()
            if str(qq_context.get("message_type", "")) == "group":
                core.send_group_voice(str(qq_context.get("target_id", "")), slice_path)
            else:
                core.send_private_voice(
                    str(qq_context.get("target_id", "") or qq_context.get("user_id", "")),
                    slice_path,
                )
        except Exception:
            pass
