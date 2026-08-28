# -*- coding: utf-8 -*-
# func/llm_active/origin/vision/config.py
# 主动回复独立视觉模块配置：独立 api，不与 meowvision 共用

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class AutoVisionConfig:
    """集中管理 llm_active.vision 节点的配置项与默认值（仅阿里云平台）"""

    def __init__(self):
        cfg = ConfigReader().get('llm_active', {})
        vision = cfg.get('vision', {}) if isinstance(cfg, dict) else {}

        # ========== 视觉理解模型（独立 api，不复用 meowvision） ==========
        self.llm_type = vision.get('llm_type', 'aliyun')
        self.api_key = vision.get('api_key', '')
        self.base_url = vision.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        # 默认 qwen3.7-flash（阿里云多模态）
        self.model = vision.get('model', 'qwen3.7-flash')
        # 视觉回复最大 token：内容(≤300字) + 话题 + tags，预留余量
        self.max_tokens = vision.get('max_tokens', 600)
        self.temperature = vision.get('temperature', 0.7)
        self.top_p = vision.get('top_p', 0.9)

        # Gemini 视觉配置
        gemini = vision.get('gemini', {})
        self.gemini_api_key = gemini.get('api_key', '')
        self.gemini_base_url = gemini.get('base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/')
        self.gemini_model = gemini.get('model', 'gemini-3.6-flash')
        self.gemini_max_tokens = gemini.get('max_tokens', 600)
        self.gemini_temperature = gemini.get('temperature', 0.7)
        self.gemini_top_p = gemini.get('top_p', 0.9)
