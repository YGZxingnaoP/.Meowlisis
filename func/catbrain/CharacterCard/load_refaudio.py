# -*- coding: utf-8 -*-
# func/catbrain/CharacterCard/load_refaudio.py
# 参考音频配置加载：读取 character/ref_audio/config.json（角色卡名 → 参考音频配置）

import os
import json

from func.log.default_log import DefaultLog


class MeowLoadRefAudio:
    """参考音频配置加载类：按角色卡名读取参考音频、参考文本与语言"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config_path = os.path.join("character", "ref_audio", "config.json")

    def load(self) -> dict:
        """读取参考音频配置（缺失或损坏时返回空 dict）"""
        if not os.path.exists(self.config_path):
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception("读取参考音频配置失败")
            return {}

    def get(self, character_name: str) -> dict:
        """按角色卡名获取参考音频配置（无匹配时返回空 dict）"""
        data = self.load()
        return data.get(character_name) or {}
