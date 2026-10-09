from func.pipeline.config_reader import ConfigReader


class MeowMemoryReviewConfig:
    def __init__(self):
        """读取记忆审查配置：节点 catbrain.abstract_mem.review，未配置时复用摘要后端"""
        node = ConfigReader().get('catbrain', {}) or {}
        cfg = (node.get('abstract_mem') or {}).get('review') or {}
        self.enabled = bool(cfg.get('enabled', True))
        self.llm_type = str(cfg.get('llm_type', '') or '')
        self.api_key = str(cfg.get('api_key', '') or '')
        self.base_url = str(cfg.get('base_url', '') or '')
        self.model = str(cfg.get('model', '') or '')
        self.max_tokens = int(cfg.get('max_tokens', 2048) or 2048)
        self.max_rounds = int(cfg.get('max_rounds', 3) or 3)
