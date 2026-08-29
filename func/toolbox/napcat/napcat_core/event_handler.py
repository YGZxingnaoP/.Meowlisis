# -*- coding: utf-8 -*-
# func/toolbox/napcat/napcat_core/event_handler.py
# NapCat 事件处理：私聊 / 群聊 / 戳一戳的业务路由

import json
import threading


class TBNapCatEventHandler:
    """把 NapCat 事件解析后路由到对应业务（缓冲 / 视觉 / 黑名单 / 戳一戳）。

    依赖：解析模块（get_message / get_record / get_group_message）、发送层（api_client）、
    缓冲层（buffer）。本类不直接持有连接状态，发送与群名解析都经 api_client。
    """

    def __init__(self, log, config, get_message, get_record, get_group_message,
                 api_client, buffer):
        self.log = log
        self.config = config
        self.get_message = get_message
        self.get_record = get_record
        self.get_group_message = get_group_message
        self.api_client = api_client
        self.buffer = buffer
        # 群名缓存（group_id -> group_name），避免每条消息重复调 API
        self._group_name_cache = {}
        self._group_name_lock = threading.Lock()

    # ==================== 私聊消息处理（聚合缓冲） ====================
    def _handle_private_message(self, event: dict):
        """解析私聊消息并送入聚合缓冲（延迟合并后统一交给 AI）"""
        try:
            # QQ excuse 等待路由（绑定用户）：正在等待该用户回复时优先消费，不走正常回复
            try:
                _uid = event.get("user_id") or (event.get("sender") or {}).get("user_id")
                from func.toolbox.napcat.message.get_message import TBGetMessage
                _parsed = TBGetMessage().parse(event)
                _text = (_parsed or {}).get("text", "") or ""
                if _text.strip():
                    from func.toolbox.napcat.excuse_router import TBNapcatExcuseRouter
                    _router = TBNapcatExcuseRouter()
                    if _router.route(_router.private_key(str(_uid or "")), _text.strip()):
                        self.log.info(f"[NapCat] 私聊 excuse 等待命中，消费: {_text[:20]}")
                        return
                    # 海龟汤拦截（游戏激活时全权处理，缓冲前）
                    from func.toolbox.turtle_soup.turtle_soup_core import TBTurtleSoupCore
                    if TBTurtleSoupCore().route_qq_private(str(_uid or ""), _text.strip()):
                        self.log.info(f"[NapCat] 海龟汤拦截命中，消费: {_text[:20]}")
                        return
            except Exception:
                pass
            # 私聊回复开关
            if not self.config.private_reply_enabled:
                return
            # 消息打断戳一戳计数（私聊）
            try:
                user_id = event.get("user_id") or (event.get("sender") or {}).get("user_id")
                from func.toolbox.napcat.poke_detector import TBPokeDetector
                TBPokeDetector().on_interrupt("private", str(user_id or ""))
            except Exception:
                pass
            # 图片检测：私聊发图必看（不再做 vision_decide 判断）
            from func.toolbox.napcat.image.image_search import TBImageSearch
            images = TBImageSearch.extract_images(event.get("message"))
            if images:
                user_id = event.get("user_id") or (event.get("sender") or {}).get("user_id")
                self_id = event.get("self_id")
                username = str((event.get("sender") or {}).get("nickname") or user_id or "")
                # 图片消息自带文本 + 此前待发送的聚合文本（先文本后图片 → 合并一次性看图回复，不走 LLM）
                # 单发图片无文本时 text 为空，不向上检索填充文本
                image_text = TBImageSearch.text_from_segments(event.get("message"))
                pending_text = self.buffer._take_pending_text(str(user_id))
                text = "，".join(t for t in (pending_text, image_text) if t and t.strip())
                # 短期记忆（QQ 历史）作为视觉上下文传输，保证看图能结合对话背景
                short_memory = self.get_record.fetch(str(user_id), self_id)
                # 图片落地本地缓存区 + 动图抽帧（避免直接用带鉴权的 url）
                from func.toolbox.meowvision.config import TBVisionConfig
                cache_dir = TBVisionConfig().cache_dir
                image_paths = TBImageSearch.prepare_for_vision(images, cache_dir)
                if image_paths:
                    from func.toolbox.napcat.vision_active.vision import TBNapCatVisionActive
                    # 幻梦（机器人）发的图不写记忆，其余用户图正常写记忆
                    is_bot = self._is_bot_user(user_id)
                    result = TBNapCatVisionActive().process(
                        image_paths, text, username,
                        need_description=True, write_memory=not is_bot,
                        history_messages=short_memory,
                    )
                    vision_reply = (result.get("reply") or "").strip()
                    if vision_reply:
                        self.api_client.send_private_text(str(user_id), vision_reply)
                        self.log.info(f"[视觉] 私聊图片视觉回复已发: {vision_reply[:30]}")
                    else:
                        self.log.warning(f"[视觉] 私聊图片视觉回复为空，未发送（图片 {len(image_paths)} 张）")
                return
            parsed = self.get_message.parse(event)
            if not parsed or not parsed.get("text"):
                return
            self_id = event.get("self_id")
            self.buffer._buffer_message(parsed, self_id)
        except Exception:
            self.log.exception("处理私聊消息异常")

    # ==================== 戳一戳处理 ====================
    def _handle_poke(self, event: dict):
        """处理戳一戳通知：检测连续被戳，达到阈值触发角色发牢骚

        NapCat 戳一戳事件字段：
        - 群聊：post_type=notice, sub_type=poke, group_id, user_id(戳的人), target_id(被戳的人)
        - 私聊：post_type=notice, sub_type=poke, user_id(戳的人), sender_id, target_id(被戳的人)
        无 message_type 字段，通过是否有 group_id 区分群/私聊。
        """
        try:
            target_id = str(event.get("target_id", "") or "")
            self_id = str(event.get("self_id", "") or "")
            # 只有被戳对象是自己才计数
            if target_id and self_id and target_id != self_id:
                return

            group_id = str(event.get("group_id", "") or "")
            if group_id:
                # 群聊戳一戳
                message_type = "group"
                session_id = group_id
                user_id = str(event.get("user_id", "") or "")
            else:
                # 私聊戳一戳
                message_type = "private"
                user_id = str(event.get("user_id", "") or event.get("sender_id", "") or "")
                session_id = user_id

            from func.toolbox.napcat.poke_detector import TBPokeDetector
            triggered = TBPokeDetector().on_poke(message_type, session_id, user_id)
            if triggered:
                # 补充 event 里的 user_id 供发牢骚发送使用
                event["_poke_user_id"] = user_id
                self._poke_complain(message_type, session_id, event)
        except Exception:
            self.log.exception("处理戳一戳异常")

    def _poke_complain(self, message_type: str, session_id: str, event: dict):
        """触发戳一戳发牢骚：LLM 流式生成牢骚（仅前后置词），分段发送并写记忆"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM

            # 仅前后置词（后置词=被戳烦了骂他们），不含角色卡/用户记忆/日期/摘要
            system_prompt = SystemPromptBridge().get_poke_prompt()

            # 发送回调：流式分段发到群/私聊
            def on_segment(seg: str):
                if not seg:
                    return
                if message_type == "group":
                    self.api_client.send_group_text(session_id, seg)
                else:
                    user_id = str(event.get("_poke_user_id", "") or event.get("user_id", "") or "")
                    if user_id:
                        self.api_client.send_private_text(user_id, seg)

            messages = [
                {"role": "user", "content": "你被连续戳了好几下，快发牢骚骂他们。"},
            ]
            complain_text = TBNapCatLLM().reply_stream(system_prompt, messages, on_segment)
            if not complain_text:
                return

            # 写记忆（assistant 身份）
            from func.pipeline.short_memory import ShortMemory
            if message_type == "group":
                ShortMemory().save({
                    "role": "assistant",
                    "content": f"【来自QQ群的消息】{complain_text}",
                    "type": "qq_groupchat",
                }, self.config.group_memory_limit)
            else:
                ShortMemory().save({
                    "role": "assistant",
                    "content": f"【来自QQ的消息】{complain_text}",
                    "type": "qq_response",
                }, self.config.short_mem_rounds)
            self.log.info(f"[戳一戳] 已发牢骚: {complain_text[:30]}")
        except Exception:
            self.log.exception("戳一戳发牢骚失败")

    # ==================== 群聊消息处理 ====================
    def _handle_group_message(self, event: dict):
        """解析群聊消息并送入 TBoxCore.receive_group（黑名单/主动回复逻辑在内部处理）"""
        try:
            # QQ excuse 等待路由（绑定群 + 用户）：正在等待该用户回复时优先消费，不走正常回复
            try:
                _gid = event.get("group_id")
                _uid = event.get("user_id") or (event.get("sender") or {}).get("user_id")
                from func.toolbox.napcat.groupchat.get_group_message import TBGetGroupMessage
                _parsed = TBGetGroupMessage().parse(event)
                _text = (_parsed or {}).get("text", "") or ""
                if _text.strip() and _gid is not None and _uid is not None:
                    from func.toolbox.napcat.excuse_router import TBNapcatExcuseRouter
                    _router = TBNapcatExcuseRouter()
                    _key = _router.group_key(str(_gid), str(_uid))
                    if _router.route(_key, _text.strip()):
                        self.log.info(f"[NapCat] 群聊 excuse 等待命中，消费: {_text[:20]}")
                        return
                    # 海龟汤拦截（群聊，游戏激活时全权处理，缓冲前）
                    from func.toolbox.turtle_soup.turtle_soup_core import TBTurtleSoupCore
                    if TBTurtleSoupCore().route_qq_group(str(_gid), str(_uid), _text.strip()):
                        self.log.info(f"[NapCat] 海龟汤群聊拦截命中，消费: {_text[:20]}")
                        return
            except Exception:
                pass
            # 消息打断戳一戳计数（群聊）
            try:
                group_id = event.get("group_id")
                from func.toolbox.napcat.poke_detector import TBPokeDetector
                TBPokeDetector().on_interrupt("group", str(group_id or ""))
            except Exception:
                pass
            parsed = self.get_group_message.parse(event)
            if not parsed:
                return
            group_id = str(parsed.get("group_id", ""))
            group_name = self._resolve_group_name(group_id)
            parsed["group_name"] = group_name
            # 顺带记录 QQ 号 → 昵称映射（供 @ 触发时加载稳定用户档案）
            try:
                from func.toolbox.napcat.groupchat.user_nickname import TBUserNicknameMap
                sender = (event.get("sender") or {})
                TBUserNicknameMap().observe(
                    parsed.get("user_id"),
                    card=sender.get("card", ""),
                    nickname=sender.get("nickname", ""),
                )
            except Exception:
                self.log.exception("记录 QQ 昵称映射失败")
            if self.get_group_message.in_blacklist(group_name):
                self.log.info(f"[NapCat群聊] 群 {group_name}({group_id}) 命中黑名单，跳过")
                return
            from func.toolbox.toolbox_core import TBoxCore
            TBoxCore().receive_group(parsed)
        except Exception:
            self.log.exception("处理群聊消息异常")

    # ==================== 杂项 ====================
    def _dump_event(self, data: dict):
        """把原始事件追加写入 .temp/napcat_raw_events.jsonl（一行一个 JSON）"""
        try:
            import os
            os.makedirs(".temp", exist_ok=True)
            with open(".temp/napcat_raw_events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _is_bot_user(self, user_id) -> bool:
        """判断发送者是否为已配置的群机器人（如幻梦）"""
        try:
            uid = str(user_id or "")
            for qq in (self.config.group_bots or {}).values():
                if str(qq) == uid:
                    return True
        except Exception:
            pass
        return False

    def _resolve_group_name(self, group_id: str) -> str:
        """解析群名（缓存 + get_group_info API）"""
        with self._group_name_lock:
            cached = self._group_name_cache.get(group_id)
            if cached:
                return cached
        name = ""
        try:
            ret = self.api_client.call_action_sync("get_group_info", {"group_id": int(group_id)})
            if isinstance(ret, dict):
                data = ret.get("data") or {}
                name = str(data.get("group_name", "") or "").strip()
        except Exception:
            self.log.exception(f"获取群信息失败: {group_id}")
        if not name:
            name = group_id
        with self._group_name_lock:
            self._group_name_cache[group_id] = name
        return name
