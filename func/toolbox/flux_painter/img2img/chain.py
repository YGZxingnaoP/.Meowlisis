# -*- coding: utf-8 -*-

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.flux_painter.config import TBFluxPainterConfig
from func.toolbox.flux_painter.img2img.ref_focus import TBRefFocus
from func.toolbox.flux_painter.img2img.ref_judge import TBRefJudge
from func.toolbox.flux_painter.painting_core import TBFluxPainterCore

@singleton
class TBImg2ImgChain:
    """图生图：判定参考来源 → 取图（截图取景 / 附图落地）→ 开画"""

    def __init__(self):
        """初始化。"""
        self.log = DefaultLog().getLogger()
        self.config = TBFluxPainterConfig()
        self.core = TBFluxPainterCore()

    def open_screen(self, arguments, channel="live"):
        """live / 弹幕 / 语音 / 手机：模型判断是否要参考屏幕，命中则截图取景后开画"""
        if not self.config.enabled or not self.config.img2img_enabled:
            return ""
        if not self.core.has_identity():
            return ""
        if self.core.is_painting(channel):
            return ""
        request = str((arguments or {}).get("request") or self.core.context_text() or "").strip()
        if not request:
            return ""
        if not TBRefJudge().needs_screen(request):
            return ""
        self.core.broadcast_status(channel, "我先看看屏幕上的画面…")
        focus = TBRefFocus()
        shot = focus.capture()
        if not shot:
            return ""
        canvas_w, canvas_h = self.config.canvas_default
        result = focus.focus(shot, request, canvas_w, canvas_h)
        crop = str(result.get("crop") or "")
        if not crop:
            if result.get("found") is False:
                problem = str(result.get("problem") or "").strip()
                fallback = str(result.get("fallback") or "end").strip().lower()
                self.log.info(f"[flux_painter] 屏幕上没找到要画的主体（处置={fallback}）：{problem[:60]}")
                if fallback == "text":
                    need = (f"屏幕上没找到主人要画的东西（{problem[:40]}），你打算先按他说的文字直接画一张。"
                            "用你自己的口气跟他说一句，别念技术细节。")
                    self.core.say_need(channel, need, 40)
                    return self.core.open_paint(channel, arguments)
                need = (f"屏幕上没找到主人要画的东西（{problem[:40]}）。"
                        "用你自己的口气问一句：是不是没打开那个画面，或者要画屏幕上哪一块？别硬画。")
                self.core.say_need(channel, need, 40)
                return "屏幕上没找到要画的内容，已经问了主人"
            self.log.warning("[flux_painter] 屏幕取景失败，本次按文生图继续")
            return ""
        self.log.info(f"[flux_painter] 屏幕参考图: {crop}")
        return self.core.open_paint(channel, arguments, init_image=crop,
                                    ref_note=str(result.get("note") or ""))

    def open_image(self, channel, request, init_image, qq_context=None):
        """QQ 附图：参考图由调用方（router）给定，直接开画"""
        if not str(init_image or "").strip():
            return ""
        arguments = {"request": str(request or ""), "topic": ""}
        return self.core.open_paint(channel, arguments, qq_context=qq_context,
                                    init_image=str(init_image))
