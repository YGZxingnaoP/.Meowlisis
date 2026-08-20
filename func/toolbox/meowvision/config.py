# -*- coding: utf-8 -*-
# func/toolbox/meowvision/config.py
# MeowVision（视觉模块）全部配置项统一管理

import os

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBVisionConfig:
    """集中管理 meowvision 节点的全部配置项与默认值（视觉理解模型，仅阿里云平台）"""

    def __init__(self):
        cfg = ConfigReader().get('meowvision', {})

        # ========== 视觉理解模型（阿里云百炼 / MaaS，OpenAI 兼容） ==========
        # 独立 apikey，不与其它模块共用
        self.api_key = cfg.get('api_key', '')
        # 默认使用百炼 dashscope；若为专属工作空间，可改为
        # https://[workspace-id].cn-beijing.maas.aliyuncs.com/compatible-mode/v1
        self.base_url = cfg.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        # 默认 qvq-plus，可配置为 qvq-max 等
        self.model = cfg.get('model', 'qvq-plus')
        # 视觉回复最大 token，默认 512
        self.max_tokens = cfg.get('max_tokens', 512)
        self.temperature = cfg.get('temperature', 0.7)
        self.top_p = cfg.get('top_p', 0.9)

        # ========== 图片缓存 ==========
        # image_handle 工具产生的截图/裁切/编码结果统一缓存目录
        # NapCat 收到的图片也会先落到此目录，避免直接使用带鉴权的 url
        self.cache_dir = cfg.get('cache_dir', os.path.join('.temp', 'vision_cache'))
