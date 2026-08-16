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
        host = obs_cfg.get("url", "127.0.0.1")
        port = obs_cfg.get("port", 4455)
        password = obs_cfg.get("password", "")
        switch = obs_cfg.get("switch", False)
        try:
            self.obs = ObsWebSocket(host=host, port=port, password=password, switch=switch)
            self.obs.connect()
        except Exception as e:
            self.log.error(f"OBS 连接失败，将禁用 OBS 功能: {e}")
            # 关键：连接失败时返回一个 switch=False 的实例，保证后续所有 obs.xxx 调用都安全跳过（no-op）
            self.obs = ObsWebSocket(host=host, port=port, password=password, switch=False)

    def get_ws(self):
        return self.obs