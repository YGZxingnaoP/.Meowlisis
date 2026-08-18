# -*- coding: utf-8 -*-
# func/toolbox/danmaku/config.py
# B站弹幕配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class DanmakuConfig:
    """集中管理 danmaku.blivedm 节点的直播间与开放平台参数"""

    def __init__(self):
        cfg = ConfigReader().get('danmaku', {}).get('blivedm', {})

        # 直播间编号
        self.room_id = cfg.get('room_id', '')

        # B站登录会话 SESSDATA
        self.SESSDATA = cfg.get('sessdata', '')

        # B站开放平台开发者密钥
        self.ACCESS_KEY_ID = cfg.get('ACCESS_KEY_ID', '')
        self.ACCESS_KEY_SECRET = cfg.get('ACCESS_KEY_SECRET', '')

        # 开放平台创建的项目 ID
        self.APP_ID = cfg.get('APP_ID', '')

        # 主播身份码
        self.ROOM_OWNER_AUTH_CODE = cfg.get('ROOM_OWNER_AUTH_CODE', '')
