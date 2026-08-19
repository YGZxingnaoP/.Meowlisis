# -*- coding: utf-8 -*-
# func/toolbox/napcat/config.py
# NapCat 全部配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBNapCatConfig:
    """集中管理 napcat 节点的全部配置项与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('napcat', {})

        # ========== 连接与开关 ==========
        # 是否启用 NapCat（客户端主动连接 NapCat 正向 WS）
        self.enabled = cfg.get('enabled', False)
        # NapCat OneBot v11 正向 WebSocket 地址
        self.ws_url = cfg.get('ws_url', 'ws://127.0.0.1:3001')
        # access_token（OneBot v11 鉴权，空表示无）
        self.access_token = cfg.get('access_token', '')

        # ========== 消息模块（接口型，自发进行） ==========
        # 拉取历史消息条数（get_record 向上获取的条数）
        self.history_limit = cfg.get('history_limit', 30)
        # 短期记忆 qq_response 类型保留轮数（1 轮 = user + assistant）
        self.short_mem_rounds = cfg.get('short_mem_rounds', 30)
        # 长期记忆开关（默认关闭）
        self.ltmem_enabled = cfg.get('ltmem_enabled', False)
        # 短期记忆开关（默认开启）
        self.short_mem_enabled = cfg.get('short_mem_enabled', True)

        # ========== LLM 回复 ==========
        # QQ 回复的深度思考级别：off/low/medium/high
        # （DeepSeek/Aliyun 当前仅有开/关两档，medium 及以上均视为开启思考）
        self.thinking_level = cfg.get('thinking_level', 'medium')

        # ========== 表情模块 ==========
        # 表情发送总开关
        self.emote_enabled = cfg.get('emote_enabled', True)
        # 表情触发基础概率（百分比，最终概率 = 基础概率 + 好感度）
        self.emote_probability = cfg.get('emote_probability', 30)
        # 表情文件目录
        self.emote_dir = cfg.get('emote_dir', '.NapCat/EmoteLab')
