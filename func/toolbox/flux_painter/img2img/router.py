# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/img2img/router.py
# QQ 附图转图生图：消息带图时先做语义判断（不做关键词匹配），
# 只有「明确要求以这张图作画」才接管，其余原样走看图链路。

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.flux_painter.config import TBFluxPainterConfig
from func.toolbox.flux_painter.img2img.chain import TBImg2ImgChain
from func.toolbox.flux_painter.img2img.ref_judge import TBRefJudge
from func.toolbox.flux_painter.img2img.ref_source import TBRefSource
from func.toolbox.flux_painter.painting_core import TBFluxPainterCore


@singleton
class TBFluxImg2ImgRouter:
    """QQ 图片分支的图生图路由：返回 True 表示已按图生图开画（调用方不再走看图）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBFluxPainterConfig()

    def try_handle_qq(self, text, images, parsed, group_id="", group_name=""):
        """QQ 消息入口：从事件里取发送者与身份，再走「带图作画」的语义判断"""
        parsed = parsed or {}
        user_id = str(parsed.get("user_id") or "")
        if not user_id or not images:
            return False
        try:
            from func.pipeline.id_signup import IdSignupBridge
            meowid = IdSignupBridge().meowid_of_account(
                "qq", user_id, str(parsed.get("username") or ""))
        except Exception:
            self.log.exception("[flux_painter] 图生图身份解析失败")
            return False
        if not meowid:
            return False
        is_group = bool(str(group_id or "").strip())
        ctx = {
            "channel": "qq",
            "message_type": "group" if is_group else "private",
            "target_id": str(group_id or user_id),
            "user_id": user_id,
            "meowid": meowid,
            "nickname": str(parsed.get("username") or ""),
            "ext_account": user_id,
            "ext_name": str(parsed.get("username") or ""),
            "self_id": str(parsed.get("self_id") or ""),
        }
        if is_group:
            ctx["group_id"] = str(group_id)
            ctx["group_name"] = str(group_name or "")
        return self.try_handle(TBFluxPainterCore.channel_of(ctx), text, images, ctx)

    def try_handle(self, channel, text, images, qq_context=None):
        """尝试把「带图 + 要求照图作画」的消息转成图生图；不命中返回 False"""
        if not self.config.enabled or not self.config.img2img_enabled or not images:
            return False
        request = str(text or "").strip()
        if not request:
            return False
        if not TBRefJudge().needs_image_ref(request):
            return False
        painter = TBFluxPainterCore()
        if painter.is_painting(channel):
            self.log.info(f"[flux_painter] 图生图跳过：{channel} 正在作画")
            return False
        ref_image = TBRefSource().materialize(images, self.config.ref_dir)
        if not ref_image:
            self.log.warning("[flux_painter] 判定要图生图，但参考图落地失败")
            return False
        ctx = dict(qq_context or {})
        painter.set_meowid(str(ctx.get("meowid") or ""))
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            painter.set_context({
                "text": request,
                "short_memory": [],
                "system_prompt": TBoxGetPrompt().get_tool_prompt(ctx.get("meowid") or "", request) or "",
            })
        except Exception:
            self.log.exception("[flux_painter] 图生图上下文注入失败")
        result = TBImg2ImgChain().open_image(channel, request, ref_image, ctx)
        self.log.info(f"[flux_painter] QQ 图生图接管 channel={channel} 结果={result}")
        return True
