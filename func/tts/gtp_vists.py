# func/tts/gtp_vists.py
import os
import requests
import random
from func.config.default_config import defaultConfig
from func.tools.singleton_mode import singleton

@singleton
class GtpVists:
    def __init__(self):
        config = defaultConfig().get_config()
        speech_cfg = config.get("speech", {}).get("gpt-sovits", {})
        self.api_base_url = speech_cfg.get("gtp_vists_url", "http://127.0.0.1:9880")
        if not self.api_base_url.endswith('/'):
            self.api_base_url += '/'
        self.tts_endpoint = self.api_base_url + "tts"

        # 加载角色卡参考音频映射（character -> 配置）
        self.character_refs = speech_cfg.get("character_refs", [])
        self.character_map = {}
        for ref in self.character_refs:
            char_name = ref.get("character", "").strip().lower()
            if char_name:
                self.character_map[char_name] = ref

        # 默认参考音频（若角色未匹配，取第一个）
        self.default_ref = self.character_refs[0] if self.character_refs else None

        # 当前激活的角色卡名称（由外部通过 set_character 设置）
        self.current_character = None

    def set_character(self, character_name: str):
        """设置当前使用的角色卡名称（例如 'MiaoWu', 'TangYuan'）"""
        self.current_character = character_name

    def get_random_character(self):
        """随机返回一个可用的角色卡名称（从 character_refs 中随机选择）"""
        if self.character_refs:
            random_ref = random.choice(self.character_refs)
            return random_ref.get("character", "").strip()
        return None

    def get_vists(self, filename, text, emotion=None):
        """合成语音并保存为文件
        :param filename: 输出文件名（不含扩展名）
        :param text: 要合成的文本
        :param emotion: 保留参数（兼容旧调用），但实际不使用，改为使用 self.current_character
        :return: 1 成功，0 失败
        """
        # 优先使用当前角色卡名称，若未设置则尝试从 emotion 参数获取（向后兼容）
        char_name = self.current_character
        if not char_name and emotion:
            # 如果 emotion 参数传入的是角色名（例如旧代码可能传了角色名），也可以使用
            char_name = emotion
            print(f"警告：未通过 set_character 设置角色，使用 emotion 参数作为角色名: {char_name}")

        if not char_name:
            print("错误：未设置当前角色卡，无法选择参考音频")
            return 0

        # 查找角色对应的参考音频配置
        ref_config = self.character_map.get(char_name.lower())
        if not ref_config and self.default_ref:
            ref_config = self.default_ref
            print(f"未找到角色 '{char_name}' 的参考音频配置，使用默认配置")
        if not ref_config:
            print(f"错误：没有任何参考音频配置，无法合成")
            return 0

        ref_audio_path = ref_config.get("audio", "")
        prompt_text = ref_config.get("text", "")
        prompt_lang = ref_config.get("lang", "zh")

        # 检查参考音频文件是否存在
        if not ref_audio_path or not os.path.exists(ref_audio_path):
            print(f"参考音频文件不存在: {ref_audio_path}")
            return 0

        # 构造 GPT-SoVITS v2 API 请求体
        payload = {
            "text": text,
            "text_lang": "auto",           # 自动检测语言，也可固定为 "zh"
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "media_type": "wav",
            "streaming_mode": False,       # 非流式，一次返回完整音频
        }

        try:
            response = requests.post(self.tts_endpoint, json=payload, timeout=(5, 60))
            if response.status_code == 200:
                save_path = f"./output/{filename}.mp3"   # 保持原有命名，实际内容是 wav，mpv 可播放
                with open(save_path, "wb") as f:
                    f.write(response.content)
                return 1
            else:
                print(f"TTS 请求失败: {response.status_code} - {response.text}")
                return 0
        except Exception as e:
            print(f"TTS 请求异常: {e}")
            return 0