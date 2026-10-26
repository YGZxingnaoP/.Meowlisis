from func.catpaws.client import CWCatPawsClient
from func.catpaws.config import CWCatPawsConfig
from func.catpaws.if_start import CWCatPawsIfStart
from func.catpaws.state import CWCatPawsState
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class CWCatPawsStop:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CWCatPawsConfig()
        self.client = CWCatPawsClient(self.config)
        self.state = CWCatPawsState()
        self.if_start = CWCatPawsIfStart(self.config)

    def is_stop(self, text):
        return self.if_start.is_stop(text)

    def trigger(self, reason="keyword"):
        result = self.client.stop(reason)
        self.state.finish(reason, ok=False)
        ok = bool(result.get("ok"))
        if ok:
            self.log.info("[CatPaws] 已停止链路（%s）" % reason)
        else:
            self.log.warning("[CatPaws] 停止请求失败：%s" % result.get("message", ""))
        return ok
