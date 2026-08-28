# -*- coding: utf-8 -*-
# func/toolbox/toolbox_core.py
# Toolbox 核心调度：整合 pipeline 桥接，统一分发输入与输出

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.config import TBoxConfig
from func.toolbox.analysis import TBoxAnalysis
from func.toolbox.get_prompt import TBoxGetPrompt
from func.pipeline.sensevoice_toolbox import SenseVoiceToolboxBridge
from func.pipeline.toolbox_tts import ToolboxTtsBridge
from func.pipeline.toolbox_ltmem import ToolboxLtMemBridge
from func.pipeline.toolbox_llm import ToolboxLLMBridge


@singleton
class TBoxCore:
    """Toolbox 总入口：持有主链路 pipeline 桥接与父级分析器，统一分发。

    QQ 回复链路已抽离至 func/toolbox/qq_response.py，此处仅保留转发入口。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self.analysis = TBoxAnalysis()
        self.get_prompt = TBoxGetPrompt()
        self.sensevoice_toolbox = SenseVoiceToolboxBridge()
        self.toolbox_tts = ToolboxTtsBridge()
        self.toolbox_ltmem = ToolboxLtMemBridge()
        self.toolbox_llm = ToolboxLLMBridge()
        # 视觉模块回传回调：视觉回复先回传 toolbox_core，再由其转发 TTS
        try:
            from func.toolbox.meowvision.vision_core import TBVisionCore
            TBVisionCore().set_reply_callback(self.forward_vision_reply)
        except Exception:
            self.log.exception("设置 MeowVision 回传回调失败")

    def receive(self, text: str, username: str):
        """接收输入内容（来自 pipeline），交给 analysis 决策调用工具。

        双通道：主 LLM 已快速回复，工具分析无工具时静默，避免重复回复。
        """
        self.analysis.decide(text, username)

    def forward_vision_reply(self, text: str):
        """接收 MeowVision 视觉模块回传的回复，通过 pipeline 转发给 TTS 合成（分段流式）"""
        self.toolbox_tts.send_stream(text, source="toolbox")

    # ==================== QQ 回复转发（逻辑已迁移至 func/toolbox/qq_response.py） ====================
    def receive_qq(self, username: str, user_id: str, text: str, short_memory: list):
        """QQ 私聊回复入口：转发至 TBoxQQResponse"""
        from func.toolbox.qq_response import TBoxQQResponse
        return TBoxQQResponse().receive_qq(username, user_id, text, short_memory)

    def receive_group(self, parsed: dict):
        """QQ 群聊回复入口：转发至 TBoxQQResponse"""
        from func.toolbox.qq_response import TBoxQQResponse
        return TBoxQQResponse().receive_group(parsed)

    def reply_group_at(self, buf: dict, text: str):
        """QQ 群聊 @ 缓冲回复入口：转发至 TBoxQQResponse"""
        from func.toolbox.qq_response import TBoxQQResponse
        return TBoxQQResponse().reply_group_at(buf, text)
