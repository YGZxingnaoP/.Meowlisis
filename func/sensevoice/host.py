# -*- coding: utf-8 -*-
# func/sensevoice/host.py
# SenseVoice 生命周期宿主：持有识别核心实例，负责启动与热启用/热停用
# 注意：不要命名为 manager —— func/sensevoice/manager.py 是会话级消息处理器

from func.sensevoice.config import SenseVoiceConfig
from func.tools.singleton_mode import singleton


@singleton
class SenseVoiceHost:
    """SenseVoice 识别核心的宿主单例（核心本身仍是普通类，不改成单例）"""

    def __init__(self):
        self.core = None

    def boot(self, callback=None):
        """启动识别核心（幂等）。无论配置是否启用都启动线程，开关交给 apply_enabled"""
        if self.core is None:
            from func.sensevoice.sensevoice_core import SenseVoiceCore
            self.core = SenseVoiceCore(callback=callback)
            self.core.start()
        return self.core

    def apply(self):
        """热重载钩子：按最新 sensevoice.enabled 切换总开关"""
        if self.core is not None:
            self.core.apply_enabled(SenseVoiceConfig().enabled)

    @property
    def running(self) -> bool:
        return bool(self.core is not None and self.core.enabled)

    @property
    def hub(self):
        return self.core.hub if self.core is not None else None

    @property
    def subtitle(self):
        return self.core.subtitle if self.core is not None else None
