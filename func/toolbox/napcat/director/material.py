# -*- coding: utf-8 -*-
# func/toolbox/napcat/director/material.py
# QQ 导演素材：从 character/shared_videos 里随机抽一条「分享过的视频」当话头
# 只读，不移动、不消费。

import os
import json
import random

from func.log.default_log import DefaultLog

SHARED_DIR = os.path.join("character", "shared_videos")
BRIEF_LIMIT = 320


class QQDirectorMaterial:
    """随机抽已分享视频：返回 {"type","title","brief"}；没有可用视频返回空 dict"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def pick(self) -> dict:
        try:
            if not os.path.isdir(SHARED_DIR):
                return {}
            files = [f for f in os.listdir(SHARED_DIR) if f.endswith(".json")]
            if not files:
                return {}
            path = os.path.join(SHARED_DIR, random.choice(files))
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            title = str(data.get("title", "") or "").strip()
            content = str(data.get("content", "") or "").strip()
            if not (title or content):
                return {}
            brief = f"{title}｜{content}" if content else title
            return {"type": "video", "title": title, "brief": brief[:BRIEF_LIMIT]}
        except Exception:
            self.log.exception("[QQ导演] 抽取素材失败")
            return {}
