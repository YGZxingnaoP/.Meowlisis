# func/tts/gpt_sovits.py
# GPT-SoVITS 语音合成引擎（唯一 TTS 引擎，参考音频由角色卡绑定传入）
import os

import requests

from func.tts.config import TTSConfig
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

        # 构造 GPT-SoVITS v2 API 请求体
        payload = {
            "text": text,
            "text_lang": "auto",
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
