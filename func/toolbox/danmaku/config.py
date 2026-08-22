# -*- coding: utf-8 -*-
# func/toolbox/danmaku/config.py
# B站弹幕模块（混合型工具）全部配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBDanmakuConfig:
    """集中管理 danmaku 节点的全部配置项与默认值。

    节点结构（config.yml）：
        danmaku:
          blivedm: {...}          # 连接参数（开放平台 + web SESSDATA）
          read_aloud_enabled:     # 是否朗读弹幕
          read_aloud_mode:        # 普通弹幕朗读模板随机/固定
          sc_llm_reply_enabled:   # SC 是否也走 LLM 回复
          multi_danmaku_strategy: # 多条弹幕选取算法
          multi_danmaku_char_limit: # all 策略回退阈值
          gift_thanks_enabled:    # 礼物/舰长感谢总开关
          active_send: {...}      # 主动发弹幕开关与冷却
    """

    def __init__(self):
        cfg = ConfigReader().get('danmaku', {})

        # ========== 连接与开关（blivedm） ==========
        blivedm = cfg.get('blivedm', {}) or {}

        # 弹幕模块总开关
        self.enabled = bool(blivedm.get('enabled', False))

        # 直播间编号
        self.room_id = blivedm.get('room_id', '')

        # B站登录会话 SESSDATA（web 端监听 / HTTP API 复用）
        self.SESSDATA = blivedm.get('sessdata', '')

        # csrf 校验令牌（发弹幕/表情必需，与 SESSDATA 同账号）
        self.bili_jct = blivedm.get('bili_jct', '')

        # B站开放平台开发者密钥
        self.ACCESS_KEY_ID = blivedm.get('ACCESS_KEY_ID', '')
        self.ACCESS_KEY_SECRET = blivedm.get('ACCESS_KEY_SECRET', '')

        # 开放平台创建的项目 ID
        self.APP_ID = blivedm.get('APP_ID', '')

        # 主播身份码
        self.ROOM_OWNER_AUTH_CODE = blivedm.get('ROOM_OWNER_AUTH_CODE', '')

        # ========== 弹幕朗读 ==========
        # 是否朗读弹幕原文（配置开关，2.1.1）
        self.read_aloud_enabled = bool(cfg.get('read_aloud_enabled', True))
        # 普通弹幕朗读模板：random / template1 / template2 / template3
        self.read_aloud_mode = cfg.get('read_aloud_mode', 'random')

        # ========== SC 回复 ==========
        # SC 是否也走 LLM 回复（默认关闭，仅朗读）
        self.sc_llm_reply_enabled = bool(cfg.get('sc_llm_reply_enabled', False))

        # ========== 多条弹幕选取算法 ==========
        # longest / newest / all / random
        self.multi_danmaku_strategy = cfg.get('multi_danmaku_strategy', 'random')
        # all 策略总字符数超过该值时回退 longest
        self.multi_danmaku_char_limit = int(cfg.get('multi_danmaku_char_limit', 200))

        # ========== 礼物/舰长感谢 ==========
        # 礼物/舰长感谢总开关（点赞感谢已移除）
        self.gift_thanks_enabled = bool(cfg.get('gift_thanks_enabled', True))

        # ========== 主动发送（active_sender 触发型工具） ==========
        as_cfg = cfg.get('active_send', {}) or {}
        self.active_send_enabled = bool(as_cfg.get('enabled', True))
        self.active_send_cooldown = int(as_cfg.get('cooldown', 60))
