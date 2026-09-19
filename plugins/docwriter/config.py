DEFAULTS = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "aliyun": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-2.0-flash"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}

# 生图端口默认值（硅基流动 Kwai-Kolors/Kolors）
# 注意：尺寸不在这里配置，由模型按用途（square/wide/tall）在图生工具里自行决定
IMAGE_DEFAULTS = {
    "enabled": True,
    "provider": "siliconflow",
    "base_url": "https://api.siliconflow.cn/v1",
    "model": "Kwai-Kolors/Kolors",
    "steps": 28,           # 实测 20 步偏噪，28 步更干净
    "guidance": 9.0,       # 7.5 偏松散，9.0 细节更实
    "timeout": 180,
    "style_suffix": True,
    "retry": 2,            # 429（IPM 限流）重试次数
    "retry_wait": 20,      # 首次退避秒数（第 n 次等待 n*wait）
    "max_per_doc": 4,      # 单篇最多配几张图（网络图 + 生成图合计）
    "source": "both",      # both=生图+搜图 / gen=只生图 / search=只搜图
    "min_w": 700,          # 网络图最小宽度
    "min_h": 450,
    "max_side": 1600,      # 网络图落盘最大边长
}


class DocWriterConfig:
    def __init__(self, data=None):
        """文档助手配置（LLM / 生图 各自独立配置）"""
        data = data or {}
        llm = data.get("llm") or {}
        self.provider = str(llm.get("provider", "deepseek"))
        preset = DEFAULTS.get(self.provider, DEFAULTS["deepseek"])
        self.api_key = str(llm.get("api_key", ""))
        self.base_url = str(llm.get("base_url") or preset["base_url"])
        self.model = str(llm.get("model") or preset["model"])
        self.temperature = float(llm.get("temperature", 0.7))
        self.max_tokens = int(llm.get("max_tokens", 8192))

        search = data.get("search") or {}
        self.output_dir = data.get("output_dir", "./character/catfiles")
        self.engine = str(search.get("engine", "both"))
        self.top_n = int(search.get("top_n", 5))
        self.timeout = int(search.get("timeout", 15))
        self.page_chars = int(search.get("page_chars", 4000))
        self.dynamic = str(search.get("dynamic", "auto"))
        self.driver_dir = search.get("driver_dir", "./.temp/edgedriver")
        self.driver_mirror = search.get("driver_mirror", "https://msedgedriver.microsoft.com")
        self.agent_rounds = int(search.get("agent_rounds", data.get("agent_rounds", 20)))

        # ---- 生图 ----
        img = dict(IMAGE_DEFAULTS)
        img.update(data.get("image") or {})
        self.image = img
        self.images_enabled = bool(img.get("enabled", True))
        self.image_source = str(img.get("source", "both")).lower()
        self.image_max = int(img.get("max_per_doc", 4) or 0)
        self.image_min_w = int(img.get("min_w", 700) or 700)
        self.image_min_h = int(img.get("min_h", 450) or 450)
        self.image_max_side = int(img.get("max_side", 1600) or 1600)   # 网络图落盘最大边长

        # ---- 排版 ----
        style = data.get("style") or {}
        self.theme = str(style.get("theme", "auto"))       # auto = 交给模型选
        self.cover = bool(style.get("cover", True))
        self.toc = bool(style.get("toc", False))
