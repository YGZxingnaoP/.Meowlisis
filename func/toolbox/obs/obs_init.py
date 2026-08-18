from func.log.default_log import DefaultLog
from func.toolbox.obs.config import ObsConfig
from func.toolbox.obs.obs_websocket import ObsWebSocket, VideoStatus, VideoControl
from func.tools.singleton_mode import singleton

@singleton
class ObsInit:
    log = DefaultLog().getLogger()
    config = ObsConfig()

    def __init__(self):
        host = self.config.url
        port = self.config.port
        password = self.config.password
        switch = self.config.switch
        try:
            self.obs = ObsWebSocket(host=host, port=port, password=password, switch=switch)
            self.obs.connect()
        except Exception as e:
            self.log.error(f"OBS 连接失败，将禁用 OBS 功能: {e}")
            # 关键：连接失败时返回一个 switch=False 的实例，保证后续所有 obs.xxx 调用都安全跳过（no-op）
            self.obs = ObsWebSocket(host=host, port=port, password=password, switch=False)

    def get_ws(self):
        return self.obs