# -*- coding: utf-8 -*-
# func/database/config.py
# database 模块全部配置项统一管理（类名 CatLearn 前缀）

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class CatLearnConfig:
    """集中管理 config.yml database 节点的全部配置项与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('database', {})

        # ========== 聊天记录（alluser_record） ==========
        record = cfg.get('record', {})
        # 累计多少条 user 消息后滚动一轮（并触发核心 search 决策）
        self.record_max_messages = int(record.get('max_messages', 50))
        # 保留轮数（last / past_1 / ...），默认 2
        self.record_rounds = int(record.get('rounds', 2))

        # ========== 关键词匹配 ==========
        match = cfg.get('match', {})
        self.search_keywords = match.get('search_keywords', ['搜索', '搜搜', '搜一下', '搜', '查一下']) or []
        self.know_keywords = match.get('know_keywords', ['知道', '了解', '听说过', '听过', '认识']) or []
        # 否定词（优先级最高，命中则拦截正向匹配）
        self.neg_keywords = match.get('neg_keywords', ['知道了', '不知道', '不了解', '没听说过', '没听过', '不认识']) or []

        # ========== search 模块 LLM ==========
        s = cfg.get('search', {})
        self.search_llm_type = s.get('llm_type', 'deepseek')
        self.search_temperature = s.get('temperature', 0.7)

        sds = s.get('deepseek', {})
        self.search_deepseek_api_key = sds.get('api_key', '')
        self.search_deepseek_base_url = sds.get('base_url', 'https://api.deepseek.com/v1')
        self.search_deepseek_model = sds.get('model', 'deepseek-chat')
        self.search_deepseek_max_tokens = sds.get('max_tokens', 2048)

        sal = s.get('aliyun', {})
        self.search_aliyun_api_key = sal.get('api_key', '')
        self.search_aliyun_base_url = sal.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.search_aliyun_model = sal.get('model', 'qwen-plus')
        self.search_aliyun_max_tokens = sal.get('max_tokens', 2048)

        # ========== search Agent 配置 ==========
        agent = s.get('agent', {}) or {}
        # 单 task 工具调用最大轮数（AI 一直调工具时强制结束）
        self.agent_max_rounds = int(agent.get('max_rounds', 5))
        # visit_url 单次回传正文截断长度（字符）
        self.agent_visit_max_chars = int(agent.get('visit_max_chars', 8000))

        # ========== search 站点配置 ==========
        # site_key -> {strategy, count, base_url}
        self.sites = {}
        sites = s.get('sites', {}) or {}
        for site_key, site_cfg in sites.items():
            if not isinstance(site_cfg, dict):
                continue
            self.sites[str(site_key)] = {
                'label': site_cfg.get('label', str(site_key)),
                'description': site_cfg.get('description', ''),
                'enabled': site_cfg.get('enabled', True),
                'strategy': site_cfg.get('strategy', 'http'),
                'count': int(site_cfg.get('count', 5)),
                'base_url': site_cfg.get('base_url', ''),
                'search_url': site_cfg.get('search_url', ''),
                'interval': float(site_cfg.get('interval', 2)),
            }

        # ========== store 模块 ==========
        st = cfg.get('store', {})
        emb = st.get('embedding', {})
        # 向量引擎：aliyun（DashScope qwen3.7-text-embedding）或 siliconflow（BAAI/bge-m3）
        self.embedding_provider = str(emb.get('provider', 'siliconflow')).strip().lower()
        # 阿里云 DashScope 文本向量（qwen3.7-text-embedding）
        ali = emb.get('aliyun', {}) or {}
        self.embedding_aliyun_api_key = ali.get('api_key', '')
        self.embedding_aliyun_base_url = ali.get('base_url', 'https://dashscope.aliyuncs.com/api/v1')
        self.embedding_aliyun_model = ali.get('model', 'qwen3.7-text-embedding')
        # 硅基流动文本向量（BAAI/bge-m3）
        sfs = emb.get('siliconflow', {}) or {}
        # 兼容旧的扁平配置（api_key / base_url / model 直接放在 embedding 下）
        self.embedding_api_key = sfs.get('api_key', emb.get('api_key', ''))
        self.embedding_base_url = sfs.get('base_url', emb.get('base_url', 'https://api.siliconflow.cn/v1'))
        self.embedding_model = sfs.get('model', emb.get('model', 'BAAI/bge-m3'))
        # 阿里云向量维度（可配置，默认 1024）
        self.embedding_dimension = int(emb.get('dimension', 1024))
        # 默认检索条数（每条消息 searching 提取 keys 后检索）
        self.store_top_k = int(st.get('top_k', 5))
        # 关键词（知道/了解）触发时检索条数
        self.store_keyword_top_k = int(st.get('keyword_top_k', 15))
        # 向量库持久化目录（项目根目录）
        self.store_db_dir = st.get('db_dir', '.DataBase')

    # ==================== 工具方法 ====================
    def site_keys(self) -> list:
        """返回全部启用站点标识（供 AI 选择 web_url）"""
        return [k for k, v in self.sites.items() if v.get('enabled', True)]

    def site_config(self, site_key: str) -> dict:
        """返回某站点配置，未知站点返回空 dict"""
        return self.sites.get(str(site_key), {}) or {}
