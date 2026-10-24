# -*- coding: utf-8 -*-
# func/config/default_config.py
# 配置入口：启动时先确认 config.yml 在；缺了就生成一份，然后读
#   * 有 config.example.yml 就复制它（用户自备的模板优先）
#   * 没有模板就写一份最小配置：绝大多数配置项在代码里都有 .get(默认值)，缺项按默认跑

import os
import shutil

from func.config.config_base import ConfigBase
from func.tools.singleton_mode import singleton

CONFIG_FILE = "config.yml"
EXAMPLE_FILE = "config.example.yml"

MINIMAL_CONFIG = """\
# 首次启动自动生成：只保留最基本的项，其余配置项使用代码内置默认值。
# 需要改什么就在下面补对应键（键名与含义见各功能模块的 config 定义）。
AiName: 喵呜
app:
  port: 1800
"""


@singleton
class defaultConfig:
    def __init__(self):
        # 加载配置
        self._ensure_config()
        self.config = ConfigBase(CONFIG_FILE, "utf-8").get_config()

    @staticmethod
    def _ensure_config():
        """config.yml 缺失时生成一份：有模板用模板，没有就写最小配置"""
        if os.path.exists(CONFIG_FILE):
            return
        if os.path.exists(EXAMPLE_FILE):
            shutil.copyfile(EXAMPLE_FILE, CONFIG_FILE)
            print("=" * 64)
            print(f"没找到 {CONFIG_FILE}，已按 {EXAMPLE_FILE} 生成了一份。")
            print(f"请打开 {CONFIG_FILE} 填好自己的密钥（api_key 之类），再重新启动。")
            print("=" * 64)
            return
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(MINIMAL_CONFIG)
        print("=" * 64)
        print(f"没找到 {CONFIG_FILE}，已生成一份最小配置。")
        print(f"其余配置项使用内置默认值；填好密钥（api_key 之类）后重新启动。")
        print("=" * 64)

    def get_config(self):
        return self.config

    def reload(self):
        """重读 config.yml（热重载用：不再做缺失兜底，避免运行中意外生成文件）"""
        self.config = ConfigBase(CONFIG_FILE, "utf-8").get_config()
        return self
