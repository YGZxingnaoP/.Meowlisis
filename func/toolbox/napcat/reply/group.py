# -*- coding: utf-8 -*-
# func/toolbox/napcat/reply/group.py
# QQ 群聊回复链路（@ / 关键词 / 主动 / 收尾）（自 func/toolbox/qq_response.py 原样拆出，行为不变）

import random
from func.pipeline.id_signup import display_name

class GroupReplyMixin:
    """QQ 群聊回复链路（@ / 关键词 / 主动 / 收尾）"""
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
        if not is_bot and (bool(parsed.get("mention_self")) or bool(parsed.get("reply_self"))):
            at_self = True

        # 观察：仅判定幻梦是否发过言 + 提取其指令名单（供 ask_group_bot 触发条件与指令提示）
        try:
            from func.toolbox.napcat.groupchat.ask_group_bot import TBAskGroupBot
            TBAskGroupBot().observe(group_id, user_id, raw_message, is_bot)
        except Exception:
            self.log.exception("ask_group_bot 观察记录失败")

        # 1. 群聊回复总开关（先于图片检测，关闭时不做任何处理）
        if not self.napcat_config.group_reply_enabled:
            return

        # 1.2 Creeper 接龙彩蛋（任意群成员都能往后接，命中则直接回复）
        if not is_bot and text:
            try:
                from func.toolbox.napcat.creeper import TBCreeper
                replies = TBCreeper().route(text, f"qq_group_{group_id}", username, "",
                                            allow_trigger=at_self)
                if replies:
                    for seg in replies:
                        self.napcat_core.send_group_text(group_id, seg)
                    return
            except Exception:
                self.log.exception("Creeper 彩蛋异常")

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
            if self._route_img2img(merged or text, images, parsed, group_id, group_name):
                return
            reply = self._reply_group_image(group_id, group_name, user_id, username, merged,
                                            images, is_bot, self_id)
            self._followup_arm(group_id, group_name, self_id,
                               {"user_id": user_id, "username": username},
                               merged or text, "视觉")
            self._followup_note(group_id, reply)
            return

        # 1.6 该用户已在触发窗口内（@ / 关键词续聊）：后续消息合并，绝不另起回复
        if coord.has_user(group_id, user_id):
            if images:
                # 图片：取出待合并文本 + 图片，一次性走视觉（与私聊先文本后图片一致）
                pending = coord.take_user(group_id, user_id)
                image_text = TBImageSearch.text_from_segments(raw_message)
                merged = "，".join([t for t in (pending, image_text) if t and t.strip()])
                if self._route_img2img(merged or text, images, parsed, group_id, group_name):
                    return
                self._reply_group_image(group_id, group_name, user_id, username, merged,
                                        images, is_bot, self_id)
                return
            # 文本 / 表情：合并进该用户条目并重置计时
            emote_text = self._extract_emote_text(raw_message)
            merge_text = "，".join([t for t in (text, emote_text) if t and t.strip()])
            directed_kind = ("at" if at_self else
                             ("keyword" if (text and self._keyword_hit(text)) else ""))
            coord.add_text(group_id, user_id, merge_text, directed_kind)
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

        if self._followup_feed(parsed):
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

    def _route_img2img(self, text, images, parsed, group_id, group_name):
        """带图消息先问绘画模块：是不是要以这张图作画（不是就返回 False，原样走看图）"""
        try:
            from func.toolbox.flux_painter.img2img.router import TBFluxImg2ImgRouter
            return TBFluxImg2ImgRouter().try_handle_qq(text, images, parsed, group_id, group_name)
        except Exception:
            self.log.exception("图生图路由异常")
            return False

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
        """按合并结果派发回复：directed（@/关键词）、followup（续聊）或 active（主动插话）"""
        gid = str(merged.get("group_id", "") or "")
        group_name = str(merged.get("group_name", "") or "")
        self_id = str(merged.get("self_id", "") or "")
        mode = str(merged.get("mode") or "active")
        merged_text = str(merged.get("merged_text") or "")
        participants = merged.get("participants") or []
        at_users = merged.get("at_users") or []
        if mode == "at":
            anchor = at_users[0] if at_users else (participants[0] if participants else {})
            trigger = "@" if any(str(p.get("kind") or "") == "at" for p in participants) else "关键词"
            self._followup_arm(gid, group_name, self_id, anchor, merged_text, trigger)
            final = self._reply_group_directed(gid, group_name, self_id, merged_text,
                                              participants, at_users, trigger=trigger)
            self._followup_note(gid, final)
        elif mode == "followup":
            self._reply_group_followup(gid, group_name, self_id, merged)
        else:
            self._reply_group_active(gid, group_name, self_id, merged_text, participants,
                                     bool(merged.get("force")))

    def _reply_group_directed(self, gid: str, group_name: str, self_id: str, merged_text: str,
                              participants: list, at_users: list, followup: bool = False,
                              trigger: str = "") -> str:
        """@ / 关键词合并回复：改图判定 → 意图分析（工具）→ 破甲 → 流式回复

        trigger：「@」/「关键词」/「followup」；QQ 导演只在 @ 与续聊时参与。
        """
        primary = (at_users[0] if at_users else (participants[0] if participants else {})) or {}
        primary_ext_account = str(primary.get("user_id", "") or "")
        primary_ext_name = str(primary.get("username", "") or "")
        plain_text = "\n".join([p.get("text") or "" for p in participants
                               if str(p.get("text") or "").strip()]) or merged_text

        # 身份标准：内部编号（唯一）。禁止兜底到群显示名，拿不到身份就明确失败
        from func.pipeline.id_signup import IdSignupBridge
        reply_meowid = IdSignupBridge().meowid_of_account("qq", primary_ext_account, primary_ext_name)
        if not reply_meowid:
            self.log.error(f"[NapCat群聊] 主发言人身份无法识别，放弃回复: {primary_ext_account}")
            return ""
        reply_nickname = display_name(reply_meowid)
        base_context = {"channel": "qq", "message_type": "group", "target_id": gid, "group_id": gid,
                        "group_name": group_name, "self_id": self_id, "user_id": primary_ext_account,
                        "ext_account": primary_ext_account, "ext_name": primary_ext_name,
                        "meowid": reply_meowid, "nickname": reply_nickname}

        # 改图判定（画完 120s 内的下一条完整 @/关键词消息；命中则续画并结束）
        try:
            from func.toolbox.flux_painter.edit_router import TBFluxEditRouter
            qq_context = dict(base_context)
            if TBFluxEditRouter().try_handle(f"qq_group_{gid}", "directed", plain_text,
                                             qq_context, reply_meowid):
                return ""
        except Exception:
            self.log.exception("群聊改图判定异常")

        # 插件消息拦截（插件自己判定，零 LLM；此处仅 @ / 关键词触发才会到达）
        try:
            from func.toolbox.plugins.manager import PluginManager
            qq_context = dict(base_context)
            if PluginManager().route_qq(f"qq_group_{gid}", plain_text,
                                        qq_context, reply_nickname):
                return ""
        except Exception:
            self.log.exception("群聊插件拦截异常")

        from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
        from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
        short_memory = TBGetGroupRecord().fetch(gid, self_id)
        group_info_text = TBGroupInfo().build_prompt(group_name)

        from func.pipeline.id_signup import IdSignupBridge

        # 记录各参与者用户档案 + 短期记忆（仅真实文本，机器人跳过）
        for p in participants:
            if not p.get("has_real_text"):
                continue
            ext_account = str(p.get("user_id", "") or "")
            ptext = str(p.get("text", "") or "")
            if not ptext.strip() or self._is_bot(ext_account):
                continue
            p_meowid = IdSignupBridge().meowid_of_account("qq", ext_account, str(p.get("username", "") or ""))
            if not p_meowid:
                self.log.error(f"[NapCat群聊] 参与者身份无法识别，跳过档案: {ext_account}")
                continue
            try:
                self.napcat_ltmem.record_user(p_meowid, ptext, group_name=group_name)
            except Exception:
                self.log.exception("群聊记录用户档案失败")
            if self.napcat_config.short_mem_enabled:
                self.short_memory.save({
                    "role": "user",
                    "content": f"【来自QQ，{group_name}的群消息】{ptext}",
                    "type": "qq_groupchat" if followup else "qq_response",
                }, self.napcat_config.group_memory_limit if followup
                    else self.napcat_config.short_mem_rounds)

        # 参与者记完，把当前说话人恢复成主发言人
        IdSignupBridge().set_current("qq", str(primary_ext_account or ""))

        # 意图分析（工具：天气/新闻/待办/唱歌/海龟汤/画图等）
        try:
            from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
            qq_context = {"channel": "qq", "message_type": "group", "target_id": gid,
                          "user_id": primary_ext_account, "ext_account": primary_ext_account,
                          "ext_name": primary_ext_name, "group_name": group_name, "self_id": self_id,
                          "meowid": reply_meowid, "nickname": reply_nickname}
            if TBNapcatAnalysis().decide_and_run(plain_text, reply_meowid, qq_context, short_memory):
                return ""
        except Exception:
            self.log.exception("群聊意图分析异常")

        # 破甲审查
        nsfw_triggered = False
        try:
            from func.catbrain.rules_break.rules_break import TBRulesBreak
            nsfw_triggered = TBRulesBreak().check_and_store_qq(
                f"qq_group:{gid}", reply_meowid, plain_text, short_memory)
        except Exception:
            self.log.exception("QQ 群聊破甲审查异常")

        # QQ 导演（简化版）：@ / 关键词 / 续聊都参与；冒泡不参与
        # 放在意图分析之后：工具类消息已被消费、不会走回复，不该在这里起戏。
        director_session = ""
        director_on = trigger in ("@", "关键词", "followup")
        if director_on:
            try:
                from func.toolbox.napcat.director.core import QQDirectorCore
                director_session = QQDirectorCore.session_group(gid)
                QQDirectorCore().before_turn(
                    director_session, "group", short_memory=short_memory,
                    current_text=plain_text, group_name=group_name,
                    maintain_only=(trigger == "followup"))
            except Exception:
                self.log.exception("QQ 导演群聊判断异常")

        _pace = self._make_pacer("group")
        final = self.napcat_group_llm.reply(
            reply_meowid, gid, group_name, merged_text, short_memory, group_info_text,
            on_segment=lambda seg: self.napcat_core.send_group_text(gid, seg, _pace(seg)),
            nsfw=nsfw_triggered, quote=self._take_quote("group", gid, merged_text),
            with_director=director_on,
        )
        if final and final.strip().lower() != "pass":
            parsed = {"group_id": gid, "group_name": group_name, "user_id": primary_ext_account,
                      "username": primary_ext_name, "at_self": not followup}
            self._after_group_reply(parsed, final, not followup)
            self._maybe_send_group_emote(parsed, merged_text, final, short_memory)
            if director_on and director_session:
                try:
                    from func.toolbox.napcat.director.core import QQDirectorCore
                    QQDirectorCore().advance(director_session)
                except Exception:
                    self.log.exception("QQ 导演群聊推进异常")
        return final

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

        # 插件资料：主动回复的 decide / 最终 reply 都带同一份参考
        plugin_knowledge = ""
        try:
            from func.toolbox.plugins.manager import PluginManager
            from func.toolbox.plugins.sdk import QQ_STAGE_ACTIVE_DECIDE, QQ_STAGE_ACTIVE_REPLY
            plugin_knowledge = PluginManager().qq_knowledge(
                merged_text,
                {
                    "channel": "qq", "message_type": "group",
                    "target_id": gid, "group_id": gid, "group_name": group_name,
                    "self_id": self_id,
                    "user_id": str(primary.get("user_id", "") or ""),
                    "nickname": str(primary.get("username", "") or ""),
                    "participants": participants,
                },
                QQ_STAGE_ACTIVE_REPLY if force else QQ_STAGE_ACTIVE_DECIDE,
            )
        except Exception:
            self.log.exception("主动回复读取插件资料失败")

        if force:
            _pace = self._make_pacer("group")
            final = self.napcat_group_llm.reply(
                None, gid, group_name, merged_text, short_memory, group_info_text,
                on_segment=lambda seg: self.napcat_core.send_group_text(gid, seg, _pace(seg)),
                quote=self._take_quote("group", gid, merged_text),
                extra_context=plugin_knowledge,
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
            None, gid, group_name, merged_text, short_memory, group_info_text, ask_bot_tools,
            extra_context=plugin_knowledge,
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

    def _ext_name_of_qq(self, user_id: str) -> str:
        """按 QQ 号（ext_account）取该通道的外部显示名（原逻辑来源，失败返回空串）"""
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
                    "content": final,
                    "type": "qq_response",
                }, self.napcat_config.short_mem_rounds)
            else:
                self.short_memory.save({
                    "role": "assistant",
                    "content": final,
                    "type": "qq_groupchat",
                }, self.napcat_config.group_memory_limit)
        # 群性质概括计数
        try:
            from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
            TBGroupInfo().on_ai_sent(group_id, group_name)
        except Exception:
            self.log.exception("群性质计数异常")
