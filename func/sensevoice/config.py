# -*- coding: utf-8 -*-
# func/sensevoice/config.py - SenseVoice 配置读取

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class SenseVoiceConfig:
    """sensevoice 配置节点封装（读取 config.yml）"""

    def __init__(self):
        cfg = ConfigReader().get('sensevoice', {})
        self.enabled = cfg.get('enabled', False)
        self.server_url = cfg.get('server_url', 'ws://127.0.0.1:10095/')
        self.mode = cfg.get('mode', '2pass')
        self.language = cfg.get('language', 'auto')
        self.itn = cfg.get('itn', True)
        self.target_speakers = cfg.get('target_speakers', [])
        self.speaker_threshold = cfg.get('speaker_threshold', 0.2)
        self.energy_threshold = cfg.get('vad_energy_threshold', 400)
        self.interrupt_threshold = cfg.get('interrupt_threshold', 800)
        self.silence_threshold = cfg.get('silence_threshold', 2.0)
        self.merge_delay = cfg.get('merge_delay', 1.0)
        self.hotwords = cfg.get('hotwords', [])
        self.replace_rules = cfg.get('replace_rules', {})
        self.ping_interval = cfg.get('ping_interval', 20)
        self.ping_timeout = cfg.get('ping_timeout', 30)
