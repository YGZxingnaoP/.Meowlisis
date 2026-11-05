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
                    if TBTurtleSoupCore().route_qq_private(
                            str(_uid or ""), _text.strip(),
                            str((_parsed or {}).get("username", "") or "")):
                        self.log.info(f"[NapCat] 海龟汤拦截命中，消费: {_text[:20]}")
                        return
                    # 绑定指令（身份表）：命中即回结果并吃掉这条消息
                    from func.toolbox.napcat.identity.qq_cmd import TBNapcatIdentityCmd
                    if TBNapcatIdentityCmd().handle_private(
                            str(_uid or ""), _text.strip(),
                            str((event.get("sender") or {}).get("nickname") or "")):
                        self.log.info(f"[NapCat] 私聊绑定指令命中，消费: {_text[:20]}")
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
            paint_images = images or TBImageSearch.extract_images(event.get("message"), include_emoji=True)
            if images:
                user_id = event.get("user_id") or (event.get("sender") or {}).get("user_id")
                self_id = event.get("self_id")
                username = str((event.get("sender") or {}).get("nickname") or user_id or "")
                # 视觉链路按 meowid 写档案：先按 QQ 号换出编号（未绑定会建临时身份），不能拿昵称顶替
                try:
                    from func.pipeline.id_signup import IdSignupBridge
                    vision_uid = IdSignupBridge().meowid_of_account("qq", str(user_id or ""), username)
                except Exception:
                    self.log.exception("私聊图片身份解析失败")
                    vision_uid = ""
                if not vision_uid:
                    self.log.error(f"[视觉] 私聊图片身份无法识别，跳过看图: {user_id}")
                    return
                # 图片消息自带文本 + 此前待发送的聚合文本（先文本后图片 → 合并一次性看图回复，不走 LLM）
                # 单发图片无文本时 text 为空，不向上检索填充文本
                image_text = TBImageSearch.text_from_segments(event.get("message"))
                pending_text = self.buffer._take_pending_text(str(user_id))
                text = "，".join(t for t in (pending_text, image_text) if t and t.strip())
                # 图生图：带图 + 明确要求照图作画 → 交给绘画模块；否则继续走看图
                try:
                    from func.toolbox.flux_painter.img2img.router import TBFluxImg2ImgRouter
                    if TBFluxImg2ImgRouter().try_handle_qq(
                            text, images,
                            {"user_id": str(user_id or ""), "username": username,
                             "self_id": str(self_id or "")}):
                        self.log.info("[NapCat] 私聊图生图接管")
                        return
                except Exception:
                    self.log.exception("私聊图生图路由异常")
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
                        image_paths, text, vision_uid,
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
            self._resolve_quote(parsed, "private", parsed.get("user_id"),
                                has_own_image=bool(images))
            # 只发了表情/贴纸（看图链路排除）又说要画：表情也可以当参考图
            if not images and paint_images:
                try:
                    from func.toolbox.flux_painter.img2img.router import TBFluxImg2ImgRouter
                    if TBFluxImg2ImgRouter().try_handle_qq(
                            str(parsed.get("text") or ""), paint_images,
                            {"user_id": str(parsed.get("user_id") or ""),
                             "username": str(parsed.get("username") or ""),
                             "self_id": str(self_id or "")}):
                        self.log.info("[NapCat] 私聊表情图生图接管")
                        return
                except Exception:
                    self.log.exception("私聊表情图生图路由异常")
            # 引用图片：本条没带图但引用了图片 → 交给图生图判定（判定不中就继续走普通回复）
            if parsed.get("quote_images"):
                try:
                    from func.toolbox.flux_painter.img2img.router import TBFluxImg2ImgRouter
                    if TBFluxImg2ImgRouter().try_handle_qq(
                            str(parsed.get("text") or ""), parsed["quote_images"],
                            {"user_id": str(parsed.get("user_id") or ""),
                             "username": str(parsed.get("username") or ""),
                             "self_id": str(self_id or "")}):
                        self.log.info("[NapCat] 私聊引用图生图接管")
                        return
                except Exception:
                    self.log.exception("私聊引用图生图路由异常")
            self.buffer._buffer_message(parsed, self_id)
        except Exception:
            self.log.exception("处理私聊消息异常")

    def _handle_message_sent(self, event: dict):
        try:
            self_id = str(event.get("self_id") or "")
            user_id = str(event.get("user_id") or "")
            if not self_id or self_id != user_id:
                return
            mid = event.get("message_id")
            if mid is None:
                return
            from func.toolbox.napcat.message.get_message import TBGetMessage
            from func.toolbox.napcat.message.quote_store import TBSelfSentStore
            text = "".join(TBGetMessage._parse_segments(event.get("message")))
            TBSelfSentStore().remember(mid, text)
        except Exception:
            self.log.exception("处理 message_sent 异常")

    def _resolve_quote(self, parsed: dict, scope: str, key, has_own_image: bool = False):
        conf = self.config.quote_conf(scope) if hasattr(self.config, "quote_conf") else {}
        if not bool(conf.get("enabled", True)):
            return
        mid = str(parsed.get("reply_to_id") or "").strip()
        if not mid:
            return
        # 引用图片：别人发的图也要能当图生图的参考图，所以先拉原消息取图片段
        # （本条消息自己带图时不用拉：自己的图优先，省一次 get_msg）
        if not has_own_image:
            try:
                quoted = self._fetch_quote_images(mid)
                if quoted:
                    parsed["quote_images"] = quoted
            except Exception:
                self.log.exception("引用消息取图失败")
        from func.toolbox.napcat.message.quote_store import TBSelfSentStore, TBQuoteStore
        text = TBSelfSentStore().text_of(mid)
        if not text:
            return
        TBQuoteStore().put(scope, key, text, parsed.get("text"))
        parsed["reply_self"] = True

    def _fetch_quote_images(self, mid: str):
        """引用消息里的图片段（拉 get_msg 取原消息）；拿不到返回空列表

        NapCat 的引用 id 可能是负数（如 -339125345），也可能要字符串形态，
        所以这里 int / str 各试一次，并支持从 raw_message 的 CQ 码兜底抽图。
        """
        message_id = str(mid or "").strip()
        if not message_id:
            return []
        attempts = []
        try:
            attempts.append(int(message_id))
        except (TypeError, ValueError):
            pass
        attempts.append(message_id)
        for value in attempts:
            try:
                ret = self.api_client.call_action_sync("get_msg", {"message_id": value}) or {}
            except Exception:
                self.log.exception(f"[NapCat] 引用取图调用失败 id={message_id}")
                continue
            data = ret.get("data") or {}
            segments = data.get("message")
            if not isinstance(segments, list):
                segments = []
            # 引用取图不做「表情过滤」：用户引用的可能就是一张动画表情（sub_type=1），
            # 但引用行为本身就说明他要拿这张当参考图。
            images = []
            for seg in segments:
                if not isinstance(seg, dict) or seg.get("type") != "image":
                    continue
                seg_data = seg.get("data") or {}
                if str(seg_data.get("url") or seg_data.get("file") or "").strip():
                    images.append({"url": seg_data.get("url", ""), "file": seg_data.get("file", "")})
            if not images:
                images = self._cq_images(str(data.get("raw_message") or ""))
            if images:
                self.log.info(f"[NapCat] 引用取图成功 id={message_id} images={len(images)}")
                return images
            self.log.info(f"[NapCat] 引用取图未拿到图片 id={message_id} status={ret.get('status')} "
                          f"retcode={ret.get('retcode')} data_keys={list(data.keys())[:6]}")
        return []

    @staticmethod
    def _cq_images(raw: str):
        """raw_message 兜底：从 CQ 码里抽图片段（[{url, file}]）"""
        import re
        out = []
        for args in re.findall(r"\[CQ:image,([^\]]*)\]", raw or ""):
            data = {}
            for part in args.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    data[k.strip()] = v.strip().replace("&amp;", "&")
            if data:
                out.append({"url": data.get("url", ""), "file": data.get("file", "")})
        return out

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
                    "content": f"【来自QQ，{self._resolve_group_name(session_id)}的群消息】{complain_text}",
                    "type": "qq_groupchat",
                }, self.config.group_memory_limit)
            else:
                ShortMemory().save({
                    "role": "assistant",
                    "content": f"【来自QQ，{self._poke_qq_name(event)}的消息】{complain_text}",
                    "type": "qq_response",
                }, self.config.short_mem_rounds)
            self.log.info(f"[戳一戳] 已发牢骚: {complain_text[:30]}")
        except Exception:
            self.log.exception("戳一戳发牢骚失败")

    def _poke_qq_name(self, event: dict) -> str:
        """戳一戳写记忆时的说话人：先用 meowid 对应的昵称，没有再回退 QQ 真实昵称"""
        try:
            user_id = str(event.get("_poke_user_id") or event.get("user_id") or "")
            if not user_id:
                return ""
            from func.pipeline.id_signup import IdSignupBridge
            meowid = IdSignupBridge().resolve("qq", user_id)
            name = IdSignupBridge().nickname_of(meowid) if meowid else ""
            if not name:
                from func.toolbox.napcat.groupchat.user_nickname import TBUserNicknameMap
                name = TBUserNicknameMap().resolve(user_id) or ""
            return str(name or "").strip()
        except Exception:
            self.log.exception("戳一戳取昵称异常")
            return ""

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
                    if TBTurtleSoupCore().route_qq_group(
                            str(_gid), str(_uid), _text.strip(),
                            str((_parsed or {}).get("username", "") or "")):
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
            try:
                from func.toolbox.napcat.image.image_search import TBImageSearch
                _own_image = TBImageSearch.has_image(event.get("message"))
            except Exception:
                _own_image = False
            self._resolve_quote(parsed, "group", parsed.get("group_id"),
                                has_own_image=_own_image)
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
            # 绑定指令（身份表）：黑名单之后，只在被 @ 时处理，群里只放开查看与绑定类
            try:
                from func.toolbox.napcat.identity.qq_cmd import TBNapcatIdentityCmd
                sender = (event.get("sender") or {})
                _at_like = bool(parsed.get("at_self"))
                if not self._is_bot_user(parsed.get("user_id")):
                    _at_like = bool(_at_like or parsed.get("mention_self") or parsed.get("reply_self"))
                if TBNapcatIdentityCmd().handle_group(
                        str(parsed.get("user_id") or ""), group_id, str(parsed.get("text") or ""),
                        str(sender.get("nickname", "")), _at_like):
                    self.log.info("[NapCat] 群绑定指令命中，已消费")
                    return
            except Exception:
                self.log.exception("群绑定指令处理异常")
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
