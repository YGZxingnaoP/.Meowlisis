# -*- coding: utf-8 -*-
# func/llm_active/config.py
# 主动回复模块配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.llm.config import LLMConfig
from func.tools.singleton_mode import singleton


@singleton
class AutoActiveConfig:
    """集中管理 llm_active 节点的全部配置项与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('llm_active', {})

        # 空闲基础冷却时间（秒），实际等待 = cold_time * random(0.8, 1.2)
        self.cold_time = cfg.get('cold_time', 90)

        # 连续空闲触发阈值：<= n 次使用 inherit 策略，> n 次使用 origin 策略
        self.strategy_threshold = cfg.get('n', 1)

        # origin 记忆摘要检索条数上限
        self.origin_summary_limit = cfg.get('origin_summary_limit', 30)

        # origin 最近说话人最大数量
        self.origin_speaker_limit = cfg.get('origin_speaker_limit', 3)

        # 主动回复插播短期记忆兜底上限（条），尾部孤立时按此裁剪
        self.active_mem_limit = cfg.get('active_mem_limit', 50)

        # 复用 llm 的分段配置（origin 流式输出照搬 llm 分段逻辑）
        llm_cfg = ConfigReader().get('llm', {})
        split_flag = llm_cfg.get('split_flag', ',|，|。|!|！|?|？|\n')
        self.split_chars = [c.strip() for c in split_flag.split('|') if c.strip()]
        self.split_limit = llm_cfg.get('split_limit', 6)

        # 主动回复 LLM：复用 llm 后端类型与 apikey，max_tokens 为 llm 两倍且上限 2048
        llm = LLMConfig()
        self.llm_type = llm.local_llm_type
        base_max_tokens = llm.aliyun_max_tokens if self.llm_type == 'aliyun' else llm.deepseek_max_tokens
        self.max_tokens = min(base_max_tokens * 2, 2048)
