# -*- coding: utf-8 -*-
# func/audio/sources/base.py
# 音频采集源抽象基类


class BaseAudioSource:
    """音频输入源统一接口：麦克风 / 电脑扬声器(loopback) / 接口注入 各自实现"""

    def __init__(self, config, log):
        self.config = config
        self.log = log

    @staticmethod
    def list_devices():
        """返回可用设备列表：[{index, name, channels, rate, kind}]"""
        raise NotImplementedError

    def open(self):
        """打开设备并准备读取"""
        raise NotImplementedError

    def read(self):
        """读取一帧 16k 单声道 int16 PCM；出错返回 None"""
        raise NotImplementedError

    def close(self):
        """关闭设备释放资源"""
        raise NotImplementedError
