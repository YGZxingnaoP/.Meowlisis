from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton

CW_DEFAULT_PREFIX = ["操作手机", "用手机", "在手机上", "帮我用手机", "帮我把手机"]
CW_DEFAULT_INTENT = ["操作手机", "手机操作", "点外卖", "点个外卖", "用手机做", "手机上帮我"]
CW_DEFAULT_STOP = ["停止操作", "停下", "别操作了", "取消操作", "退出操作"]
CW_DEFAULT_TRIGGER_APPS = [
    "微信", "QQ", "支付宝", "淘宝", "天猫", "美团", "饿了么", "抖音", "快手", "小红书", "微博",
    "高德地图", "百度地图", "相册", "照片", "相机", "设置", "电话", "信息", "短信", "备忘录",
    "日历", "闹钟", "时钟", "邮件", "音乐", "地图", "文件", "Safari", "网易云音乐", "哔哩哔哩",
]
CW_DEFAULT_ACTION_WORDS = [
    "打开", "发", "点", "进", "去", "搜", "翻", "切", "关", "帮我", "帮忙",
]


@singleton
class CWCatPawsConfig:
    def __init__(self):
        cfg = ConfigReader().get("catpaws", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.host = str(cfg.get("host", "127.0.0.1"))
        self.port = int(cfg.get("port", 18110))
        self.relay_port = int(cfg.get("relay_port", 18111))
        self.token = str(cfg.get("token", "") or "")
        self.timeout = float(cfg.get("timeout", 10))
        self.poll_sec = float(cfg.get("poll_sec", 1.5))
        self.max_run_sec = int(cfg.get("max_run_sec", 1800))
        self.answer_timeout = int(cfg.get("answer_timeout", 90))
        self.notify = bool(cfg.get("notify", True))
        prefixes = cfg.get("start_prefixes", None)
        intents = cfg.get("intent_keywords", None)
        stops = cfg.get("stop_keywords", None)
        apps = cfg.get("trigger_apps", None)
        actions = cfg.get("action_words", None)
        self.start_prefixes = [str(item) for item in (prefixes if prefixes is not None else CW_DEFAULT_PREFIX)]
        self.intent_keywords = [str(item) for item in (intents if intents is not None else CW_DEFAULT_INTENT)]
        self.stop_keywords = [str(item) for item in (stops if stops is not None else CW_DEFAULT_STOP)]
        self.trigger_apps = [str(item) for item in (apps if apps is not None else CW_DEFAULT_TRIGGER_APPS)]
        self.action_words = [str(item) for item in (actions if actions is not None else CW_DEFAULT_ACTION_WORDS)]

    def base_url(self):
        return "http://%s:%d" % (self.host, self.port)

    def headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        return headers
