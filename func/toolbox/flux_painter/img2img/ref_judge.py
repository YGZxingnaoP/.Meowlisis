# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/ref_judge.py
# 参考图意图判定：判断这条作画请求是否要求「以某张现成画面为参考」再落笔
#   - screen：参考当前电脑屏幕（live / 弹幕 / 语音 / 手机，全 msg 通道）
#   - image ：参考用户刚发来的那张图片（QQ）
# 纯语义判断（不做关键词匹配）；判定不出来一律按「不需要参考」处理，保持文生图。

import json
import re

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.flux_painter.config import TBFluxPainterConfig
from func.toolbox.flux_painter.port.base import create_painter_llm


SCREEN_SYSTEM = (
    "你是绘画需求的语义判定器。判断用户这句话是否要求「以当前电脑屏幕上的画面为参考」来画图。\n"
    "需要参考屏幕：把屏幕上这个画面画成…／照着这个界面画／把现在屏幕里的东西画下来／"
    "把刚才那个画面重画成插画／参考屏幕上的画面来一张。\n"
    "不需要参考屏幕：画一只猫／画个美少女／想象一张风景／把上一张画改一下（指上一张画作，不是屏幕）／"
    "画一个显示器（物体本身，不是屏幕内容）。\n"
    "只输出一个 JSON，不要任何多余文字：{\"need\": true} 或 {\"need\": false}"
)

IMAGE_SYSTEM = (
    "你是绘画需求的语义判定器。用户刚发来一张图片，判断这句话是否要求「以这张图片为参考」来画图或改图。\n"
    "需要参考这张图：把这张图改成…／照着这张画一张／参考我刚发的图来…／按这张图重画。\n"
    "不需要参考这张图：画个猫（图片只是随手发的）／这张图是什么／好看吗／图里的字写的啥（只是在看图）。\n"
    "只输出一个 JSON，不要任何多余文字：{\"need\": true} 或 {\"need\": false}"
)


@singleton
class TBRefJudge:
    """参考图语义判定：一次小调用拿一个是/否，供绘画链路决定要不要走图生图"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBFluxPainterConfig()

    def needs_screen(self, request: str) -> bool:
        """这条作画请求是否要求参考屏幕内容"""
        return self._ask(SCREEN_SYSTEM, request)

    def needs_image_ref(self, request: str) -> bool:
        """这条作画请求是否要求参考用户刚发来的图片"""
        return self._ask(IMAGE_SYSTEM, request)

    def _ask(self, system: str, request: str) -> bool:
        """一次判定调用：返回 True/False，客户端不可用或解析失败统一 False（保持文生图）"""
        text = str(request or "").strip()
        if not text or not self.config.img2img_enabled:
            return False
        try:
            llm = create_painter_llm(self.config)
            if llm is None or not getattr(llm, "client", None):
                return False
            resp = llm.chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": f"用户消息：{text}"}],
                tools=None, enable_thinking=False,
                options={"temperature": 0.1, "max_tokens": 120},
            )
            if not resp or not getattr(resp, "choices", None):
                return False
            content = str(getattr(resp.choices[0].message, "content", "") or "")
            return self._parse(content)
        except Exception:
            self.log.exception("[flux_painter] 参考图意图判定异常")
            return False

    @staticmethod
    def _parse(content: str) -> bool:
        """解析 {"need": true}；解析不到时看文本里的 true/false"""
        match = re.search(r"\{[\s\S]*\}", content or "")
        if match:
            try:
                data = json.loads(match.group(0))
                return bool(data.get("need"))
            except Exception:
                pass
        low = str(content or "").strip().lower()
        if "false" in low:
            return False
        return "true" in low
