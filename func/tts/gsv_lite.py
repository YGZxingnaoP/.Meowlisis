# -*- coding: utf-8 -*-
# func/tts/gsv_lite.py
# GSV-TTS-Lite 客户端适配：沿用 api_v2 协议，追加情绪与首块加速字段
from func.tts.gpt_sovits import GptSovits


class GsvLite(GptSovits):
    """GSV-Lite 合成引擎（CUDA Graph 加速版）

    - 端点指向 tts.gsv_lite_url，而不是原版 gpt_sovits_url；
    - 请求体沿用 api_v2 字段，额外带上当前情绪/强度与首块加速开关；
    - 情绪参数仍由 GptSovits._sampling_params 逐句计算（动态变化），
      这里只是把同一份结果原样发给 lite 服务。
    """

    def _apply_endpoint(self):
        base = self.config.gsv_lite_url
        if not base.endswith('/'):
            base += '/'
        self.api_base_url = base
        self.tts_endpoint = base + "tts"

    def _build_payload(self, text: str, ref_audio_path: str, prompt_text: str, prompt_lang: str,
                       params: dict, emotion: str = "neutral", intensity: float = 3.0) -> dict:
        payload = super()._build_payload(
            text, ref_audio_path, prompt_text, prompt_lang, params, emotion, intensity
        )
        payload.update({
            "emotion": str(emotion or "neutral"),
            "emotion_intensity": float(intensity or 3.0),
            "boost_first_chunk": bool(getattr(self.config, "lite_boost_first_chunk", True)),
        })
        return payload
