# -*- coding: utf-8 -*-
# scripts/xiaohu_response/reply_engine.py
# 筱狐必回机器人：回复编排引擎
#
# 复刻主项目 qq_response.py 的「@ 触发必回路径」（reply_group_at 的回复部分）：
#   群历史 → 群档案 → 昵称解析 → 记忆记录 → 系统提示词 → LLM 流式回复
#   → 分段回调发送 → 回复记忆回写 → 群性质计数 → 表情 gif 触发。
#
# @ 发送规则（脚本侧，不改主项目）：
#   - 筱狐消息：回复【句首】有效 @ 筱狐（第一段带 at 段，后续段纯文本）；
#   - 其它人 @ 角色：按原项目逻辑回复，纯文本不 @ 回去。
# 不做图片识别（按需求跳过视觉链路）。

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class XHReplyEngine:
    """回复编排：由缓冲 flush 回调驱动（buf, text）"""

    def __init__(self, log, config, sender, memory):
        """
        :param log: 日志器
        :param config: XHConfig
        :param sender: XHSender
        :param memory: XHMemoryWriter
        """
        self.log = log
        self.config = config
        self.sender = sender
        self.memory = memory

        from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
        from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
        from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
        from func.toolbox.napcat.groupchat.user_nickname import TBUserNicknameMap
        self.group_llm = TBNapCatGroupLLM()
        self.group_record = TBGetGroupRecord()
        self.group_info = TBGroupInfo()
        self.nickname_map = TBUserNicknameMap()

    # ==================== 对外 ====================
    def reply(self, buf: dict, text: str):
        """对合并后的消息执行完整回复链路（必回）"""
        group_id = str(buf.get("group_id", "") or "")
        group_name = str(buf.get("group_name", "") or "") or self.config.GROUP_NAME
        user_id = str(buf.get("user_id", "") or "")
        username = str(buf.get("username", "") or "") or self.config.TARGET_USER_NAME
        self_id = str(buf.get("self_id", "") or "")
        has_real_text = bool([t for t in (buf.get("texts") or []) if t and t.strip()])

        # 是否筱狐：筱狐必回且句首 @；其它人 @ 角色按原逻辑纯文本回复
        is_xiaohu = (str(user_id or "") == self.config.TARGET_USER_ID)
        at_qq = self.config.TARGET_USER_ID if is_xiaohu else None

        # 1. 群历史 → 短期记忆上下文（与主项目一致）
        short_memory = []
        try:
            short_memory = self.group_record.fetch(group_id, self_id)
        except Exception:
            self.log.exception("拉取群历史失败")

        # 2. 群性质档案（替代用户档案进提示词，与主项目一致）
        group_info_text = ""
        try:
            group_info_text = self.group_info.build_prompt(group_name)
        except Exception:
            self.log.exception("读取群性质档案失败")

        # 3. 稳定档案昵称（@ 触发时按 QQ 号解析，与主项目一致）
        reply_username = None
        try:
            reply_username = self.nickname_map.resolve(user_id)
        except Exception:
            reply_username = None
        if not reply_username:
            reply_username = username

        # 4. 用户消息记忆记录（仅真实文本，与主项目一致）
        if has_real_text:
            try:
                self.memory.record_user_message(reply_username, text)
            except Exception:
                self.log.exception("记录用户消息记忆失败")

        # 5. LLM 回复：流式分段回传；筱狐时首段带有效 @，后续段纯文本
        first_seg = [True]

        def on_segment(seg: str):
            seg = (seg or "").strip()
            if not seg:
                return
            if at_qq and first_seg[0]:
                self.sender.send_at(group_id, at_qq, seg)  # 句首有效 @
            else:
                self.sender.send_text(group_id, seg)       # 其余纯文本
            first_seg[0] = False

        final = ""
        try:
            final = self.group_llm.reply(
                reply_username, group_id, group_name, text, short_memory,
                group_info_text, on_segment=on_segment,
            )
        except Exception:
            self.log.exception("群聊 LLM 回复异常")

        # 6. 回复后：记忆回写 + 群性质计数 + 表情 gif 触发
        if final and final.strip().lower() != "pass":
            try:
                self.memory.record_ai_reply(reply_username, final)
            except Exception:
                self.log.exception("记录 AI 回复记忆失败")
            try:
                self.memory.on_group_sent(group_id, group_name)
            except Exception:
                self.log.exception("群性质计数失败")
            self._maybe_send_emote(username, group_id, text, final, short_memory)

    # ==================== 表情 gif 触发（开启） ====================
    def _maybe_send_emote(self, username: str, group_id: str, text: str,
                          final_text: str, short_memory: list):
        """与主项目 _maybe_send_group_emote 一致：概率 = 配置概率 + 好感度，发到群"""
        if not self.config.emote_enabled:
            return
        try:
            from func.toolbox.napcat.message.emote_sender import TBEmoteSender
            TBEmoteSender().maybe_send(
                username, group_id, text, final_text, short_memory,
                target_type="group", with_affinity=True,
            )
        except Exception:
            self.log.exception("表情触发异常")
