# -*- coding: utf-8 -*-
# scripts/xiaohu_response/config.py
# 筱狐必回机器人：配置中心
#
# 目标：监听「上理GM电竞方块幻想MC社团分部」群（174127179）中
#       用户「熙欧_筱狐」（3382794370）的消息，必回且有效 @ 对方。
# 配置来源：主项目 config.yml 的 napcat 节点（经 TBNapCatConfig 读取），
#           硬编码目标群/用户只放本文件，改这里即可。

import os
import sys

# 项目根目录：scripts/xiaohu_response/config.py -> 上级 x2 = D:\.Meowlisis
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ==================== 目标（硬编码，改这里即可） ====================
GROUP_ID = "174127179"            # 上理GM电竞方块幻想MC社团分部
GROUP_NAME = "上理GM电竞方块幻想MC社团分部"
TARGET_USER_ID = "3382794370"     # 熙欧_筱狐
TARGET_USER_NAME = "熙欧_筱狐"

# 机器人自身 QQ（NapCat 实际登录账号，事件里 self_id 动态兜底，这里仅作参考）
SELF_ID = "3781465760"


class XHConfig:
    """脚本运行配置：聚合主项目 napcat 配置 + 脚本专属参数"""

    def __init__(self):
        # 目标常量（模块级定义，这里映射为实例属性，供各模块统一经 config 访问）
        self.GROUP_ID = GROUP_ID
        self.GROUP_NAME = GROUP_NAME
        self.TARGET_USER_ID = TARGET_USER_ID
        self.TARGET_USER_NAME = TARGET_USER_NAME
        self.SELF_ID = SELF_ID

        # 主项目 napcat 配置（单例，读取 config.yml 的 napcat 节点，不改动主项目）
        from func.toolbox.napcat.config import TBNapCatConfig
        self.napcat = TBNapCatConfig()

        # ===== 缓冲参数（与主项目 func/toolbox/napcat/napcat_core/buffer.py 完全一致）=====
        self.buffer_wait_min = 5.0        # BUFFER_WAIT_MIN
        self.buffer_wait_max = 15.0       # BUFFER_WAIT_MAX
        self.buffer_max_rounds = 10       # BUFFER_MAX_ROUNDS

        # ===== 表情 gif 触发（开启，与主项目 _maybe_send_group_emote 一致）=====
        self.emote_enabled = True

    @property
    def ws_url(self) -> str:
        return self.napcat.ws_url

    @property
    def access_token(self) -> str:
        return self.napcat.access_token

    @property
    def group_reply_word_count(self) -> int:
        return int(self.napcat.group_reply_word_count or 10)

    @property
    def short_mem_rounds(self) -> int:
        return int(self.napcat.short_mem_rounds or 10)

    @property
    def short_mem_enabled(self) -> bool:
        return bool(self.napcat.short_mem_enabled)
