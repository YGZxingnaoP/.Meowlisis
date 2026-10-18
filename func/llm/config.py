# -*- coding: utf-8 -*-
# func/llm/config.py
# LLM 配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class LLMConfig:
    """集中管理 llm 节点的全部配置项与默认值（仿 SenseVoiceConfig）"""

    def __init__(self):
        # 从配置总线读取 llm 配置节点，缺失时回退到空字典
        cfg = ConfigReader().get('llm', {})

        # ========== 模型类型 ==========
        # 当前仅支持 deepseek / aliyun 两种流式后端
        self.local_llm_type = cfg.get('local_llm_type', 'deepseek')

        # ========== 短期记忆 ==========
        # 短期记忆保留的对话轮数（1 轮 = 1 次用户消息 + 1 次助手回复）
        self.short_term_rounds = cfg.get('short_term_rounds', 60)

        # ========== 输出分段 ==========
        # 分段标点列表与最小分段长度
        split_flag = cfg.get('split_flag', ',|，|。|!|！|?|？|\n')
        self.split_chars = [c.strip() for c in split_flag.split('|') if c.strip()]
        self.split_limit = cfg.get('split_limit', 6)

        # ========== message_get 正则替换规则 ==========
        # 用于清洗 SenseVoice 识别结果（如错别字纠正），键为匹配模式，值为替换内容
        # 后续在 config.yml 中新增 llm.message_replace_rules 节点即可覆盖
        self.message_replace_rules = cfg.get('message_replace_rules', {
            "喵屋": "喵呜",
            "猫屋": "喵呜",
        })

        # ========== DeepSeek 配置 ==========
        deepseek_cfg = cfg.get('deepseek', {})
        self.deepseek_api_key = deepseek_cfg.get('api_key', '')
        self.deepseek_base_url = deepseek_cfg.get('base_url', 'https://api.deepseek.com/v1')
        self.deepseek_model = deepseek_cfg.get('model', 'deepseek-chat')
        self.deepseek_temperature = deepseek_cfg.get('temperature', 0.7)
        self.deepseek_max_tokens = deepseek_cfg.get('max_tokens', 1024)
        self.deepseek_top_p = deepseek_cfg.get('top_p', 0.9)
        self.deepseek_stream = deepseek_cfg.get('stream', True)
        self.deepseek_enable_thinking = deepseek_cfg.get('enable_thinking', False)

        # ========== Aliyun 配置 ==========
        aliyun_cfg = cfg.get('aliyun', {})
        self.aliyun_api_key = aliyun_cfg.get('api_key', '')
        self.aliyun_base_url = aliyun_cfg.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.aliyun_model = aliyun_cfg.get('model', 'qwen-plus')
        self.aliyun_temperature = aliyun_cfg.get('temperature', 0.7)
        self.aliyun_max_tokens = aliyun_cfg.get('max_tokens', 1024)
        self.aliyun_top_p = aliyun_cfg.get('top_p', 0.9)
        self.aliyun_stream = aliyun_cfg.get('stream', True)
        self.aliyun_enable_thinking = aliyun_cfg.get('enable_thinking', False)

        # ========== Gemini 配置 ==========
        gemini_cfg = cfg.get('gemini', {})
        self.gemini_api_key = gemini_cfg.get('api_key', '')
        self.gemini_base_url = gemini_cfg.get('base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/')
        self.gemini_model = gemini_cfg.get('model', 'gemini-3.6-flash')
        self.gemini_temperature = gemini_cfg.get('temperature', 0.7)
        self.gemini_max_tokens = gemini_cfg.get('max_tokens', 1024)
        self.gemini_top_p = gemini_cfg.get('top_p', 0.9)
        self.gemini_stream = gemini_cfg.get('stream', True)

        # ========== MeowLLM（本地/自建，OpenAI 兼容）==========
        # 与 deepseek / aliyun / gemini 完全并列。端点由启动器回写，
        # 各模块统一从根 llm.meowllm 读（加载的是同一个 config.yml）。
        meowllm_cfg = cfg.get('meowllm') or llm_cfg.get('meowllm') or {}
        self.meowllm_base_url = meowllm_cfg.get(
            'base_url', 'http://127.0.0.1:18100/meowllm/v1')
        self.meowllm_model = meowllm_cfg.get('model', 'meowllm-local')
        self.meowllm_temperature = meowllm_cfg.get('temperature', 0.8)
        self.meowllm_max_tokens = int(meowllm_cfg.get('max_tokens', 256))
        self.meowllm_top_p = meowllm_cfg.get('top_p', 0.9)
        self.meowllm_top_k = int(meowllm_cfg.get('top_k', 40))
        self.meowllm_repeat_penalty = float(meowllm_cfg.get('repeat_penalty', 1.05))
        # 注意 YAML 的坑：裸写 `off` / `on` / `yes` / `no` 会被解析成布尔。
        # 这里做一次归一，配置里写加引号的 "off" 或直接写 false 都能用。
        _level = meowllm_cfg.get('thinking_level', 'off')
        if _level is False or _level is None:
            _level = 'off'
        elif _level is True:
            _level = 'medium'
        self.meowllm_thinking_level = str(_level)
        # 兼容旧名（llm_active 用它算主动回复长度上限）
        self.meowllm_talk_max_tokens = self.meowllm_max_tokens
        self.gemini_enable_thinking = gemini_cfg.get('enable_thinking', False)
