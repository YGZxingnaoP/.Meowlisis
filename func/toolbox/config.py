# -*- coding: utf-8 -*-
# func/toolbox/config.py
# Toolbox 配置项统一管理（父级 toolcalls LLM 独立配置）

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBoxConfig:
    """集中管理 toolbox 节点的全部配置项与默认值（独立于其它模块）"""

    def __init__(self):
        cfg = ConfigReader().get('toolbox', {})

        # 父级 toolcalls LLM 后端类型：deepseek / aliyun
        self.llm_type = cfg.get('llm_type', 'deepseek')

        # DeepSeek 独立配置
        ds = cfg.get('deepseek', {})
        self.deepseek_api_key = ds.get('api_key', '')
        self.deepseek_base_url = ds.get('base_url', 'https://api.deepseek.com/v1')
        self.deepseek_model = ds.get('model', 'deepseek-chat')
        self.deepseek_temperature = ds.get('temperature', 0.7)
        self.deepseek_max_tokens = ds.get('max_tokens', 2048)

        # Aliyun 独立配置
        al = cfg.get('aliyun', {})
        self.aliyun_api_key = al.get('api_key', '')
        self.aliyun_base_url = al.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.aliyun_model = al.get('model', 'qwen-plus')
        self.aliyun_temperature = al.get('temperature', 0.7)
        self.aliyun_max_tokens = al.get('max_tokens', 2048)

        # ========== excuse 通用询问链路 ==========
        # 是否启用 excuse 阻塞等待（关闭则询问后不阻塞，直接返回）
        self.excuse_enabled = cfg.get('excuse_enabled', True)
        # excuse 等待用户文本输入超时（秒）
        self.excuse_timeout = cfg.get('excuse_timeout', 60)
