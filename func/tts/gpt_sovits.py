# func/tts/gpt_sovits.py
# GPT-SoVITS 语音合成引擎（唯一 TTS 引擎）
import os
import random

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

        # 加载角色卡参考音频映射（character -> 配置）
        self.character_refs = self.config.character_refs
        self.character_map = {}
        for ref in self.character_refs:
            char_name = ref.get("character", "").strip().lower()
            if char_name:
                self.character_map[char_name] = ref
        self.default_ref = self.character_refs[0] if self.character_refs else None
        self.current_character = None

    def set_character(self, character_name: str):
        """设置当前使用的角色卡名称"""
        self.current_character = character_name

    def get_random_character(self):
        """随机返回一个可用角色卡名称"""
        if self.character_refs:
            return random.choice(self.character_refs).get("character", "").strip()
        return None

    def resolve_character(self, prompt: str):
        """从角色提示词中解析角色名（system_prompt 未实现，先保留接口）"""
        if not prompt:
            return None
        prompt_lower = prompt.lower()
        for name in self.character_map:
            if name in prompt_lower:
                return self.character_map[name].get("character", "")
        return None

    def get_sovits(self, filename: str, text: str, character: str = None) -> int:
        """合成语音并保存为 wav，返回 1 成功 0 失败"""
        # 确定参考音频角色，未匹配时回退到默认配置
        char_name = character or self.current_character
        ref_config = None
        if char_name:
            ref_config = self.character_map.get(char_name.lower())
        if not ref_config:
            ref_config = self.default_ref
            if char_name:
                print(f"未找到角色 '{char_name}' 的参考音频，使用默认配置")
        if not ref_config:
            print("错误：没有任何参考音频配置，无法合成")
            return 0

        ref_audio_path = ref_config.get("audio", "")
        prompt_text = ref_config.get("text", "")
        prompt_lang = ref_config.get("lang", "zh")
        if not ref_audio_path or not os.path.exists(ref_audio_path):
            print(f"参考音频文件不存在: {ref_audio_path}")
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
