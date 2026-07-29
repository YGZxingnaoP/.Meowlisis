# -*- coding: utf-8 -*-
# func/pipeline/pipeline_core.py
# Pipeline 集成文件，汇总所有模块间传递桥接

from func.pipeline.llm_memory import LLMMemoryBridge
from func.pipeline.llm_tts import LLMTtsBridge
from func.pipeline.sensevoice_llm import SenseVoiceLLMBridge
from func.pipeline.memory_llm import MemoryLLMBridge

__all__ = ['PipelineCore']


class PipelineCore:
    """Pipeline 集成入口，汇总所有模块间传递桥接"""

    def __init__(self):
        self.llm_memory = LLMMemoryBridge()
        self.llm_tts = LLMTtsBridge()
        self.sensevoice_llm = SenseVoiceLLMBridge()
        self.memory_llm = MemoryLLMBridge()
