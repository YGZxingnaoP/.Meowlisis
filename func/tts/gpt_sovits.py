# func/tts/gpt_sovits.py
# GPT-SoVITS 语音合成引擎（唯一 TTS 引擎，参考音频由角色卡绑定传入）
import os

import requests

from func.log.default_log import DefaultLog
from func.tts.config import TTSConfig
from func.tts.emotion import build_sampling_params
from func.tts.lan_judge import LanguageJudge
from func.tools.singleton_mode import singleton


@singleton
class GptSovits:
    def __init__(self):
        # 从集中配置读取引擎参数
        self.log = DefaultLog().getLogger()
        self.config = TTSConfig()
        self._apply_endpoint()

    def _apply_endpoint(self):
        """按 config 里的 GPT-SoVITS 地址重算端点（热重载复用）"""
        self.api_base_url = self.config.gpt_sovits_url
        if not self.api_base_url.endswith('/'):
            self.api_base_url += '/'
        self.tts_endpoint = self.api_base_url + "tts"

    def rebuild(self):
        """配置热重载：刷新引擎地址（模型权重在 .vendor 侧，不在本进程）"""
        self._apply_endpoint()

    def _resolve_text_lang(self, text: str) -> str:
        """按配置决定合成语言：启用整段语言判定时，仅整段 en/ja 覆盖默认，否则用配置默认。"""
        if not getattr(self.config, "lang_judge_enabled", True):
            return self.config.text_lang
        return LanguageJudge(self.config.text_lang).judge(text)

    def _sampling_params(self, emotion: str = "neutral", intensity: float = 3.0) -> dict:
        """基础采样参数 + 情绪覆盖（逻辑委托 func.tts.emotion.build_sampling_params）。"""
        base = {
            "top_k": getattr(self.config, "top_k", 15),
            "top_p": getattr(self.config, "top_p", 1.0),
            "temperature": getattr(self.config, "temperature", 1.0),
            "repetition_penalty": getattr(self.config, "repetition_penalty", 1.35),
            "noise_scale": getattr(self.config, "noise_scale", 0.5),
            "speed": getattr(self.config, "speed", 1.0),
        }
        return build_sampling_params(emotion, intensity, base, self.config.emotion_params)

    def _build_payload(self, text: str, ref_audio_path: str, prompt_text: str, prompt_lang: str,
                       params: dict, emotion: str = "neutral", intensity: float = 3.0) -> dict:
        """构造 api_v2 请求体（子类可覆写以追加引擎专属字段）"""
        return {
            "text": text,
            "text_lang": self._resolve_text_lang(text),
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "media_type": self.config.media_type,
            "streaming_mode": self.config.streaming_mode,
            "fragment_interval": self.config.fragment_interval,
            "min_chunk_length": self.config.min_chunk_length,
            "overlap_length": self.config.overlap_length,
            "top_k": params["top_k"],
            "top_p": params["top_p"],
            "temperature": params["temperature"],
            "repetition_penalty": params["repetition_penalty"],
            "noise_scale": params["noise_scale"],
            "speed_factor": params["speed"],
        }

    def get_sovits_stream(self, text: str, ref_audio_config: dict = None,
                          emotion: str = "neutral", intensity: float = 3.0):
        """流式合成，返回 (生成器, 取消函数)。

        生成器逐块 yield 裸 PCM 字节（int16 / 单声道 / self.config.sample_rate Hz）。
        取消函数用于打断时主动关闭 HTTP 连接。
        失败返回 (None, None)。
        """
        ref_audio_config = ref_audio_config or {}
        ref_audio_path = ref_audio_config.get("audio", "")
        prompt_text = ref_audio_config.get("text", "")
        prompt_lang = ref_audio_config.get("lang", "zh")

        if not ref_audio_path or not os.path.exists(ref_audio_path):
            self.log.error(f"[TTS] 参考音频文件不存在，无法合成: {ref_audio_path}")
            return None, None
        if not prompt_text:
            self.log.error("[TTS] 缺少参考音频对应的参考文本，无法合成")
            return None, None

        # SoVITS 服务进程的 cwd 与主程序不同，转为绝对路径避免找不到文件
        ref_audio_path = os.path.abspath(ref_audio_path)

        params = self._sampling_params(emotion, intensity)
        payload = self._build_payload(
            text, ref_audio_path, prompt_text, prompt_lang, params, emotion, intensity
        )

        try:
            # stream=True 建立连接后即返回，body 由生成器惰性读取
            response = requests.post(self.tts_endpoint, json=payload, stream=True, timeout=(5, 300))
        except Exception as e:
            self.log.error(f"[TTS] 引擎不可用（{self.tts_endpoint}），本段无法合成: {e}")
            return None, None

        if response.status_code != 200:
            self.log.error(f"[TTS] 引擎返回 {response.status_code}: {response.text[:200]}")
            try:
                response.close()
            except Exception:
                pass
            return None, None

        def generator():
            try:
                for chunk in response.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            except Exception:
                # 被 cancel/打断时 response 可能已被关闭，静默结束
                pass
            finally:
                try:
                    response.close()
                except Exception:
                    pass

        def cancel():
            try:
                response.close()
            except Exception:
                pass

        return generator(), cancel
