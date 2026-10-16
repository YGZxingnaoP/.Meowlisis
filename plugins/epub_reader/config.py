DEFAULTS = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "aliyun": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-2.0-flash"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}


class EpubConfig:
    def __init__(self, ctx):
        data = ctx.config or {}
        llm = data.get("llm") or {}
        self.provider = str(llm.get("provider", "deepseek"))
        preset = DEFAULTS.get(self.provider, DEFAULTS["deepseek"])
        self.api_key = str(llm.get("api_key", ""))
        self.base_url = str(llm.get("base_url") or preset["base_url"])
        self.model = str(llm.get("model") or preset["model"])
        self.temperature = float(llm.get("temperature", 0.7))
        self.max_tokens = int(llm.get("max_tokens", 2048))
        self.books_dir = ctx.resolve(data.get("books_dir") or "./character/books")
        self.emotion = str(data.get("emotion", "neutral"))
        self.speed = max(0.5, min(1.5, float(data.get("speed", 0.9))))
        self.min_chars = int(data.get("min_chars", 3000))
        self.section_paras = int(data.get("section_paras", 8))
        self.section_wait = float(data.get("section_wait", 3))
        self.short_mem_limit = int(data.get("short_mem_limit", 30))
        self.followup_enabled = bool(data.get("followup_enabled", True))
        self.followup_window = float(data.get("followup_window", 300))
        self.followup_temperature = float(data.get("followup_temperature", 0.2))
        self.followup_max_tokens = int(data.get("followup_max_tokens", 256))
