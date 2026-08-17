# -*- coding: utf-8 -*-
# func/catbrain/CatValues/port/review.py
# 价值观二次审查端口：按配置创建另一平台的大模型客户端

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.CatValues.port.deepseek import MeowValuesDeepSeekLLM
from func.catbrain.CatValues.port.aliyun import MeowValuesAliyunLLM


class MeowValuesReviewLLM:
    """二次审查客户端工厂：根据 second_review 配置创建另一平台的 LLM"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.client = None
        self._inner = self._create()
        if self._inner:
            self.client = self._inner.client

    def _create(self):
        """按配置创建二次审查 LLM（覆盖对应平台的 apikey/base_url/model）"""
        llm_type = self.config.values_second_review_llm_type
        if llm_type == "aliyun":
            llm = MeowValuesAliyunLLM()
            llm.api_key = self.config.val_sr_aliyun_api_key
            llm.base_url = self.config.val_sr_aliyun_base_url
            llm.model = self.config.val_sr_aliyun_model
        else:
            llm = MeowValuesDeepSeekLLM()
            llm.api_key = self.config.val_sr_deepseek_api_key
            llm.base_url = self.config.val_sr_deepseek_base_url
            llm.model = self.config.val_sr_deepseek_model
        # 覆盖后需要重建客户端
        if llm.api_key:
            try:
                from openai import OpenAI
                llm.client = OpenAI(api_key=llm.api_key, base_url=llm.base_url)
            except Exception as e:
                self.log.error(f"初始化二次审查客户端失败: {e}")
                llm.client = None
        else:
            self.log.error("二次审查 API Key 未配置")
            llm.client = None
        return llm

    def chat(self, messages, tools=None, tool_choice=None):
        """非流式对话，转发到内部客户端"""
        if not self._inner:
            return None
        return self._inner.chat(messages, tools=tools, tool_choice=tool_choice)
