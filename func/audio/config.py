# -*- coding: utf-8 -*-
# func/audio/config.py
# 音频采集配置（多源：每个源独立开关与设备）

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton

DEFAULT_SOURCES = {
    'mic': {'type': 'mic', 'enabled': True, 'device_index': -1},
    'loopback': {'type': 'loopback', 'enabled': False, 'device_index': -1},
}


@singleton
class AudioConfig:
    """集中管理 audio 节点配置：多个采集源 + 音频基础参数"""

    def __init__(self):
        cfg = ConfigReader().get('audio', {})

        # 音频基础参数（固定 16k 单声道）
        self.rate = int(cfg.get('rate', 16000))
        self.channels = int(cfg.get('channels', 1))
        self.chunk_size_ms = int(cfg.get('chunk_size_ms', 300))
        self.chunk = int(self.rate * self.chunk_size_ms / 1000)

        # 重采样质量档：sinc_best / sinc_medium / sinc_fastest / linear / zero_order_hold
        self.resample_converter = cfg.get('resample_converter', 'sinc_medium')
        # 是否优先按目标采样率直接打开设备（免重采样；设备不支持时自动回退）
        self.prefer_native_rate = bool(cfg.get('prefer_native_rate', False))

        # 采集源：{id: {type, enabled, device_index}}
        self.sources = cfg.get('sources', {}) or {}
        if not self.sources:
            self.sources = DEFAULT_SOURCES

    def source_config(self, source_id: str) -> dict:
        """返回指定源的配置（补全默认值）"""
        default = {
            'type': 'mic',
            'enabled': False,
            'device_index': -1,
            'allow_interrupt': True,
            'speaker_verify': True,
            'username': '主人的电脑',
        }
        cfg = dict(default)
        cfg.update(self.sources.get(source_id, {}) or {})
        return cfg
