# func/tts/gpt_sovits.py
# GPT-SoVITS 语音合成引擎（唯一 TTS 引擎，参考音频由角色卡绑定传入）
import os

import requests

from func.tts.config import TTSConfig
from func.tts.lan_judge import LanguageJudge
from func.tools.singleton_mode import singleton


@singleton
class GptSovits:
    def __init__(self):
        # 从集中配置读取引擎参数
        self.config = TTSConfig()
        self.api_base_url = self.config.gpt_sovits_url
        if not self.api_base_url.endswith('/'):
            self.api_base_url += '/'
        self.tts_endpoint = self.api_base_url + "tts"

    def _resolve_text_lang(self, text: str) -> str:
        """按配置决定合成语言：启用整段语言判定时，仅整段 en/ja 覆盖默认，否则用配置默认。"""
        if not getattr(self.config, "lang_judge_enabled", True):
            return self.config.text_lang
        return LanguageJudge(self.config.text_lang).judge(text)

    def get_sovits(self, filename: str, text: str, ref_audio_config: dict = None) -> int:
        """合成语音并保存为 wav，返回 1 成功 0 失败（参考音频配置来自角色卡绑定）"""
        ref_audio_config = ref_audio_config or {}
        ref_audio_path = ref_audio_config.get("audio", "")
        prompt_text = ref_audio_config.get("text", "")
        prompt_lang = ref_audio_config.get("lang", "zh")

        if not ref_audio_path or not os.path.exists(ref_audio_path):
            print(f"参考音频文件不存在: {ref_audio_path}")
            return 0
        if not prompt_text:
            print("缺少参考音频对应的参考文本，无法合成")
            return 0

        # SoVITS 服务进程的 cwd 与主程序不同，转为绝对路径避免找不到文件
        ref_audio_path = os.path.abspath(ref_audio_path)

        # 构造 GPT-SoVITS v2 API 请求体
        payload = {
            "text": text,
            "text_lang": self._resolve_text_lang(text),
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "media_type": "wav",
            "streaming_mode": False,
        }

        try:
            response = requests.post(self.tts_endpoint, json=payload, timeout=(5, 60))
            if response.status_code == 200:
                save_path = os.path.join(self.config.output_dir, f"{filename}.wav")
                with open(save_path, "wb") as f:
                    f.write(response.content)
                return 1
            print(f"TTS 请求失败: {response.status_code} - {response.text}")
            return 0
        except Exception as e:
            print(f"TTS 请求异常: {e}")
            return 0

    def get_sovits_stream(self, text: str, ref_audio_config: dict = None):
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
            print(f"参考音频文件不存在: {ref_audio_path}")
            return None, None
        if not prompt_text:
            print("缺少参考音频对应的参考文本，无法合成")
            return None, None

        # SoVITS 服务进程的 cwd 与主程序不同，转为绝对路径避免找不到文件
        ref_audio_path = os.path.abspath(ref_audio_path)

        payload = {
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
        }

        try:
            # stream=True 建立连接后即返回，body 由生成器惰性读取
            response = requests.post(self.tts_endpoint, json=payload, stream=True, timeout=(5, 300))
        except Exception as e:
            print(f"TTS 流式请求异常: {e}")
            return None, None

        if response.status_code != 200:
            print(f"TTS 流式请求失败: {response.status_code} - {response.text}")
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
