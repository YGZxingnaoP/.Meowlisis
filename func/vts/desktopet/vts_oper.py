# -*- coding: utf-8 -*-
# func/vts/desktopet/vts_oper.py
# 桌宠表情操作入口（触发热键）

from func.log.default_log import DefaultLog
from func.vts.desktopet.vts_init import DesktopetInit
from func.vts.desktopet.config import DesktopetConfig
from func.vts.desktopet.state import DesktopetState
from func.tools.singleton_mode import singleton


@singleton
class DesktopetOper:
    """桌宠操作入口：统一通过热键触发表情"""

    log = DefaultLog().getLogger()
    desktopetConfig = DesktopetConfig()
    desktopetState = DesktopetState()

    def __init__(self):
        self.desktopet = DesktopetInit()

    def emote_ws(self, num, interval, key):
        """触发热键（保留与 VTS 一致的命名接口）

        - num：延迟的字符序号（大于 0 时按 num*interval 秒延时）；
        - interval：每个字符的间隔秒数；
        - key：桌宠 hotkeyID。
        """
        if self.desktopetConfig.switch == False:
            return
        if num > 0:
            import time
            start = round(num * interval, 2)
            time.sleep(start)
        self.desktopet.trigger_hotkey(key)
