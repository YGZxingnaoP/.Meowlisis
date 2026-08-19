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
                   reply_text: str, chat_record: List[dict]):
        """根据概率决定是否发送表情（触发后选表情并发送 gif）"""
        if not self.config.emote_enabled:
            return
        prob = max(0, self.config.emote_probability + self._affinity(username))
        if prob <= 0:
            return
        if random.random() * 100 >= prob:
            return
        name = self.choose.choose(username, text, reply_text, chat_record)
        if not name:
            return
        path = os.path.join(self.config.emote_dir, f"{name}.gif")
        if not os.path.exists(path):
            self.log.warning(f"表情文件不存在: {path}")
            return
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        TBNapCatCore().send_private_image(user_id, path)
        self.log.info(f"发送表情: {name}")

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
