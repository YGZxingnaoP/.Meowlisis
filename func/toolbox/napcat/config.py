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
        # 调试：是否把原始事件落盘到 .temp/napcat_raw_events.jsonl（用于拿群机器人消息样本）
        self.debug_event_dump = cfg.get('debug_event_dump', False)

        # 角色账号名（群聊里 @该昵称 触发立即回复；同时用于识别自身消息）
        self.self_nickname = cfg.get('self_nickname', '')

        # 私聊回复开关（默认开启）
        self.private_reply_enabled = cfg.get('private_reply_enabled', True)
        # 群聊回复开关（默认开启）
        self.group_reply_enabled = cfg.get('group_reply_enabled', True)
        # 群聊主动回复（按消息更新次数判断是否插话）开关
        self.group_active_enabled = cfg.get('group_active_enabled', True)

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
        self.thinking_level = cfg.get('thinking_level', 'medium')
        # 回复字数（默认10，严格上限 = 该值 + 10）
        self.reply_word_count = cfg.get('reply_word_count', 10)

        # ========== 表情模块 ==========
        # 表情发送总开关
        self.emote_enabled = cfg.get('emote_enabled', True)
        # 表情触发基础概率（百分比，最终概率 = 基础概率 + 好感度）
        self.emote_probability = cfg.get('emote_probability', 30)
        # 表情文件目录
        self.emote_dir = cfg.get('emote_dir', '.NapCat/EmoteLab')

        # ========== 群聊模块（接口型，自发进行） ==========
        # 群聊名称黑名单（命中则不接收该群消息，默认空）
        self.group_blacklist = cfg.get('group_blacklist', []) or []
        # 群聊历史拉取条数（get_group_record 向上获取，默认 50）
        self.group_history_limit = cfg.get('group_history_limit', 50)
        # 群聊主动回复触发基数（更新 N 次后由 AI 判断是否插话）
        self.group_reply_base = cfg.get('group_reply_base', 6)
        # 触发基数的抖动比例（±20%）
        self.group_reply_jitter = cfg.get('group_reply_jitter', 0.2)
        # AI 输出 pass（不插话）允许连续循环次数（默认 1，之后再打标必须发送）
        self.group_pass_rounds = cfg.get('group_pass_rounds', 1)
        # qq_groupchat 类型短期记忆最多容纳条数（默认 10）
        self.group_memory_limit = cfg.get('group_memory_limit', 10)
        # 群性质概括触发间隔（AI 在该群每发送多少条消息触发一次，默认 100）
        self.group_info_interval = cfg.get('group_info_interval', 100)
        # 群性质概括：拉取最近 N 条作为上下文（默认 50）
        self.group_info_recent = cfg.get('group_info_recent', 50)
        # 群性质概括：50 条之外向上再取多少条内随机抽取（默认 200）
        self.group_info_sample_range = cfg.get('group_info_sample_range', 200)
        # 每群单独配置（group_id -> {reply_base, pass_rounds, ...}，缺省回退全局）
        self.group_per_group = cfg.get('group_per_group', {}) or {}
        # 群机器人 QQ 号映射（可选，如 {"幻梦": "123456789"}，便于识别群机器人）
        self.group_bots = cfg.get('group_bots', {}) or {}

        # ========== 主动发送（active_sender 触发型工具，受 toolcalls 控制） ==========
        as_cfg = cfg.get('active_sender', {}) or {}
        # 是否启用主动发送（AI 主动给好友/群发消息、文件、链接）
        self.active_send_enabled = as_cfg.get('enabled', True)
        # 两次主动发送最小间隔（秒）
        self.active_send_cooldown = as_cfg.get('cooldown', 60)

        # ========== 戳一戳（poke） ==========
        # 是否启用戳一戳发牢骚
        self.poke_enabled = cfg.get('poke_enabled', True)
        # 群聊连续被戳多少次触发（默认 5）
        self.poke_group_trigger = cfg.get('poke_group_trigger', 5)
        # 私聊连续被戳多少次触发（默认 1）
        self.poke_private_trigger = cfg.get('poke_private_trigger', 1)
        # 戳一戳计数冷却时间（秒），超过该时间未再被戳则计数归零
        self.poke_cooldown = cfg.get('poke_cooldown', 30)

    # ==================== 群聊逐群配置 ====================
    def group_config(self, group_id: str) -> dict:
        """返回某群的合并配置（全局默认 + 该群覆盖项）"""
        per = {}
        if isinstance(self.group_per_group, dict):
            item = self.group_per_group.get(str(group_id)) or {}
            if isinstance(item, dict):
                per = item
        base = {
            "reply_base": self.group_reply_base,
            "reply_jitter": self.group_reply_jitter,
            "pass_rounds": self.group_pass_rounds,
        }
        base.update(per)
        return base

    def group_reply_base_for(self, group_id: str) -> int:
        return int(self.group_config(group_id).get("reply_base", self.group_reply_base))

    def group_pass_rounds_for(self, group_id: str) -> int:
        return int(self.group_config(group_id).get("pass_rounds", self.group_pass_rounds))
