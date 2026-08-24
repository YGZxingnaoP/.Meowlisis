# -*- coding: utf-8 -*-
# func/vts/vts_oper.py
# VTS 表情/换装操作入口（触发热键）

from func.log.default_log import DefaultLog
from func.vts.vts_init import VtsInit
from func.vts.config import VtsConfig
from func.vts.state import VtsState
from func.tools.singleton_mode import singleton


@singleton
class VtsOper:
    """VTS 操作入口：统一通过热键触发表情/动作/换装"""

    # 设置控制台日志
    log = DefaultLog().getLogger()
    vtsConfig = VtsConfig()
    vtsState = VtsState()

    def __init__(self):
        self.vts = VtsInit()

    def emote_ws(self, num, interval, key):
        """触发热键（保留历史命名接口，供 api.py 换装/HTTP 表情调用）

        - num：延迟的字符序号（大于 0 时按 num*interval 秒延时）；
        - interval：每个字符的间隔秒数；
        - key：VTS hotkeyID。
        """
        if self.vtsConfig.switch == False:
            return
        if num > 0:
            import time
            start = round(num * interval, 2)
            time.sleep(start)
        self.vts.trigger_hotkey(key)
