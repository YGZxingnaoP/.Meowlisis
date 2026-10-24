# -*- coding: utf-8 -*-
# func/config/default_config.py
# 配置入口：启动时先确认 config.yml 在，缺了就从 config.example.yml 生成一份，然后再读

import os
import shutil

from func.config.config_base import ConfigBase
from func.tools.singleton_mode import singleton

CONFIG_FILE = "config.yml"
EXAMPLE_FILE = "config.example.yml"


@singleton
class defaultConfig:
    def __init__(self):
        # 加载配置
        self._ensure_config()
        self.config = ConfigBase(CONFIG_FILE, "utf-8").get_config()

    @staticmethod
    def _ensure_config():
        """config.yml 缺失时用 config.example.yml 生成一份；模板也没有就抛错说清怎么办"""
        if os.path.exists(CONFIG_FILE):
            return
        if os.path.exists(EXAMPLE_FILE):
            shutil.copyfile(EXAMPLE_FILE, CONFIG_FILE)
            print("=" * 64)
            print(f"没找到 {CONFIG_FILE}，已按 {EXAMPLE_FILE} 生成了一份。")
            print(f"请打开 {CONFIG_FILE} 填好自己的密钥（api_key 之类），再重新启动。")
            print("=" * 64)
            return
        raise RuntimeError(
            f"没找到 {CONFIG_FILE}，也没找到 {EXAMPLE_FILE}，无法生成配置。\n"
            f"请把 {EXAMPLE_FILE} 放到程序根目录，或者直接放一份填好的 {CONFIG_FILE}，再启动。"
        )

    def get_config(self):
        return self.config

    def reload(self):
        """重读 config.yml（热重载用：不再做缺失兜底，避免运行中意外生成文件）"""
        self.config = ConfigBase(CONFIG_FILE, "utf-8").get_config()
        return self
