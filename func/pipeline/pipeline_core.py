# -*- coding: utf-8 -*-
# func/pipeline/pipeline_core.py
# Pipeline 集成入口，汇总所有模块间传递桥接

from func.pipeline.sensevoice_llm import SenseVoiceLLMBridge
from func.pipeline.llm_tts import LLMTtsBridge
from func.pipeline.system_prompt import SystemPromptBridge
from func.pipeline.llm_emotion import LLMEmotionBridge
from func.pipeline.danmuku_llm import DanmukuLLMBridge
from func.pipeline.sensevoice_tts import SenseVoiceTtsBridge
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.pipeline.llm_values import MeowLLMValuesBridge

__all__ = ['PipelineCore']


class PipelineCore:
    """Pipeline 集成入口，汇总所有模块间传递桥接"""

    def __init__(self):
        self.sensevoice_llm = SenseVoiceLLMBridge()
        self.llm_tts = LLMTtsBridge()
        self.system_prompt = SystemPromptBridge()
        self.llm_emotion = LLMEmotionBridge()
        self.danmuku_llm = DanmukuLLMBridge()
        self.sensevoice_tts = SenseVoiceTtsBridge()
        self.llm_ltmem = MeowLLMLtMemBridge()
        self.llm_values = MeowLLMValuesBridge()
