# -*- coding: utf-8 -*-
# func/toolbox/napcat/message/emote_sender.py
# 表情发送：按概率（配置概率 + 好感度）触发，选择并发送 gif 表情

import os
import random
from typing import List

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.message.emote_choose import TBEmoteChoose


class TBEmoteSender:
    """表情触发与发送：概率 = 配置概率(%) + 用户好感度"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self.choose = TBEmoteChoose()

    def maybe_send(self, username: str, user_id: str, text: str,
                   reply_text: str, chat_record: List[dict], target_type: str = "friend",
                   with_affinity: bool = True):
        """根据概率决定是否发送表情（触发后选表情并发送 gif）

        target_type: friend（私聊，发到 user_id）/ group（群聊，发到 group_id）
        with_affinity: True 时概率 = 配置概率 + 好感度；False 时概率固定 = 配置概率。
        表情选择逻辑与 message 完全共用，仅发送目标不同。
        """
        if not self.config.emote_enabled:
            self.log.info("[表情] 未启用（emote_enabled=False）")
            return
        affinity = self._affinity(username) if with_affinity else 0
        prob = max(0, self.config.emote_probability + affinity)
        if with_affinity:
            self.log.info(f"[表情] 概率计算: 配置{self.config.emote_probability}% + 好感度{affinity} = {prob}%")
        else:
            self.log.info(f"[表情] 概率计算: 固定配置概率 {prob}%（不叠加好感度）")
        if prob <= 0:
            self.log.info("[表情] 概率≤0，跳过")
            return
        roll = random.random() * 100
        if roll >= prob:
            self.log.info(f"[表情] 未命中概率（roll={roll:.1f} >= {prob}），跳过")
            return
        self.log.info(f"[表情] 命中概率（roll={roll:.1f} < {prob}），开始选择表情")
        name = self.choose.choose(username, text, reply_text, chat_record)
        if not name:
            self.log.warning("[表情] 选择表情失败（返回空），未发送")
            return
        # 严格限制：一次只发一个表情
        path = os.path.join(self.config.emote_dir, f"{name}.gif")
        if not os.path.exists(path):
            self.log.warning(f"表情文件不存在: {path}")
            return
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        if target_type == "group":
            TBNapCatCore().send_group_image(user_id, path)
        else:
            TBNapCatCore().send_private_image(user_id, path)
        self.log.info(f"发送表情: {name}（target={target_type}）")

    def _affinity(self, username: str) -> int:
        """读取用户档案好感度（character/info/users_info/{username}_latest.json）"""
        try:
            from func.catbrain.UserMemory.load_usrmem import MeowLoadUserMemory
            data = MeowLoadUserMemory().load(username)
            affinity = data.get("affinity", 0)
            if isinstance(affinity, (int, float)):
                return int(affinity)
        except Exception:
            self.log.exception("读取用户好感度失败")
        return 0
