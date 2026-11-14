# -*- coding: utf-8 -*-

from func.tools.singleton_mode import singleton
from func.toolbox.flux_painter.painting_core import TBFluxPainterCore

@singleton
class TBTxt2ImgChain:
    """文生图：按文字需求直接开画"""

    def __init__(self):
        """初始化。"""
        self.core = TBFluxPainterCore()

    def open_live(self, arguments):
        """live 主链路（含语音 / 弹幕 / 手机同一条 msg 管线）开画"""
        return self.core.open_paint("live", arguments)

    def open_qq(self, arguments, qq_context):
        """QQ 开画：通道按群聊 / 私聊隔离"""
        if not qq_context:
            return "缺少 QQ 上下文"
        return self.core.open_paint(self.core.channel_of(qq_context), arguments,
                                    qq_context=qq_context)
