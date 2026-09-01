# -*- coding: utf-8 -*-
# scripts/xiaohu_response/memory_writer.py
# 筱狐必回机器人：记忆回写层
#
# 复刻主项目 qq_response.py 中 @ 触发回复链路的记忆逻辑（100% 复用主项目实现）：
#   - 用户档案记录：始终执行（不跟随 ltmem_enabled 开关）
#   - 用户短期记忆：type=qq_response，上限 short_mem_rounds
#   - AI 回复短期记忆：type=qq_response，上限 short_mem_rounds
#   - 长期记忆：受 ltmem_enabled 开关控制
#   - 群性质发送计数：TBGroupInfo().on_ai_sent
# 所有文件与主项目共用（.temp/public_short_mem.json / character/info/users_info/ 等）。

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class XHMemoryWriter:
    """记忆回写封装：供回复引擎在正确时机调用"""

    def __init__(self, log, config):
        self.log = log
        self.config = config
        from func.pipeline.short_memory import ShortMemory
        from func.pipeline.toolbox_ltmem import NapcatLtMemBridge
        from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
        self.short_memory = ShortMemory()
        self.ltmem = NapcatLtMemBridge()
        self.group_info = TBGroupInfo()

    def record_user_message(self, reply_username: str, text: str):
        """记录用户消息：用户档案（始终）+ 用户短期记忆（受开关）"""
        if not reply_username:
            return
        # 1. 用户档案记录（始终执行，不跟随长期记忆开关）
        try:
            self.ltmem.record_user(reply_username, text)
        except Exception:
            self.log.exception("记录用户档案失败")
        # 2. 用户短期记忆（type=qq_response，与主项目 @ 触发一致）
        if self.config.short_mem_enabled:
            try:
                self.short_memory.save({
                    "role": "user",
                    "content": f"【来自QQ群的消息】{text}",
                    "type": "qq_response",
                }, self.config.short_mem_rounds)
            except Exception:
                self.log.exception("记录用户短期记忆失败")

    def record_ai_reply(self, reply_username: str, final_text: str):
        """记录 AI 回复：短期记忆（受开关）+ 长期记忆（受 ltmem 开关）"""
        if not final_text:
            return
        if self.config.short_mem_enabled:
            try:
                self.short_memory.save({
                    "role": "assistant",
                    "content": f"【来自QQ群的消息】{final_text}",
                    "type": "qq_response",
                }, self.config.short_mem_rounds)
            except Exception:
                self.log.exception("记录 AI 短期记忆失败")
        try:
            self.ltmem.record_ai(reply_username, final_text)
        except Exception:
            self.log.exception("记录 AI 长期记忆失败")

    def on_group_sent(self, group_id: str, group_name: str):
        """AI 在群里发了一条消息：群性质发送计数（满 group_info_interval 触发概括）"""
        try:
            self.group_info.on_ai_sent(group_id, group_name)
        except Exception:
            self.log.exception("群性质计数失败")
