# -*- coding: utf-8 -*-
# func/llm_active/origin/web_browse/config.py
# B站内容收集模块配置项统一管理

import os

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class AutoWebBrowseConfig:
    """集中管理 llm_active.web_browse 节点的配置项与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('llm_active', {})
        wb = cfg.get('web_browse', {}) if isinstance(cfg, dict) else {}

        # 总开关
        self.enabled = bool(wb.get('enabled', True))

        # 采集间隔（秒），默认 10 分钟
        self.interval = int(wb.get('interval', 600))

        # 缓存上限
        self.max_cache = int(wb.get('max_cache', 5))

        # 抽帧数：视频 n 等分，每段随机抽 1 帧
        self.frames = int(wb.get('frames', 5))

        # 允许主题（默认二次元/科普/游戏）
        self.allow_topics = wb.get('allow_topics', ['二次元', '科普', '游戏'])
        if not isinstance(self.allow_topics, list):
            self.allow_topics = ['二次元', '科普', '游戏']

        # 严格程度：strict=只允许列表内；loose=允许其它主题
        self.strictness = str(wb.get('strictness', 'strict')).strip().lower()

        # 是否禁止抽象视频
        self.forbid_abstract = bool(wb.get('forbid_abstract', True))

        # UP 主 mid：0 = 自动用登录态拿自己 mid；也可手动指定
        self.mid = int(wb.get('mid', 0) or 0)

        # 缓存目录（json 落盘）
        self.cache_dir = wb.get('cache_dir', os.path.join('.temp', 'web_browse_cache'))

        # 收藏目录（消费后移动到这里）
        self.collect_dir = wb.get('collect_dir', os.path.join('character', 'shared_videos'))

        # 抽帧临时目录（帧用后即删）
        self.frame_tmp_dir = wb.get('frame_tmp_dir', os.path.join('.temp', 'web_browse_frames'))
