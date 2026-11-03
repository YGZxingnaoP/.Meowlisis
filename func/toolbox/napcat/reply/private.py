# -*- coding: utf-8 -*-
# func/toolbox/napcat/reply/private.py
# QQ 私聊回复链路（自 func/toolbox/qq_response.py 原样拆出，行为不变）

import random
from threading import Thread
from func.pipeline.id_signup import display_name

class PrivateReplyMixin:
    """QQ 私聊回复链路"""
    # ==================== QQ 私聊回复链路 ====================
    def receive_qq(self, ext_name: str, user_id: str, text: str, short_memory: list):
        """接收 QQ 私聊消息：记录记忆 → napcat 独立 LLM 回复 → 回发 QQ

        - `ext_name`：QQ 显示名（外部显示名，只作认人线索；首次建档时用来填 nickname）；
        - `user_id`：QQ 号（查/建内部编号的唯一依据）；
        - 身份一律以内部编号为准，任何环节禁止用昵称/QQ号顶替身份键。
        """
        # 0. 私聊回复开关
        if not self.napcat_config.private_reply_enabled:
            return
        # 0.2 qq 通道：外部账号（QQ号）→ 反查 meowid；查不到就建档（建档时用 QQ 显示名填一次 nickname）
        from func.pipeline.id_signup import IdSignupBridge
        meowid = IdSignupBridge().meowid_of_account("qq", str(user_id or ""), str(ext_name or ""))
        if not meowid:
            self.log.error(f"[NapCat私聊] 无法确定 meowid，放弃回复：ext_account={user_id} ext_name={ext_name}")
            return
        # 昵称只用于展示：唯一规则 display_name()，禁止把内部编号当昵称传给下游
        nickname_display = display_name(meowid)
        # 短期记忆里的说话人：先用 meowid 对应的昵称，没有再回退 QQ 真实昵称（ext_name）
        mem_name = IdSignupBridge().nickname_of(meowid) or str(ext_name or "").strip()
        # 私聊统一上下文：meowid=唯一身份键，nickname=展示名
        base_context = {"channel": "qq", "message_type": "private", "target_id": str(user_id),
                        "user_id": str(user_id), "ext_account": str(user_id),
                        "ext_name": ext_name, "meowid": meowid, "nickname": nickname_display}
        # 机器人消息（如幻梦）：仅参与当轮上下文，不写入任何记忆文件
        is_bot = self._is_bot(user_id)
        # 0.6 Creeper 接龙彩蛋（命中则直接回复，不再走 LLM）
        if not is_bot:
            try:
                from func.toolbox.napcat.creeper import TBCreeper
                replies = TBCreeper().route(text, f"qq_private_{user_id}",
                                            nickname_display, str(user_id))
                if replies:
                    for seg in replies:
                        self.napcat_core.send_private_text(user_id, seg)
                    return
            except Exception:
                self.log.exception("Creeper 彩蛋异常")
        # 0.5 数据库关键词匹配（仅私聊，机器人消息不进入）
        if not is_bot:
            try:
                from func.pipeline.msg_database import MsgDatabaseBridge
                MsgDatabaseBridge().send_to_database(text, meowid)
            except Exception:
                self.log.exception("QQ 私聊 → database 处理异常")
        # 0.7 改图判定（画完 window 秒内的下一条消息：判断是否在上一张图上改）
        #     改图入口第 4 参是「内部编号」（flux_painter 用编号做记忆键），与插件入口不同
        if not is_bot:
            try:
                from func.toolbox.flux_painter.edit_router import TBFluxEditRouter
                if TBFluxEditRouter().try_handle(f"qq_private_{user_id}", "directed", text,
                                                 dict(base_context), meowid):
                    return
            except Exception:
                self.log.exception("QQ 私聊改图判定异常")
        # 0.75 插件消息拦截（插件自己判定，零 LLM）：第 4 参是「昵称」
        if not is_bot:
            try:
                from func.toolbox.plugins.manager import PluginManager
                if PluginManager().route_qq(f"qq_private_{user_id}", text,
                                            dict(base_context), nickname_display):
                    return
            except Exception:
                self.log.exception("QQ 私聊插件拦截异常")
        # 0.8 napcat 意图分析：命中工具则走工具流程（结果发 QQ），跳过原 LLM 回复
        if not is_bot:
            try:
                from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
                if TBNapcatAnalysis().decide_and_run(text, meowid, dict(base_context), short_memory):
                    return
            except Exception:
                self.log.exception("QQ 私聊意图分析异常")
        # 0.9 QQ 私聊破甲审查：命中色情则写 toolbox_rulebreak 桥接（仅真实用户消息）
        nsfw_triggered = False
        if not is_bot:
            try:
                from func.catbrain.rules_break.rules_break import TBRulesBreak
                nsfw_triggered = TBRulesBreak().check_and_store_qq(f"qq_private:{user_id}", meowid, text, short_memory)
            except Exception:
                self.log.exception("QQ 私聊破甲审查异常")
        # 1. 记录用户消息短期记忆（qq_response，加前缀）
        if self.napcat_config.short_mem_enabled and not is_bot:
            self.short_memory.save({
                "role": "user",
                "content": f"【来自QQ，{mem_name}的消息】{text}",
                "type": "qq_response",
            }, self.napcat_config.short_mem_rounds)
        # 2. 记录用户消息长期记忆（默认关闭）
        if not is_bot:
            self.napcat_ltmem.record_user(meowid, text, name=ext_name)
        # 2.5 QQ 导演（私聊）：只判断要不要起一段戏 / 要不要收，不碰回复链
        director_session = ""
        if not is_bot:
            try:
                from func.toolbox.napcat.director.core import QQDirectorCore
                director_session = QQDirectorCore.session_private(user_id)
                QQDirectorCore().before_turn(
                    director_session, "private",
                    short_memory=short_memory, current_text=text)
            except Exception:
                self.log.exception("QQ 导演私聊判断异常")
        # 3. napcat 独立 LLM 回复（流式短句回传发送）
        _pace = self._make_pacer("private")
        final_text = self.napcat_llm.send_to_llm(
            meowid, user_id, text, short_memory,
            on_segment=lambda seg: self.napcat_core.send_private_text(user_id, seg, _pace(seg)),
            nsfw=nsfw_triggered, quote=self._take_quote("private", user_id, text),
        )
        # 4. 记录 AI 回复短期记忆（AI 自己说的话不加来源前缀）
        if final_text and self.napcat_config.short_mem_enabled and not is_bot:
            self.short_memory.save({
                "role": "assistant",
                "content": final_text,
                "type": "qq_response",
            }, self.napcat_config.short_mem_rounds)
        # 5. 记录 AI 回复长期记忆（默认关闭）
        if final_text and not is_bot:
            self.napcat_ltmem.record_ai(meowid, final_text, name=ext_name)
        # 5.5 QQ 导演推进（私聊）：这一句说出去就算走了一步
        if final_text and director_session:
            try:
                from func.toolbox.napcat.director.core import QQDirectorCore
                QQDirectorCore().advance(director_session)
            except Exception:
                self.log.exception("QQ 导演私聊推进异常")
        # 6. 表情触发（概率 = 配置概率 + 好感度）
        if final_text:
            self._maybe_send_emote(meowid, user_id, text, final_text, short_memory)
        # 7. 后置情绪更新（异步，与主链路一致，更新最新情绪/性格）
        if final_text:
            Thread(target=self._update_emotion_async, args=(text, final_text), daemon=True).start()

    def _make_pacer(self, channel: str = "private"):
        cfg = self.napcat_config
        conf = cfg.pace_conf(channel) if hasattr(cfg, "pace_conf") else {}
        enabled = bool(conf.get("enabled", True))
        ms = max(0, int(conf.get("ms_per_char", 55) or 0))
        jitter = float(conf.get("jitter", 0.25) or 0)
        extra = float(conf.get("sentence_extra", 0.2) or 0)
        cap = float(conf.get("max_seconds", 2.5) or 0)
        first = float(conf.get("first_delay", 0.35) or 0)
        import random as _random
        state = {"done": 0.0, "first": True}

        def pace(seg: str) -> float:
            if not enabled:
                return 0.0
            s = str(seg or "")
            body = s.strip()
            if state["first"] and first > 0:
                want = first * (1 + _random.uniform(-0.2, 0.2))
                state["first"] = False
            elif len(body) <= 2:
                want = 0.0
            else:
                want = len(s) * ms / 1000.0
                if body.endswith(("。", "？", "！", ".", "?", "!")):
                    want += extra
                elif body.endswith(("，", ",", "、", "；", ";")):
                    want += extra * 0.3
                want *= (1 + _random.uniform(-jitter, jitter))
            want = min(max(0.0, want), max(0.0, cap - state["done"]))
            state["done"] += want
            return state["done"]

        return pace

    def _take_quote(self, scope: str, key, current=None):
        cfg = self.napcat_config
        conf = cfg.quote_conf(scope) if hasattr(cfg, "quote_conf") else {}
        if not bool(conf.get("enabled", True)):
            return None
        try:
            from func.toolbox.napcat.message.quote_store import TBQuoteStore
            return TBQuoteStore().take(scope, key, current)
        except Exception:
            return None
