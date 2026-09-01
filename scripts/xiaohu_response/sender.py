# -*- coding: utf-8 -*-
# scripts/xiaohu_response/sender.py
# 筱狐必回机器人：发送层封装
#
# 复用主项目 TBNapCatCore 的发送能力，核心是 send_group_at_text
# （构造独立 at 段 + text 段，有效 @ 对方）。不改主项目代码。

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class XHSender:
    """发送封装：@ 文本 / 纯文本 / 图片"""

    def __init__(self, log):
        self.log = log
        # 主项目门面（单例，复用其连接与发送层）
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        self.core = TBNapCatCore()

    def send_at(self, group_id, at_qq, text: str):
        """有效 @ 某人发送（at 段 + 空格文本段）"""
        try:
            self.core.send_group_at_text(group_id, at_qq, text)
            self.log.info(f"[发送] @{at_qq} → 群 {group_id}: {(text or '')[:30]}")
        except Exception:
            self.log.exception(f"发送 @ 文本失败: 群 {group_id} @{at_qq}")

    def send_text(self, group_id, text: str):
        """普通群文本发送（兜底，一般不用）"""
        try:
            self.core.send_group_text(group_id, text)
            self.log.info(f"[发送] 群 {group_id}: {text[:30]}")
        except Exception:
            self.log.exception(f"发送文本失败: 群 {group_id}")

    def send_image(self, group_id, file_path: str):
        """发送群图片（表情 gif 用）"""
        try:
            self.core.send_group_image(group_id, file_path)
            self.log.info(f"[发送] 群 {group_id} 图片: {file_path}")
        except Exception:
            self.log.exception(f"发送图片失败: 群 {group_id}")
