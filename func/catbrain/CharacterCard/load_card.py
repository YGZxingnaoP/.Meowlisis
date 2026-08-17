# -*- coding: utf-8 -*-
# func/catbrain/CharacterCard/load_card.py
# 角色卡加载：读取 character/info/character_prompt/{配置文件名}.json

import os
import json

from func.log.default_log import DefaultLog
from func.catbrain.config import MeowCatBrainConfig


class MeowLoadCard:
    """角色卡加载类：读取并返回角色卡提示词文件的原始数据"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        # 文件名可配置，默认 prompt，兼容缺省 .json 后缀
        filename = self.config.character_prompt_file or "prompt"
        if not filename.endswith(".json"):
            filename += ".json"
        self.card_path = os.path.join("character", "info", "character_prompt", filename)

    def load(self) -> dict:
        """读取角色卡提示词文件，缺失时返回空 dict"""
        if not os.path.exists(self.card_path):
            self.log.warning(f"角色卡不存在: {self.card_path}")
            return {}
        try:
            with open(self.card_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            self.log.exception("读取角色卡失败")
            return {}
