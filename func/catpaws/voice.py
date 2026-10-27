# -*- coding: utf-8 -*-
# func/catpaws/voice.py
# 语音桥接：角色说话走 TTS，服务端提问转成阻塞等待，手机没连上时以角色口吻说明
from func.catpaws.config import CWCatPawsConfig
from func.catpaws.port import get_catpaws_port
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class CWCatPawsVoice:
    """TTS 播报、追问等待、兜底角色化回应"""

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = config or CWCatPawsConfig()

    def speak(self, text, source="catpaws"):
        """把一段文本交给 TTS（分段流式）"""
        body = str(text or "").strip()
        if not body:
            return False
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(body, source=source)
            return True
        except Exception:
            self.log.exception("[CatPaws] TTS 播报失败")
            return False

    def interrupt(self):
        """打断当前播报（停止词/链路结束时用）"""
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().interrupt()
        except Exception:
            self.log.exception("[CatPaws] 打断播报失败")

    def wait(self, meowid="", timeout=None):
        """阻塞等待用户的一条文本回复（经 TBExcuse 的等待队列送达）"""
        wait_for = timeout if timeout is not None else (self.config.answer_timeout or 300)
        try:
            from func.toolbox.excuse import TBExcuse
            return TBExcuse().wait_text(meowid, wait_for)
        except Exception:
            self.log.exception("[CatPaws] 等待用户回复失败")
            return None

    def excuse(self, reason, meowid=""):
        """手机没连上/服务没起来时，以角色口吻说明一句（不是固定播报）"""
        text = self._character_line(reason, meowid)
        if text:
            self.speak(text)
            return text
        fallback = "手机那边现在还没连好，等我弄好了再帮你办。"
        self.speak(fallback)
        return fallback

    def _character_line(self, reason, meowid=""):
        """让角色把「内部原因」转成自己会说的一句话"""
        try:
            from func.catpaws.prompt import CWCatPawsPrompt
            system_prompt = CWCatPawsPrompt().system_prompt(meowid, reason)
            if not system_prompt:
                return ""
            port = get_catpaws_port(self.config)
            answer = port.text([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    "（内部提示：%s）请用你自己的角色口吻、平常的语气跟主人说一句，"
                    "让主人知道现在办不了、你在等什么；不要解释技术细节、不要说教、不要套模板。" % reason)},
            ])
            return str(answer or "").strip()
        except Exception:
            self.log.exception("[CatPaws] 生成兜底回应失败")
            return ""
