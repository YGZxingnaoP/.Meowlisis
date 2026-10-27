# -*- coding: utf-8 -*-
# func/catpaws/stop.py
# 停止触发：命中停止词立即停手、停链路、停语音
from func.catpaws.client import CWCatPawsClient
from func.catpaws.config import CWCatPawsConfig
from func.catpaws.state import CWCatPawsState
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class CWCatPawsStop:
    """停止检测与执行（默认「别再操控手机了」「手机还我」，可配置）"""

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = config or CWCatPawsConfig()
        self.client = CWCatPawsClient(self.config)
        self.state = CWCatPawsState()

    def is_stop(self, text):
        """判断文本是否命中停止词"""
        body = str(text or "").strip()
        if not body:
            return False
        return any(word and word in body for word in self.config.stop_keywords)

    def trigger(self, reason="user"):
        """立即停止：服务端停手、语音停播、链路状态结束"""
        result = self.client.stop(reason)
        if not result.get("ok"):
            self.log.warning("[CatPaws] 停止请求未成功：%s" % result.get("message", ""))
        try:
            from func.catpaws.voice import CWCatPawsVoice
            CWCatPawsVoice().interrupt()
        except Exception:
            self.log.exception("[CatPaws] 打断语音失败")
        self.state.finish(reason)
        self.log.info("[CatPaws] 已停止链路（%s）" % reason)
        return True
