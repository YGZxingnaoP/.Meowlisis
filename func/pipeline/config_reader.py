# -*- coding: utf-8 -*-
# func/pipeline/config_reader.py
# 配置总线：启动时读取完整配置，按节点分发给各模块 config

from func.config.default_config import defaultConfig
from func.tools.singleton_mode import singleton


@singleton
class ConfigReader:
    """配置读取总线：统一持有完整配置字典，供各模块按节点请求"""

    def __init__(self):
        # 启动时读取一次完整配置（不热重载）
        self._root = defaultConfig().get_config()

    def get(self, node: str = None, default=None):
        """按节点名获取配置：node 为 None 返回完整字典，否则返回对应节点（缺省返回空 dict）"""
        if node is None:
            return self._root
        return self._root.get(node, default if default is not None else {})

    def get_all(self) -> dict:
        """获取完整配置字典"""
        return self._root
