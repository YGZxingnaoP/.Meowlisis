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
    """Toolbox 总入口：持有各 pipeline 桥接与父级分析器，统一分发"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self.analysis = TBoxAnalysis()
        self.get_prompt = TBoxGetPrompt()
        self.sensevoice_toolbox = SenseVoiceToolboxBridge()
        self.toolbox_tts = ToolboxTtsBridge()
        self.toolbox_ltmem = ToolboxLtMemBridge()
        self.toolbox_llm = ToolboxLLMBridge()

    def receive(self, text: str, username: str):
        """接收输入内容（来自 pipeline），交给 analysis 决策调用工具"""
        self.analysis.decide(text, username)
