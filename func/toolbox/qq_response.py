# -*- coding: utf-8 -*-
# func/toolbox/qq_response.py
# QQ 回复编排：从 toolbox_core 抽离的私聊/群聊完整回复链路

import random
from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.pipeline.short_memory import ShortMemory
from func.pipeline.toolbox_ltmem import NapcatLtMemBridge
from func.pipeline.toolbox_llm import NapcatLLMBridge, NapcatGroupLLMBridge
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.napcat_core import TBNapCatCore


@singleton
class TBoxQQResponse:
    """QQ 回复编排：私聊/群聊完整回复链路（原 TBoxCore 的 QQ 部分）

    由 TBoxCore 提供转发入口（receive_qq / receive_group / reply_group_at）调用，
    napcat 内部模块与 analysis 仍通过 TBoxCore 转发，保证外部调用零改动。
    """

    # 幻梦被动触发概率（硬编码）：群聊 decide 时，只要幻梦在该群发过言，
    # 就有该概率直接随机调它（替代 LLM 的「冷场」判断，冷场与累计消息矛盾）。
    BOT_TRIGGER_PROB = 0.5

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.napcat_config = TBNapCatConfig()
        self.napcat_core = TBNapCatCore()
        self.napcat_llm = NapcatLLMBridge()
        self.napcat_group_llm = NapcatGroupLLMBridge()
        self.napcat_ltmem = NapcatLtMemBridge()
        self.short_memory = ShortMemory()

    # ==================== QQ 私聊回复链路 ====================
    def receive_qq(self, username: str, user_id: str, text: str, short_memory: list):
        """接收 QQ 私聊消息：记录记忆 → napcat 独立 LLM 回复 → 回发 QQ

        回复短句由本方法提供回调发送到 NapCat，napcat/llm 不直接操作发送，
        保证 napcat 只通过 toolbox_core 与 pipeline 与项目核心交互。
        """
        # 0. 私聊回复开关
        if not self.napcat_config.private_reply_enabled:
            return
        # 机器人消息（如幻梦）：仅参与当轮上下文，不写入任何记忆文件
        is_bot = self._is_bot(user_id)
        # 0.5 数据库关键词匹配（仅私聊，机器人消息不进入）
        if not is_bot:
            try:
                from func.pipeline.msg_database import MsgDatabaseBridge
                MsgDatabaseBridge().send_to_database(text, username)
            except Exception:
                self.log.exception("QQ 私聊 → database 处理异常")
        # 0.7 改图判定（画完 window 秒内的下一条消息：判断是否在上一张图上改）
        if not is_bot:
            try:
                from func.toolbox.flux_painter.edit_router import TBFluxEditRouter
                qq_context = {"message_type": "private", "target_id": str(user_id), "user_id": str(user_id)}
                if TBFluxEditRouter().try_handle(f"qq_private_{user_id}", "directed", text, qq_context, username):
                    return
            except Exception:
                self.log.exception("QQ 私聊改图判定异常")
        # 0.8 napcat 意图分析：命中工具则走工具流程（结果发 QQ），跳过原 LLM 回复
        if not is_bot:
            try:
                from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
                qq_context = {"message_type": "private", "target_id": str(user_id), "user_id": str(user_id)}
                if TBNapcatAnalysis().decide_and_run(text, username, qq_context, short_memory):
                    return
            except Exception:
                self.log.exception("QQ 私聊意图分析异常")
        # 0.9 QQ 私聊破甲审查：命中色情则写 toolbox_rulebreak 桥接（仅真实用户消息）
        nsfw_triggered = False
        if not is_bot:
            try:
                from func.catbrain.rules_break.rules_break import TBRulesBreak
                nsfw_triggered = TBRulesBreak().check_and_store_qq(f"qq_private:{user_id}", username, text, short_memory)
            except Exception:
                self.log.exception("QQ 私聊破甲审查异常")
        # 1. 记录用户消息短期记忆（qq_response，加前缀）
        if self.napcat_config.short_mem_enabled and not is_bot:
            self.short_memory.save({
                "role": "user",
                "content": f"【来自QQ的消息】{text}",
                "type": "qq_response",
            }, self.napcat_config.short_mem_rounds)
        # 2. 记录用户消息长期记忆（默认关闭）
        if not is_bot:
            self.napcat_ltmem.record_user(username, text)
        # 3. napcat 独立 LLM 回复（流式短句回传发送）
        final_text = self.napcat_llm.send_to_llm(
            username, user_id, text, short_memory,
            on_segment=lambda seg: self.napcat_core.send_private_text(user_id, seg),
            nsfw=nsfw_triggered,
        )
        # 4. 记录 AI 回复短期记忆
        if final_text and self.napcat_config.short_mem_enabled and not is_bot:
            self.short_memory.save({
                "role": "assistant",
                "content": f"【来自QQ的消息】{final_text}",
                "type": "qq_response",
            }, self.napcat_config.short_mem_rounds)
        # 5. 记录 AI 回复长期记忆（默认关闭）
        if final_text and not is_bot:
            self.napcat_ltmem.record_ai(username, final_text)
        # 6. 表情触发（概率 = 配置概率 + 好感度）
        if final_text:
            self._maybe_send_emote(username, user_id, text, final_text, short_memory)
        # 7. 后置情绪更新（异步，与主链路一致，更新最新情绪/性格）
        if final_text:
            Thread(target=self._update_emotion_async, args=(text, final_text), daemon=True).start()

    # ==================== QQ 群聊回复链路 ====================
    def receive_group(self, parsed: dict):
        """接收 QQ 群聊消息：图片检测 → 主动回复决策 → 群聊 LLM 回复 → 回发群

        群聊回复遵循：
        - @ 触发：立即回复，并按 user/assistant 存入 qq_response；
        - 普通消息：累计到阈值后由 AI 决策（pass 则跳过），回复仅存 assistant 到 qq_groupchat。
        """
        group_id = str(parsed.get("group_id", ""))
        group_name = str(parsed.get("group_name", "") or "")
        user_id = str(parsed.get("user_id", ""))
        username = str(parsed.get("username", "") or "")
        text = str(parsed.get("text", "") or "").strip()
        self_id = str(parsed.get("self_id", "") or "")
        at_self = bool(parsed.get("at_self"))
        is_self = bool(parsed.get("is_self"))
        raw_message = parsed.get("raw_message") or []

        # 自己发的消息不处理
        if is_self:
            return

        # 机器人消息（如幻梦）：仅参与当轮上下文，不写入任何记忆文件
        is_bot = self._is_bot(user_id)

        # 观察：仅判定幻梦是否发过言 + 提取其指令名单（供 ask_group_bot 触发条件与指令提示）
        try:
            from func.toolbox.napcat.groupchat.ask_group_bot import TBAskGroupBot
            TBAskGroupBot().observe(group_id, user_id, raw_message, is_bot)
        except Exception:
            self.log.exception("ask_group_bot 观察记录失败")

        # 1. 群聊回复总开关（先于图片检测，关闭时不做任何处理）
        if not self.napcat_config.group_reply_enabled:
            return

        # 1.1 幻梦回复角色（markdown mention 提到角色 + 刚触发过）：必回复，消费式防重复
        if is_bot and parsed.get("mention_self"):
            try:
                from func.toolbox.napcat.groupchat.ask_group_bot import TBAskGroupBot
                if TBAskGroupBot().consume_trigger(group_id):
                    self._reply_bot_reply(parsed)
                    return
            except Exception:
                self.log.exception("幻梦回复评价处理异常")

        # 提前提取图片（供 @ 缓冲协调与后续普通图片检测复用）
        from func.toolbox.napcat.image.image_search import TBImageSearch
        images = TBImageSearch.extract_images(raw_message)

        # @ 触发时重置该群主动回复计数（@ 回复后主动插话重新计时，保持原行为）
        if at_self:
            from func.toolbox.napcat.groupchat.napcat_active import TBNapCatActive
            TBNapCatActive().reset_group(group_id)

        # 群聊回复协调器：统一聚合 @ / 关键词 / 主动触发，2 秒窗口内多人/多触发合并为一次回复
        coord = self._coord()

        # 1.5 @ + 图片：@ 了角色必看，直接走视觉（顺带带上该用户未决的待合并文本）
        if at_self and images:
            pending = coord.cancel_user(group_id, user_id)
            image_text = TBImageSearch.text_from_segments(raw_message)
            merged = "，".join([t for t in (pending, image_text) if t and t.strip()])
            self._reply_group_image(group_id, group_name, user_id, username, merged,
                                    images, is_bot, self_id)
            return

        # 1.6 该用户已在触发窗口内（@ / 关键词续聊）：后续消息合并，绝不另起回复
        if coord.has_user(group_id, user_id):
            if images:
                # 图片：取出待合并文本 + 图片，一次性走视觉（与私聊先文本后图片一致）
                pending = coord.take_user(group_id, user_id)
                image_text = TBImageSearch.text_from_segments(raw_message)
                merged = "，".join([t for t in (pending, image_text) if t and t.strip()])
                self._reply_group_image(group_id, group_name, user_id, username, merged,
                                        images, is_bot, self_id)
                return
            # 文本 / 表情：合并进该用户条目并重置计时
            emote_text = self._extract_emote_text(raw_message)
            merge_text = "，".join([t for t in (text, emote_text) if t and t.strip()])
            coord.add_text(group_id, user_id, merge_text)
            return

        # 1.7 @ 触发（无图）：进入协调器（窗口内后续消息合并 / 多人合并）
        if at_self:
            coord.offer({
                "group_id": group_id, "group_name": group_name, "user_id": user_id,
                "username": username, "self_id": self_id, "text": text,
                "kind": "at", "at_self": True, "has_real_text": bool(text.strip()),
            })
            return

        # 1.8 关键词命中：与 @ 完全同等待遇（进入协调器，窗口内合并；@ 等待期内不会走到这里）
        if text and self._keyword_hit(text):
            self.log.info(f"[NapCat群聊] 关键词命中，触发回复: {text[:20]}")
            coord.offer({
                "group_id": group_id, "group_name": group_name, "user_id": user_id,
                "username": username, "self_id": self_id, "text": text,
                "kind": "keyword", "at_self": True, "has_real_text": True,
            })
            return

        # 2. 普通图片检测（非 @ 且无缓冲）：[暂禁 2026-09-09] 主动判断"是否需要看图/是否回复"
        #    原逻辑：vision_decide 深度思考决定要不要看图；已临时禁用（恢复：改回 if images:）。
        #    影响：普通图片消息不再主动触发看图判断，直接落入下方正常回复决策；@+图/等待缓冲图等必看路径不受影响。
        if False and images:
            try:
                from func.toolbox.napcat.image.vision_decide import TBVisionDecide
                chat_record = None
                try:
                    from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
                    chat_record = TBGetGroupRecord().fetch(group_id, self_id)
                except Exception:
                    pass
                need_view = TBVisionDecide().should_view(text, images, chat_record, username=username)
                if need_view:
                    self._reply_group_image(group_id, group_name, user_id, username, text,
                                            images, is_bot, self_id, static_only=True)
                    return
            except Exception:
                self.log.exception("群聊图片检测异常")

        # 3. 主动回复决策：进入协调器，与其它触发（@ / 关键词）在 2 秒窗口内合并
        from func.toolbox.napcat.groupchat.napcat_active import TBNapCatActive
        decision = TBNapCatActive().on_message(parsed)
        action = decision.get("action")
        if action == "skip":
            return
        coord.offer({
            "group_id": group_id, "group_name": group_name, "user_id": user_id,
            "username": username, "self_id": self_id, "text": text,
            "kind": "active", "at_self": False, "has_real_text": bool(text.strip()),
            "force": bool(decision.get("force")), "decide": (action == "decide"),
        })

    # ==================== 群聊回复协调器 ====================
    def _coord(self):
        """获取群聊回复协调器并绑定派发回调"""
        from func.toolbox.napcat.groupchat.group_coordinator import TBGroupReplyCoordinator
        c = TBGroupReplyCoordinator()
        c.set_flush_handler(self._coordinator_flush)
        return c

    def _coordinator_flush(self, group_id: str, merged: dict):
        """协调器窗口到期：执行一次合并回复"""
        try:
            self._reply_group_merged(merged)
        except Exception:
            self.log.exception("群聊协调器回复异常")

    def _keyword_hit(self, text: str) -> bool:
        """本地关键词命中判断（子串匹配，零 LLM）"""
        if not getattr(self.napcat_config, "group_keyword_enabled", False):
            return False
        kws = getattr(self.napcat_config, "group_keywords", None) or []
        if not kws or not text:
            return False
        cs = getattr(self.napcat_config, "group_keyword_case_sensitive", False)
        t = text if cs else text.lower()
        for k in kws:
            kk = str(k) if cs else str(k).lower()
            if kk and kk in t:
                return True
        return False

    def reply_group_at(self, buf: dict, text: str):
        """群聊回复入口（@ 缓冲 flush / 重新投递）：统一进入协调器，与其它触发合并。

        - text 由调用方计算（纯 @ 时为「{username}@了你」占位，否则为合并文本）；
        - has_real_text 决定是否写用户档案与短期记忆，避免占位污染。
        """
        texts = [t for t in (buf.get("texts") or []) if t and t.strip()]
        self._coord().offer({
            "group_id": str(buf.get("group_id", "")),
            "group_name": str(buf.get("group_name", "")),
            "user_id": str(buf.get("user_id", "")),
            "username": str(buf.get("username", "")),
            "self_id": str(buf.get("self_id", "")),
            "text": text,
            "kind": "at", "at_self": True, "has_real_text": bool(texts),
        })

    # ==================== 合并回复执行 ====================
    def _reply_group_merged(self, merged: dict):
        """按合并结果派发回复：directed（@/关键词）或 active（主动插话）"""
        gid = str(merged.get("group_id", "") or "")
        group_name = str(merged.get("group_name", "") or "")
        self_id = str(merged.get("self_id", "") or "")
        mode = str(merged.get("mode") or "active")
        merged_text = str(merged.get("merged_text") or "")
        participants = merged.get("participants") or []
        at_users = merged.get("at_users") or []
        if mode == "at":
            self._reply_group_directed(gid, group_name, self_id, merged_text, participants, at_users)
        else:
            self._reply_group_active(gid, group_name, self_id, merged_text, participants,
                                     bool(merged.get("force")))

    def _reply_group_directed(self, gid: str, group_name: str, self_id: str, merged_text: str,
                              participants: list, at_users: list):
        """@ / 关键词合并回复：改图判定 → 意图分析（工具）→ 破甲 → 流式回复"""
        primary = (at_users[0] if at_users else (participants[0] if participants else {})) or {}
        primary_uid = str(primary.get("user_id", "") or "")
        primary_name = str(primary.get("username", "") or "")

        # 改图判定（画完 120s 内的下一条完整 @/关键词消息；命中则续画并结束）
        try:
            from func.toolbox.flux_painter.edit_router import TBFluxEditRouter
            qq_context = {"message_type": "group", "target_id": gid, "group_id": gid,
                          "group_name": group_name, "self_id": self_id, "user_id": primary_uid}
            if TBFluxEditRouter().try_handle(f"qq_group_{gid}", "directed", merged_text,
                                             qq_context, primary_name):
                return
        except Exception:
            self.log.exception("群聊改图判定异常")

        from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
        from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
        short_memory = TBGetGroupRecord().fetch(gid, self_id)
        group_info_text = TBGroupInfo().build_prompt(group_name)

        # 稳定档案昵称
        reply_username = self._resolve_username(primary_uid) or primary_name

        # 记录各参与者用户档案 + 短期记忆（仅真实文本，机器人跳过）
        for p in participants:
            if not p.get("has_real_text"):
                continue
            uid = str(p.get("user_id", "") or "")
            ptext = str(p.get("text", "") or "")
            if not ptext.strip() or self._is_bot(uid):
                continue
            rn = self._resolve_username(uid) or str(p.get("username", "") or "")
            try:
                self.napcat_ltmem.record_user(rn, ptext)
            except Exception:
                self.log.exception("群聊记录用户档案失败")
            if self.napcat_config.short_mem_enabled:
                self.short_memory.save({
                    "role": "user",
                    "content": f"【来自QQ群的消息】{ptext}",
                    "type": "qq_response",
                }, self.napcat_config.short_mem_rounds)

        # 意图分析（工具：天气/新闻/待办/唱歌/海龟汤/画图等）
        try:
            from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
            qq_context = {"message_type": "group", "target_id": gid, "user_id": primary_uid,
                          "group_name": group_name, "self_id": self_id}
            if TBNapcatAnalysis().decide_and_run(merged_text, reply_username, qq_context, short_memory):
                return
        except Exception:
            self.log.exception("群聊意图分析异常")

        # 破甲审查
        nsfw_triggered = False
        try:
            from func.catbrain.rules_break.rules_break import TBRulesBreak
            nsfw_triggered = TBRulesBreak().check_and_store_qq(
                f"qq_group:{gid}", reply_username, merged_text, short_memory)
        except Exception:
            self.log.exception("QQ 群聊破甲审查异常")

        final = self.napcat_group_llm.reply(
            reply_username, gid, group_name, merged_text, short_memory, group_info_text,
            on_segment=lambda seg: self.napcat_core.send_group_text(gid, seg),
            nsfw=nsfw_triggered,
        )
        if final and final.strip().lower() != "pass":
            parsed = {"group_id": gid, "group_name": group_name, "user_id": primary_uid,
                      "username": primary_name, "at_self": True}
            self._after_group_reply(parsed, final, True)
            self._maybe_send_group_emote(parsed, merged_text, final, short_memory)

    def _reply_group_active(self, gid: str, group_name: str, self_id: str, merged_text: str,
                            participants: list, force: bool):
        """主动插话合并回复：force 直接回复；否则幻梦概率触发 + AI decide（可 pass）"""
        from func.toolbox.napcat.groupchat.napcat_active import TBNapCatActive
        from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
        from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
        active = TBNapCatActive()
        primary = (participants[0] if participants else {}) or {}
        username = str(primary.get("username", "") or "")
        parsed = {"group_id": gid, "group_name": group_name,
                  "user_id": str(primary.get("user_id", "") or ""), "username": username,
                  "at_self": False}

        short_memory = TBGetGroupRecord().fetch(gid, self_id)
        group_info_text = TBGroupInfo().build_prompt(group_name)

        if force:
            final = self.napcat_group_llm.reply(
                None, gid, group_name, merged_text, short_memory, group_info_text,
                on_segment=lambda seg: self.napcat_core.send_group_text(gid, seg),
            )
            active.record_reply(gid)
            if final and final.strip().lower() != "pass":
                self._after_group_reply(parsed, final, at_self=False)
                self._maybe_send_group_emote(parsed, merged_text, final, short_memory)
            return

        # 硬编码概率触发幻梦（替代 LLM 的「冷场」判断）
        try:
            from func.toolbox.napcat.groupchat.ask_group_bot import TBAskGroupBot
            _prob_bot = TBAskGroupBot()
            _prob_qq = _prob_bot.resolve_bot_qq("幻梦")
            if _prob_qq and _prob_bot.was_used(gid, _prob_qq) \
                    and random.random() < self.BOT_TRIGGER_PROB:
                _cmds = _prob_bot.merged_commands().get("幻梦") or []
                if _cmds:
                    _cmd = random.choice(_cmds)
                    _res = _prob_bot.execute_forced(gid, "幻梦", _cmd)
                    self.log.info(f"[NapCat群聊] 概率触发幻梦: {_res}")
                    active.record_reply(gid)
                    return
        except Exception:
            self.log.exception("概率触发幻梦失败")

        ask_bot_tools = None
        try:
            from func.toolbox.napcat.groupchat.ask_group_bot import TBAskGroupBot
            ask_bot_tools = TBAskGroupBot().build_tools()
        except Exception:
            self.log.exception("构建 ask_group_bot 工具失败")

        decision_text = self.napcat_group_llm.decide(
            None, gid, group_name, merged_text, short_memory, group_info_text, ask_bot_tools
        )
        final = (decision_text or "").strip()
        if final.startswith("ASK_BOT:"):
            self.log.info(f"[NapCat群聊] AI 主动调用群机器人: {final}")
            active.record_reply(gid)
            return
        if self._is_pass(final):
            active.record_pass(gid)
            self.log.info(f"[NapCat群聊] AI 决策 pass，不插话（群 {group_name}）")
            return
        if final:
            active.record_reply(gid)
            from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
            for seg in TBNapCatGroupLLM.split_segments(final):
                self.napcat_core.send_group_text(gid, seg)
            self._after_group_reply(parsed, final, at_self=False)
            self._maybe_send_group_emote(parsed, merged_text, final, short_memory)

    def _resolve_username(self, user_id: str) -> str:
        """按 QQ 号解析稳定用户档案昵称（失败返回空串）"""
        try:
            from func.toolbox.napcat.groupchat.user_nickname import TBUserNicknameMap
            return TBUserNicknameMap().resolve(str(user_id or "")) or ""
        except Exception:
            return ""

    def _flush_group_at_text(self, buf: dict):
        """flush 被新 @ 挤出的旧缓冲（与 napcat_core 定时超时 flush 共用同一文本计算逻辑）"""
        if not buf:
            return
        texts = [t for t in (buf.get("texts") or []) if t and t.strip()]
        if not texts:
            text = f"{buf.get('username', '有人')}@了你"
        else:
            text = "，".join(texts)
        self.reply_group_at(buf, text)

    # ==================== 群聊图片视觉回复 ====================
    def _reply_group_image(self, group_id, group_name, user_id, username, text,
                           images, is_bot, self_id, static_only=False):
        """群聊图片视觉回复：无文本向上检索 → 落地图片 → 视觉 → 发群"""
        from func.toolbox.napcat.image.image_search import TBImageSearch
        from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
        # 拉取群聊短期记忆（一次拉取，两处复用：无文本补上下文 + 传给视觉模型）
        group_history = None
        try:
            group_history = TBGetGroupRecord().fetch(group_id, self_id)
        except Exception:
            self.log.exception("群聊图片拉取历史失败")

        # 无文本 → 向上检索最近群历史用户文本作为看图上下文
        if not text.strip():
            text = TBImageSearch.gather_text_context("", group_history or [])

        # 图片落地本地缓存区 + 动图抽帧 + 张数/大小限制
        from func.toolbox.meowvision.config import TBVisionConfig
        cache_dir = TBVisionConfig().cache_dir
        if static_only:
            image_paths = TBImageSearch.prepare_static_only(images, cache_dir)
        else:
            image_paths = TBImageSearch.prepare_for_vision(images, cache_dir)
        if image_paths:
            from func.toolbox.napcat.vision_active.vision import TBNapCatVisionActive
            result = TBNapCatVisionActive().process(
                image_paths, text, username,
                need_description=True, write_memory=not is_bot,
                history_messages=group_history,
            )
            vision_reply = (result.get("reply") or "").strip()
            if vision_reply:
                from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
                for seg in TBNapCatGroupLLM.split_segments(vision_reply):
                    self.napcat_core.send_group_text(group_id, seg)
                self.log.info(f"[视觉] 群图片视觉回复已发群 {group_name}: {vision_reply[:30]}")

    # ==================== 幻梦回复评价 ====================
    def _reply_bot_reply(self, parsed: dict):
        """幻梦回复角色：基于图 + 幻梦文字，简短评价/接话，发群一次（10~20 字）"""
        group_id = str(parsed.get("group_id", "") or "")
        group_name = str(parsed.get("group_name", "") or "")
        username = str(parsed.get("username", "") or "")
        self_id = str(parsed.get("self_id", "") or "")
        text = str(parsed.get("text", "") or "").strip()
        raw_message = parsed.get("raw_message") or []

        from func.toolbox.napcat.image.image_search import TBImageSearch
        from func.toolbox.meowvision.config import TBVisionConfig

        # 1. 提取幻梦的图（markdown 图 + image 段图）并落地本地（含压缩/抽帧/大小限制保护）
        images = TBImageSearch.extract_markdown_images(raw_message) + TBImageSearch.extract_images(raw_message)
        image_paths = []
        if images:
            try:
                image_paths = TBImageSearch.prepare_for_vision(images, TBVisionConfig().cache_dir)
            except Exception:
                self.log.exception("幻梦图片落地本地失败")

        reply = ""
        if image_paths:
            # 2. 有图：视觉看图（图 + 幻梦文字），简短评价
            from func.toolbox.napcat.vision_active.vision import TBNapCatVisionActive
            if text:
                user_message = (
                    f"幻梦回复：{text}\n"
                    f"请结合图片和这段文字，用你的角色口吻给出简短评价，字数控制在10到20字之间。"
                )
            else:
                user_message = "幻梦发来了一张图，请用你的角色口吻给出简短评价，字数严格控制在10到20字之间。"
            try:
                result = TBNapCatVisionActive().process(
                    image_paths, user_message, username,
                    need_description=False, write_memory=False,
                )
                reply = (result.get("reply") or "").strip()
            except Exception:
                self.log.exception("幻梦图片视觉回复失败")
        else:
            # 3. 无图：基于幻梦文字简短接话
            try:
                from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
                from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
                short_memory = TBGetGroupRecord().fetch(group_id, self_id)
                group_info_text = TBGroupInfo().build_prompt(group_name)
                prompt_text = f"幻梦机器人回复了：{text}\n请用你的角色口吻简短接话或评价，字数严格控制在10到20字之间。"
                reply = self.napcat_group_llm.reply(
                    username, group_id, group_name, prompt_text, short_memory, group_info_text,
                )
            except Exception:
                self.log.exception("幻梦文字回复失败")

        # 4. 发群（字数由提示词约束为 10~20 字，不做截断）
        reply = (reply or "").strip()
        if not reply:
            return
        from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
        for seg in TBNapCatGroupLLM.split_segments(reply):
            self.napcat_core.send_group_text(group_id, seg)
        self.log.info(f"[幻梦评价] 已回复 {group_name}: {reply[:30]}")

    # ==================== 辅助 ====================
    @staticmethod
    def _extract_emote_text(segments) -> str:
        """从消息段提取动画表情文本（mface 有 summary 名称），静态 face 忽略"""
        buf = ""
        for seg in segments or []:
            if isinstance(seg, dict) and seg.get("type") == "mface":
                summary = str((seg.get("data") or {}).get("summary", "") or "").strip()
                if summary:
                    buf += f"[动画表情：{summary}]"
        return buf.strip()

    @staticmethod
    def _is_pass(text: str) -> bool:
        """判断 AI 决策输出是否为 pass（容忍大小写与尾部标点）"""
        t = (text or "").strip().lower().rstrip("。.!！?？,，")
        return t == "pass"

    def _after_group_reply(self, parsed: dict, final: str, at_self: bool):
        """群聊回复后：记录 AI 回复短期记忆，并累计群性质概括计数（机器人消息不写记忆）"""
        group_id = str(parsed.get("group_id", ""))
        group_name = str(parsed.get("group_name", "") or "")
        is_bot = self._is_bot(parsed.get("user_id", ""))
        if final and self.napcat_config.short_mem_enabled and not is_bot:
            if at_self:
                self.short_memory.save({
                    "role": "assistant",
                    "content": f"【来自QQ群的消息】{final}",
                    "type": "qq_response",
                }, self.napcat_config.short_mem_rounds)
            else:
                self.short_memory.save({
                    "role": "assistant",
                    "content": f"【来自QQ群的消息】{final}",
                    "type": "qq_groupchat",
                }, self.napcat_config.group_memory_limit)
        # 群性质概括计数
        try:
            from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
            TBGroupInfo().on_ai_sent(group_id, group_name)
        except Exception:
            self.log.exception("群性质计数异常")

    def _is_bot(self, user_id) -> bool:
        """判断发送者是否为已配置的群机器人（如幻梦），机器人消息不写任何记忆文件"""
        try:
            uid = str(user_id or "")
            for qq in (self.napcat_config.group_bots or {}).values():
                if str(qq) == uid:
                    return True
        except Exception:
            pass
        return False

    def _maybe_send_emote(self, username: str, user_id: str, text: str,
                          final_text: str, short_memory: list):
        """私聊表情触发（由 toolbox_core 统一调度，napcat 内部模块不直接碰发送）"""
        try:
            from func.toolbox.napcat.message.emote_sender import TBEmoteSender
            TBEmoteSender().maybe_send(username, user_id, text, final_text, short_memory, target_type="friend")
        except Exception:
            self.log.exception("表情触发异常")

    def _maybe_send_group_emote(self, parsed: dict, text: str, final_text: str, short_memory: list):
        """群聊表情触发（复用 message 表情系统，仅发送目标为群）

        - @ 触发：概率 = 配置概率 + 好感度（与私聊一致）；
        - 非 @ 触发：概率固定 = 配置概率（不叠加好感度）。
        """
        try:
            from func.toolbox.napcat.message.emote_sender import TBEmoteSender
            group_id = str(parsed.get("group_id", ""))
            username = str(parsed.get("username", "") or "")
            at_self = bool(parsed.get("at_self"))
            TBEmoteSender().maybe_send(
                username, group_id, text, final_text, short_memory,
                target_type="group", with_affinity=at_self,
            )
        except Exception:
            self.log.exception("群聊表情触发异常")

    def _update_emotion_async(self, prompt: str, reply_text: str):
        """后置情绪更新：复用 TBEmoteController，用 toolbox port 流式调用更新在线情绪"""
        try:
            from func.toolbox.napcat.emote_controller import TBEmoteController
            from func.llm.config import LLMConfig
            ec = TBEmoteController()
            tools = ec.build_tools()
            tool_choice = ec.build_tool_choice()
            update_messages = [
                {"role": "system", "content": "根据本轮对话，判断角色当前情绪、强度与性格。"},
                {"role": "user", "content": f"用户说：{prompt}\n角色回复：{reply_text}"}
            ]
            cfg = LLMConfig()
            if cfg.local_llm_type == "gemini":
                from func.toolbox.port.gemini import TBoxGeminiLLM
                llm = TBoxGeminiLLM(cfg)
            elif cfg.local_llm_type == "aliyun":
                from func.toolbox.port.aliyun import TBoxAliyunLLM
                llm = TBoxAliyunLLM(cfg)
            else:
                from func.toolbox.port.deepseek import TBoxDeepSeekLLM
                llm = TBoxDeepSeekLLM(cfg)
            if not llm.client:
                return
            stream = llm.chat_stream(
                update_messages, tools=tools, tool_choice=tool_choice, thinking_level="off"
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.tool_calls:
                    ec.handle_stream_tool_calls(delta.tool_calls)
            if ec.tool_calls:
                ec.finalize()
        except Exception:
            self.log.exception("napcat 后置情绪更新异常")
