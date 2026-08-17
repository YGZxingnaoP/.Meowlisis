# -*- coding: utf-8 -*-
# func/sensevoice/config.py
# SenseVoice 配置项统一管理

from func.config.default_config import defaultConfig
from func.tools.singleton_mode import singleton


@singleton
class SenseVoiceConfig:
    """集中管理 sensevoice 节点的全部配置项与默认值"""

    def __init__(self):
        # 读取 sensevoice 配置节点，缺失时回退到空字典
        cfg = defaultConfig().get_config().get('sensevoice', {})

        # 功能开关
        self.enabled = cfg.get('enabled', False)

        # 服务端地址
        self.server_url = cfg.get('server_url', 'ws://127.0.0.1:10095/')

        # 识别协议参数
        self.mode = cfg.get('mode', '2pass')
        self.language = cfg.get('language', 'auto')
        self.itn = cfg.get('itn', True)

        # 用户身份与声纹
        self.username = cfg.get('username', '访客')
        self.target_speakers = cfg.get('target_speakers', [])
        self.speaker_threshold = cfg.get('speaker_threshold', 0.2)

        # 音频基础参数（固定 16k 单声道）
        self.rate = 16000
        self.channels = 1
        self.chunk_size_ms = cfg.get('chunk_size_ms', 200)
        self.chunk = int(self.rate * self.chunk_size_ms / 1000)

        # 说话状态检测阈值
        self.energy_threshold = cfg.get('vad_energy_threshold', 400)
        self.silence_threshold = cfg.get('silence_threshold', 2.0)

        # 断句合并延迟
        self.merge_delay = cfg.get('merge_delay', 1.0)

        # 热词列表
        self.hotwords = cfg.get('hotwords', [])

        # 连接保活与重连
        self.ping_interval = cfg.get('ping_interval', 20)
        self.ping_timeout = cfg.get('ping_timeout', 60)
        self.max_reconnect_attempts = cfg.get('max_reconnect_attempts', 5)
