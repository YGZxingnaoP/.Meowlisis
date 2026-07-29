from func.log.default_log import DefaultLog
from func.config.default_config import defaultConfig
from func.obs.obs_websocket import ObsWebSocket, VideoStatus, VideoControl
from func.tools.singleton_mode import singleton

@singleton
class ObsInit:
    log = DefaultLog().getLogger()
    config = defaultConfig().get_config()

    def __init__(self):
        obs_cfg = self.config.get("obs", {})
        self.obs = ObsWebSocket(
            host=obs_cfg.get("url", "192.168.2.198"),
            port=obs_cfg.get("port", 4455),
            password=obs_cfg.get("password", ""),
            switch=obs_cfg.get("switch", False),
        )
        # 尝试连接，失败时标记 obs 为 None 并记录错误
        try:
            self.obs.connect()
        except Exception as e:
            self.log.error(f"OBS 连接失败，将禁用 OBS 功能: {e}")
            self.obs = None  # 关键：设为 None 表示不可用

    def get_ws(self):
        return self.obs