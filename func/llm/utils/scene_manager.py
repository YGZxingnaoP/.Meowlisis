# -*- coding: utf-8 -*-
"""
场景管理器：根据 AI 回复内容切换场景。
"""
import re
import random
from typing import Optional

class SceneManager:
    """根据关键词切换场景"""

    # 关键词到场景名的映射（可配置）
    SCENE_MAP = {
        "粉色": "粉色房间",
        "睡觉": "粉色房间",
        "粉红": "粉色房间",
        "房间": "粉色房间",
        "晚上": "粉色房间",
        "清晨": "清晨房间",
        "早": "清晨房间",
        "睡醒": "清晨房间",
        "祭拜": "神社",
        "神社": "神社",
        "寺庙": "神社",
        "花房": "花房",
        "花香": "花房",
        "岸": "海岸花坊",
        "海": "海岸花坊"
    }

    @classmethod
    def get_scene(cls, text: str) -> Optional[str]:
        """
        根据文本内容返回应切换的场景名，若无匹配则返回 None
        """
        for keyword, scene in cls.SCENE_MAP.items():
            if keyword in text:
                return scene
        return None