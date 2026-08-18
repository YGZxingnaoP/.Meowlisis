# -*- coding: utf-8 -*-
# func/toolbox/minecraft/config.py
# Minecraft 日志读取配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class MinecraftConfig:
    """集中管理 minecraft 节点日志读取参数与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('minecraft', {})

        # 是否启用日志读取
        self.enabled = cfg.get('enabled', False)

        # 日志文件路径
        self.log_path = cfg.get('log_path', '')

        # 日志编码
        self.encoding = cfg.get('encoding', 'utf-8')

        # 检查间隔（秒）
        self.check_interval = cfg.get('check_interval', 5.0)

        # 是否使用玩家名作为 UID
        self.use_player_name = cfg.get('use_player_name', False)

        # 固定用户名
        self.username_fixed = cfg.get('username_fixed', 'MinecraftSever')

        # 是否在提示词中包含玩家名
        self.include_player_name_in_prompt = cfg.get('include_player_name_in_prompt', True)

        # 玩家白名单（空 = 不过滤）
        self.filter_players = cfg.get('filter_players', [])

        # 是否忽略自己发送的消息
        self.ignore_self_messages = cfg.get('ignore_self_messages', False)
