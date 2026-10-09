from func.pipeline.config_reader import ConfigReader


class MeowPsycheConfig:
    def __init__(self):
        """读取心理模块配置，节点 psyche，缺省复用 llm 节点密钥"""
        root = ConfigReader().get()
        cfg = root.get('psyche', {}) or {}
        llm = root.get('llm', {}) or {}
        self.enabled = bool(cfg.get('enabled', True))
        self.llm_type = str(cfg.get('llm_type', llm.get('local_llm_type', 'deepseek')) or 'deepseek')
        self.interval_seconds = int(cfg.get('interval_seconds', 5) or 5)
        self.max_tokens = int(cfg.get('max_tokens', 600) or 600)
        self.temperature = float(cfg.get('temperature', 0.7) or 0.7)
        self.short_rounds = int(cfg.get('short_rounds', 3) or 3)
        ds = cfg.get('deepseek', {}) or llm.get('deepseek', {}) or {}
        self.deepseek_api_key = ds.get('api_key', '')
        self.deepseek_base_url = ds.get('base_url', 'https://api.deepseek.com/v1')
        self.deepseek_model = ds.get('model', 'deepseek-chat')
        al = cfg.get('aliyun', {}) or llm.get('aliyun', {}) or {}
        self.aliyun_api_key = al.get('api_key', '')
        self.aliyun_base_url = al.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.aliyun_model = al.get('model', 'qwen-plus')
        gm = cfg.get('gemini', {}) or llm.get('gemini', {}) or {}
        self.gemini_api_key = gm.get('api_key', '')
        self.gemini_base_url = gm.get('base_url', 'https://generativelanguage.googleapis.com/v1beta/openai/')
        self.gemini_model = gm.get('model', 'gemini-3.6-flash')
