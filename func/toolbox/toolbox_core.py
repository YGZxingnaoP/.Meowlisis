# -*- coding: utf-8 -*-
# func/toolbox/toolbox_core.py
# Toolbox 核心调度：整合 pipeline 桥接，统一分发输入与输出

from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.config import TBoxConfig
from func.toolbox.analysis import TBoxAnalysis
from func.toolbox.get_prompt import TBoxGetPrompt
from func.pipeline.sensevoice_toolbox import SenseVoiceToolboxBridge
from func.pipeline.toolbox_tts import ToolboxTtsBridge
from func.pipeline.toolbox_ltmem import ToolboxLtMemBridge
from func.pipeline.toolbox_llm import ToolboxLLMBridge
from func.pipeline.napcat_llm import NapcatLLMBridge
from func.pipeline.napcat_group_llm import NapcatGroupLLMBridge
from func.pipeline.napcat_ltmem import NapcatLtMemBridge
from func.pipeline.short_memory import ShortMemory
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.napcat_core import TBNapCatCore


@singleton
class TBoxCore:
    """Toolbox 总入口：持有各 pipeline 桥接与父级分析器，统一分发"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBoxConfig()
        self.analysis = TBoxAnalysis()
        self.get_prompt = TBoxGetPrompt()
        self.sensevoice_toolbox = SenseVoiceToolboxBridge()
        self.toolbox_tts = ToolboxTtsBridge()
        self.toolbox_ltmem = ToolboxLtMemBridge()
        self.toolbox_llm = ToolboxLLMBridge()
        self.napcat_llm = NapcatLLMBridge()
        self.napcat_group_llm = NapcatGroupLLMBridge()
        self.napcat_ltmem = NapcatLtMemBridge()
        self.short_memory = ShortMemory()
        self.napcat_config = TBNapCatConfig()
        self.napcat_core = TBNapCatCore()
        # 视觉模块回传回调：视觉回复先回传 toolbox_core，再由其转发 TTS
        try:
            from func.toolbox.meowvision.vision_core import TBVisionCore
            TBVisionCore().set_reply_callback(self.forward_vision_reply)
        except Exception:
            self.log.exception("设置 MeowVision 回传回调失败")

    def receive(self, text: str, username: str):
        """接收输入内容（来自 pipeline），交给 analysis 决策调用工具。

        双通道：主 LLM 已快速回复，工具分析无工具时静默，避免重复回复。
        """
        self.analysis.decide(text, username)

    def forward_vision_reply(self, text: str):
        """接收 MeowVision 视觉模块回传的回复，通过 pipeline 转发给 TTS 合成（分段流式）"""
        self.toolbox_tts.send_stream(text, source="toolbox")

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
        # 0.8 napcat 意图分析：命中工具则走工具流程（结果发 QQ），跳过原 LLM 回复
        if not is_bot:
            try:
                from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
                qq_context = {"message_type": "private", "target_id": str(user_id), "user_id": str(user_id)}
                if TBNapcatAnalysis().decide_and_run(text, username, qq_context, short_memory):
                    return
            except Exception:
                self.log.exception("QQ 私聊意图分析异常")
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

    # ==================== 群聊回复链路 ====================
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

        # 提前提取图片（供 @ 缓冲协调与后续普通图片检测复用）
        from func.toolbox.napcat.image.image_search import TBImageSearch
        images = TBImageSearch.extract_images(raw_message)

        # @ 触发时重置该群主动回复计数（@ 回复后主动插话重新计时，保持原行为）
        if at_self:
            from func.toolbox.napcat.groupchat.napcat_active import TBNapCatActive
            TBNapCatActive().reset_group(group_id)

        # 1.5 群聊 @ 聚合缓冲协调（@ 后等待该用户后续消息，等待策略与私聊共用，仅检测该用户）
        has_buffer = self.napcat_core.group_buffer_exists(group_id, user_id)

        if at_self and not images:
            # 纯 @ 或 @ + 文字（无图片）：进入缓冲等待后续消息
            old = self.napcat_core.buffer_group_at(parsed)
            if old:
                self._flush_group_at_text(old)
            return

        if at_self and images:
            # @ + 图片：@ 了角色必看，直接走视觉；新 @ 先挤出旧缓冲
            old = self.napcat_core.take_group_buffer(group_id, user_id)
            if old:
                self._flush_group_at_text(old)
            self._reply_group_image(group_id, group_name, user_id, username, text,
                                    images, is_bot, self_id)
            return

        if has_buffer:
            # 该用户正在 @ 等待中，后续消息（仅检测该用户，不影响其他用户）
            if images:
                # 图片：取出缓冲文本 + 图片，一次性走视觉（与私聊先文本后图片一致）
                buf = self.napcat_core.take_group_buffer(group_id, user_id)
                pending_text = "，".join([t for t in (buf.get("texts") or []) if t and t.strip()]) if buf else ""
                image_text = TBImageSearch.text_from_segments(raw_message)
                merged = "，".join([t for t in (pending_text, image_text) if t and t.strip()])
                self._reply_group_image(group_id, group_name, user_id, username, merged,
                                        images, is_bot, self_id)
                return
            # 文本 / 表情：合并到缓冲，重置计时
            emote_text = self._extract_emote_text(raw_message)
            if emote_text:
                merged_parsed = dict(parsed)
                merged_parsed["text"] = "，".join([t for t in (text, emote_text) if t and t.strip()])
                self.napcat_core.add_group_buffer_text(merged_parsed)
            else:
                self.napcat_core.add_group_buffer_text(parsed)
            return

        # 2. 普通图片检测（非 @ 且无缓冲）：vision_decide 深度思考判断是否看
        if images:
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
                                            images, is_bot, self_id)
                    return
            except Exception:
                self.log.exception("群聊图片检测异常")

        # 3. 主动回复决策
        from func.toolbox.napcat.groupchat.napcat_active import TBNapCatActive
        active = TBNapCatActive()
        decision = active.on_message(parsed)
        action = decision.get("action")
        if action == "skip":
            return

        # 4. 群聊历史作为短期记忆上下文 + 群聊档案（无 @ 时替换用户档案）
        from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
        from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
        short_memory = TBGetGroupRecord().fetch(group_id, self_id)
        group_info_text = TBGroupInfo().build_prompt(group_name)

        # @ 触发时用 QQ 号解析稳定用户档案昵称（用户档案按昵称存取）
        reply_username = None
        if at_self:
            try:
                from func.toolbox.napcat.groupchat.user_nickname import TBUserNicknameMap
                reply_username = TBUserNicknameMap().resolve(user_id)
            except Exception:
                reply_username = decision.get("username")
            if not reply_username:
                reply_username = decision.get("username")
        force = bool(decision.get("force"))

        # 5. @ 触发：记录用户档案（始终）+ 用户消息短期记忆
        if at_self and not is_bot:
            # 用户档案记录：始终执行（不跟随长期记忆开关），群聊 @ 同样有效
            try:
                self.napcat_ltmem.record_user(reply_username or username, text)
            except Exception:
                self.log.exception("群聊 @ 记录用户档案失败")
        if at_self and self.napcat_config.short_mem_enabled and not is_bot:
            self.short_memory.save({
                "role": "user",
                "content": f"【来自QQ群的消息】{text}",
                "type": "qq_response",
            }, self.napcat_config.short_mem_rounds)

        # 6. 生成回复
        if action == "reply":
            # @ 或 pass 次数用尽后强制回复：流式输出
            final = self.napcat_group_llm.reply(
                reply_username, group_id, group_name, text, short_memory, group_info_text,
                on_segment=lambda seg: self.napcat_core.send_group_text(group_id, seg),
            )
            active.record_reply(group_id)
            if final and final.strip().lower() != "pass":
                self._after_group_reply(parsed, final, at_self)
                self._maybe_send_group_emote(parsed, text, final, short_memory)
            return

        # action == "decide"：AI 判断是否插话 / 是否调用 ask_group_bot / 输出 pass
        # ask_group_bot 是 napcat 独有工具，挂群聊 LLM，不进 toolbox
        ask_bot_tools = None
        try:
            from func.toolbox.napcat.groupchat.ask_group_bot import TBAskGroupBot
            ask_bot_tools = TBAskGroupBot().build_tools()
        except Exception:
            self.log.exception("构建 ask_group_bot 工具失败")

        decision_text = self.napcat_group_llm.decide(
            None, group_id, group_name, text, short_memory, group_info_text, ask_bot_tools
        )
        final = (decision_text or "").strip()
        # AI 选择调用群机器人发指令：工具已执行，不再文本回复
        if final.startswith("ASK_BOT:"):
            self.log.info(f"[NapCat群聊] AI 主动调用群机器人: {final}")
            return
        if self._is_pass(final):
            active.record_pass(group_id)
            self.log.info(f"[NapCat群聊] AI 决策 pass，不插话（群 {group_name}）")
            return
        if final:
            active.record_reply(group_id)
            # 与 message 一致：去掉逗号句号，分段发送
            from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
            for seg in TBNapCatGroupLLM.split_segments(final):
                self.napcat_core.send_group_text(group_id, seg)
            self._after_group_reply(parsed, final, at_self=False)
            self._maybe_send_group_emote(parsed, text, final, short_memory)

    # ==================== 群聊 @ 缓冲 flush ====================
    def reply_group_at(self, buf: dict, text: str):
        """群聊 @ 缓冲 flush：拉历史 + 群档案 + 记忆 + 群聊 LLM 回复 + 发群。

        - text 由缓冲计算而来（纯 @ 时为「{username}@了你」占位，否则为合并文本）；
        - 仅真实文本（非占位）才写用户档案与短期记忆，避免污染。
        """
        group_id = str(buf.get("group_id", ""))
        group_name = str(buf.get("group_name", ""))
        user_id = str(buf.get("user_id", ""))
        username = str(buf.get("username", ""))
        self_id = str(buf.get("self_id", ""))
        has_real_text = bool([t for t in (buf.get("texts") or []) if t and t.strip()])
        is_bot = self._is_bot(user_id)

        parsed = {
            "group_id": group_id,
            "group_name": group_name,
            "user_id": user_id,
            "username": username,
            "self_id": self_id,
            "at_self": True,
            "is_self": False,
            "text": text,
        }

        # 历史 + 群档案
        from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
        from func.toolbox.napcat.groupchat.group_info import TBGroupInfo
        short_memory = TBGetGroupRecord().fetch(group_id, self_id)
        group_info_text = TBGroupInfo().build_prompt(group_name)

        # 用户档案昵称（@ 触发时按 QQ 号解析稳定昵称）
        reply_username = None
        try:
            from func.toolbox.napcat.groupchat.user_nickname import TBUserNicknameMap
            reply_username = TBUserNicknameMap().resolve(user_id)
        except Exception:
            reply_username = None
        if not reply_username:
            reply_username = username

        # 仅真实文本记录用户档案 + 短期记忆
        if has_real_text and not is_bot:
            try:
                self.napcat_ltmem.record_user(reply_username or username, text)
            except Exception:
                self.log.exception("群聊 @ 记录用户档案失败")
        if has_real_text and self.napcat_config.short_mem_enabled and not is_bot:
            self.short_memory.save({
                "role": "user",
                "content": f"【来自QQ群的消息】{text}",
                "type": "qq_response",
            }, self.napcat_config.short_mem_rounds)

        # napcat 意图分析（@ 触发）：命中工具则走工具流程（结果发群），跳过原群聊 LLM 回复
        try:
            from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
            qq_context = {
                "message_type": "group",
                "target_id": group_id,
                "user_id": user_id,
                "group_name": group_name,
                "self_id": self_id,
            }
            if TBNapcatAnalysis().decide_and_run(text, reply_username, qq_context, short_memory):
                return
        except Exception:
            self.log.exception("群聊 @ 意图分析异常")

        # 流式回复
        final = self.napcat_group_llm.reply(
            reply_username, group_id, group_name, text, short_memory, group_info_text,
            on_segment=lambda seg: self.napcat_core.send_group_text(group_id, seg),
        )
        if final and final.strip().lower() != "pass":
            self._after_group_reply(parsed, final, True)
            self._maybe_send_group_emote(parsed, text, final, short_memory)

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
                           images, is_bot, self_id):
        """群聊图片视觉回复：无文本向上检索 → 落地图片 → 视觉 → 发群"""
        from func.toolbox.napcat.image.image_search import TBImageSearch
        # 无文本 → 向上检索最近群历史用户文本作为看图上下文
        if not text.strip():
            try:
                from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
                group_history = TBGetGroupRecord().fetch(group_id, self_id)
                text = TBImageSearch.gather_text_context("", group_history)
            except Exception:
                self.log.exception("群聊图片向上检索文本失败")

        # 图片落地本地缓存区 + 动图抽帧 + 张数/大小限制
        from func.toolbox.meowvision.config import TBVisionConfig
        cache_dir = TBVisionConfig().cache_dir
        image_paths = TBImageSearch.prepare_for_vision(images, cache_dir)
        if image_paths:
            from func.toolbox.napcat.vision_active.vision import TBNapCatVisionActive
            result = TBNapCatVisionActive().process(
                image_paths, text, username,
                need_description=True, write_memory=not is_bot,
            )
            vision_reply = (result.get("reply") or "").strip()
            if vision_reply:
                from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
                for seg in TBNapCatGroupLLM.split_segments(vision_reply):
                    self.napcat_core.send_group_text(group_id, seg)
                self.log.info(f"[视觉] 群图片视觉回复已发群 {group_name}: {vision_reply[:30]}")

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
            if cfg.local_llm_type == "aliyun":
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
