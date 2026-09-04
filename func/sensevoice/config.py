# -*- coding: utf-8 -*-
# func/sensevoice/config.py
# SenseVoice 配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class SenseVoiceConfig:
    """集中管理 sensevoice 节点的全部配置项与默认值"""

    def __init__(self):
        # 从配置总线读取 sensevoice 配置节点，缺失时回退到空字典
        cfg = ConfigReader().get('sensevoice', {})

        # 功能开关
        self.enabled = cfg.get('enabled', False)

        # 服务端地址
        self.server_url = cfg.get('server_url', 'ws://127.0.0.1:10095/')
        # UDP 音频直传端口（None = 服务端口 + 1）
        self.udp_port = cfg.get('udp_port', None)

        # 识别协议参数
        self.mode = cfg.get('mode', '2pass')
        self.language = cfg.get('language', 'auto')
        self.itn = cfg.get('itn', True)

        # 用户身份与声纹
        self.target_speakers = cfg.get('target_speakers', [])
        self.speaker_threshold = cfg.get('speaker_threshold', 0.2)

        # 说话状态检测阈值（VAD，用于上报服务端说话状态）
        self.energy_threshold = cfg.get('vad_energy_threshold', 400)
        # 打断阈值（独立于说话判断阈值，用于触发 TTS 打断；应比 vad 阈值更严格）
        self.interrupt_threshold = cfg.get('interrupt_threshold', 800)
        self.silence_threshold = cfg.get('silence_threshold', 2.0)

        # 断句合并延迟
        self.merge_delay = cfg.get('merge_delay', 1.0)

        # 热词列表
        self.hotwords = cfg.get('hotwords', [])

        # 易错词替换规则：正确词 -> [错误词列表]
        self.replace_rules = cfg.get('replace_rules', {})

        # 连接保活与重连
        self.ping_interval = cfg.get('ping_interval', 20)
        self.ping_timeout = cfg.get('ping_timeout', 60)
