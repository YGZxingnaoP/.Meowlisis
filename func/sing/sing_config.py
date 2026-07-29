# -*- coding: utf-8 -*-
import os

# 服务端配置
SERVER_URL = "http://127.0.0.1:5000"
SONG_CACHE_DIR = "./output/songs"
os.makedirs(SONG_CACHE_DIR, exist_ok=True)

# RVC 配置（需根据实际部署修改）
RVC_ENABLED = True
RVC_API_URL = "http://127.0.0.1:8000"
RVC_VOICE_ID = "miaowu"

# 哼歌模块配置
HUM_THRESHOLD = 30                     # 相似度阈值（%）
HUM_RANDOM_RANGE = (0, 3)              # 匹配句后额外播放的句子数范围
HUM_TRIGGER_PROB = 0.25                # 哼歌触发概率（可动态修改）