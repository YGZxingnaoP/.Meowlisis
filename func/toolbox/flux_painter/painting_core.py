# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/painting_core.py
import os
import re
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.flux_painter.config import TBFluxPainterConfig
from func.toolbox.flux_painter.archive import TBPainterArchive
from func.toolbox.flux_painter.prompt_producer import TBPromptProducer
from func.toolbox.flux_painter.comfy_connector import create_connector, TBArtistPicker

DEFAULT_NEGATIVE = ("lowres,bad anatomy,bad hands,error,missing fingers,extra digits,"
                    "worst quality,jpeg artifacts,watermark,signature,text")
REVIEW_VOICE = "画完啦，快检查检查吧~"
REJECT_TEXT = "不给看不给看awa"


@singleton
class TBFluxPainterCore:
    """ComfyUI 文生图一次性触发总入口（live/QQ），绘画中冷却，不长期接管"""

    TOOL_NAME = "flux_paint"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBFluxPainterConfig()
        self.archive = TBPainterArchive(self.config.backup_dir)
        self.producer = TBPromptProducer(self.config)
        self.artist = TBArtistPicker(self.config)
        self._context = {}
        self._running = set()
        self._review_events = {}
        self._review_results = {}
        self._lock = threading.Lock()
        # channel -> 上一轮绘画（完整提示词缓存，供画完后 window 秒内改图续画）
        self._last_paint = {}
        self._last_lock = threading.Lock()
        self._clean_legacy_svg_memory()

    def _clean_legacy_svg_memory(self):
        """清一次旧 svg_paint 记忆条目（幂等）；此后绘画记忆统一走 config.memory_type"""
        try:
            from func.pipeline.short_memory import ShortMemory
            sm = ShortMemory()
            data = sm._read()
            cleaned = [m for m in data if (m.get("type") or "") != "svg_paint"]
            if len(cleaned) != len(data):
                sm._write(cleaned)
                self.log.info(f"[flux_painter] 已清理 {len(data) - len(cleaned)} 条旧 svg_paint 记忆")
        except Exception:
            pass

    # ==================== 上下文注入（兼容父级 dispatch） ====================
    def set_username(self, username):
        if username:
            self._context["username"] = username or ""

    def set_context(self, context):
        if context:
            self._context.update(context or {})

    def is_enabled(self):
        """功能开关"""
        return bool(self.config.enabled)

    def is_painting(self, key=None):
        """当前是否有画作任务在跑（冷却判断）"""
        if key is not None:
            return key in self._running
        return bool(self._running)

    # ==================== 改图续画（上一轮完整提示词缓存） ====================
    def _remember_paint(self, channel, request, elements, final_image, owner_uid):
        """出图成功后缓存本轮完整提示词与成品图（供改图续画）"""
        try:
            with self._last_lock:
                self._last_paint[str(channel)] = {
                    "ts": time.time(),
                    "request": str(request or ""),
                    "elements": {
                        "positive": str((elements or {}).get("positive") or ""),
                        "cinema": str((elements or {}).get("cinema") or ""),
                        "character": str((elements or {}).get("character") or ""),
                        "canvas": str((elements or {}).get("canvas") or ""),
                        "title": str((elements or {}).get("title") or ""),
                        "reply": str((elements or {}).get("reply") or ""),
                    },
                    "final_image": str(final_image or ""),
                    "owner_uid": str(owner_uid or ""),
                }
        except Exception:
            self.log.exception("[flux_painter] 缓存上一轮绘画失败")

    def get_last_paint(self, channel):
        """取上一轮绘画缓存；超出改图等待窗口则返回 None"""
        with self._last_lock:
            item = self._last_paint.get(str(channel))
        if not item:
            return None
        try:
            window = float(self.config.edit_followup_window)
        except Exception:
            window = 120.0
        if window > 0 and (time.time() - float(item.get("ts", 0))) > window:
            self.clear_last_paint(channel)
            return None
        return item

    def clear_last_paint(self, channel):
        """清掉改图缓存（不要求改图 / 窗口过期）"""
        with self._last_lock:
            self._last_paint.pop(str(channel), None)

    def continue_paint(self, channel, edit_instruction, qq_context, username=None):
        """以上一轮缓存提示词为底，执行改图（纯 txt2img 增量重绘）"""
        item = self.get_last_paint(channel)
        if not item:
            return "没有可续画的上一张图"
        base_elements = item.get("elements") or {}
        arguments = {"request": str(edit_instruction or item.get("request") or ""),
                     "topic": str(base_elements.get("title") or "改图")}
        return self._open(channel, arguments, qq_context=qq_context,
                          base_elements=base_elements,
                          base_request=str(item.get("request") or ""))

    # ==================== 父级 schema ====================
    def build_tools(self):
        """模块级触发工具定义"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "给主人画一张动漫风格插画/立绘。用户表达「画/画一张/画个…/给我画/绘一幅/想要一张图/"
                    "来张…的图/生成一张图」等意图即可调用。AI 依据需求产出提示词交给绘图引擎出图，"
                    "画完汇报（会看到画作）。无需用户提供技术细节。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string",
                                    "description": "用户原始绘画请求（必填，完整保留角色/服装/姿势/场景等描述）"},
                        "topic": {"type": "string",
                                  "description": "画面主题短词（可空）"},
                    },
                    "required": ["request"],
                },
            },
        }]

    # ==================== 开局 ====================
    def dispatch(self, name, arguments):
        """live 开局（父级 decide 命中 flux_paint 时调用）"""
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        return self._open("live", arguments, qq_context=None)

    def dispatch_qq(self, name, arguments, qq_context):
        """QQ 开局，channel 按私聊/群聊隔离"""
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        if not self.config.enabled:
            return "绘画模块未开启"
        if not qq_context:
            return "缺少 QQ 上下文"
        if str(qq_context.get("message_type", "")) == "group":
            channel = f"qq_group_{qq_context.get('target_id')}"
        else:
            channel = f"qq_private_{qq_context.get('user_id') or qq_context.get('target_id')}"
        return self._open(channel, arguments, qq_context=qq_context)

    def _open(self, channel, arguments, qq_context=None, base_elements=None, base_request=""):
        """冷却检查并起后台绘画线程（base_elements 非空时表示续画/改图）。

        冷却为「按通道」判断（channel：live / qq_private_x / qq_group_y）：
        主链路（live）与 QQ 链路各自独立出图，互不阻塞（不串行）。
        """
        if not self.config.enabled:
            return "绘画模块未开启（请在工具箱-绘画配置中启用）"
        if self.is_painting(channel):
            return "正在画画呢，画完这张再点下一张吧～"
        arguments = arguments or {}
        request = str(arguments.get("request") or self._context.get("text") or "").strip()
        if not request:
            return "想让我画什么呀？说说看～"
        username = str(arguments.get("username") or self._context.get("username") or "主人")
        # 快照 persona/记忆到 session：避免多频道并发绘画时，后到的 set_context 覆盖先开的单例上下文
        try:
            persona = str(self._context.get("system_prompt") or "")
            memories = self._context.get("short_memory")
            if not memories:
                from func.pipeline.short_memory import ShortMemory
                memories = ShortMemory().load()[-10:]
        except Exception:
            persona, memories = "", []
        session = {"channel": channel, "username": username, "request": request,
                   "topic": str(arguments.get("topic") or "").strip(),
                   "persona": persona, "memories": memories,
                   "qq_context": qq_context,
                   "base_elements": base_elements, "base_request": base_request,
                   "owner_uid": str((qq_context or {}).get("user_id") or
                                    (qq_context or {}).get("target_id") or "")}
        with self._lock:
            self._running.add(channel)
        t = threading.Thread(target=self._run, args=(session,), daemon=True,
                             name=f"flux_painter_{channel}")
        t.start()
        if qq_context:
            # QQ 渠道：AI 按需求生成开场白（异步，不阻塞开画）
            threading.Thread(target=self._qq_opener, args=(qq_context, request),
                             daemon=True).start()
        else:
            self._say(channel, "收到～我去画画啦，稍等！")
        return ("开始作画…画完把图发给你～" if qq_context
                else "开始作画…（画作完成后会展示；画板页面可实时看进度）")

    # ==================== 绘画线程 ====================
    def _run(self, session):
        """一次完整绘画：提示词→出图→归档→审查→语音/展示→记忆"""
        channel = session["channel"]
        username = session["username"]
        request = session["request"]
        # 短期记忆 + 角色系统提示词（_open 已快照进 session，防并发串号）
        memories = session.get("memories") or []
        persona = session.get("persona") or ""

        try:
            self._bcast(channel, {"type": "status", "text": "AI 正在构思画面…"})

            def on_stream(text):
                self._bcast(channel, {"type": "producing", "text": text})

            elements = self.producer.run(request, username=username,
                                         persona=persona,
                                         memory=memories,
                                         on_stream=on_stream,
                                         base_elements=session.get("base_elements"),
                                         base_request=session.get("base_request"))
            if not elements:
                self.log.error("[flux_painter] 提示词 LLM 未产出画作要素，本次绘画提前结束")
                msg = "呜……我想了半天没想好怎么画，要不再换一句试试？"
                self._say(channel, msg)
                self._bcast(channel, {"type": "status", "text": msg})
                return
            positive = str(elements["positive"] or "").strip()
            reply = str(elements["reply"] or "画好啦！")
            title = str(elements["title"] or session.get("topic") or "画")
            canvas_key = elements["canvas"]
            self.log.info(f"[flux_painter] 提示词产出 title={title} len={len(positive)} "
                          f"canvas={canvas_key} request={request[:60]!r}")

            # —— 点名角色解析：词典/缓存命中→注入标签；模型不了解才出网查证→重出一次 ——
            character = str(elements.get("character") or "").strip()
            ck = elements.get("character_known")
            char_known = True if ck is None else bool(ck)
            if character and not char_known:
                try:
                    from func.toolbox.flux_painter.char_resolver import TBRoleResolver
                    resolver = TBRoleResolver(self.config)
                    card = resolver.resolve(character)
                    if card and card.get("tags"):
                        role_prefix = ", ".join(str(t).strip()
                                                for t in card["tags"] if str(t).strip())
                        if role_prefix and not positive.lower().startswith(role_prefix[:10].lower()):
                            positive = role_prefix + ", " + positive
                            self.log.info(f"[flux_painter] 词典角色标签注入: {role_prefix[:80]}")
                    elif card:
                        role_text = resolver.card_text(card)
                        if role_text:
                            again = self.producer.run(
                                request, username=username,
                                persona=persona,
                                memory=memories,
                                on_stream=on_stream, role_card=role_text,
                                base_elements=session.get("base_elements"),
                                base_request=session.get("base_request"))
                            if again and again.get("positive"):
                                elements = again
                                positive = str(elements["positive"] or "").strip()
                                reply = str(elements["reply"] or "画好啦！")
                                title = str(elements["title"] or session.get("topic") or "画")
                                canvas_key = elements["canvas"]
                                self.log.info(f"[flux_painter] 角色查证后重出提示词 title={title} "
                                              f"card={card.get('name')}")
                except Exception:
                    self.log.exception("[flux_painter] 角色解析异常(忽略，按原提示词继续)")

            # 自然语言镜头段（producer 的 cinema 字段）附加到 tag 段之后——DiT 模型吃自然语言指令
            cinema = str(elements.get("cinema") or "").strip()
            if cinema:
                positive = (positive.rstrip() + ", " + cinema) if positive else cinema

            # 画师/风格串 + 质量前缀（脚本侧拼接，模型不输出）
            # 规则：默认不加画师 tag；只有「点名要求画师」或「要求风格化」时才会带上画师
            style_extra, artist_kw, style_on = self._style_hint(request)
            if not artist_kw and not style_extra and style_on:
                # 风格化：从引擎内画师库 .ComfyNode/artist/data.js 随机抽（带质量过滤）
                _hit = self.artist.pick_artists(1)
                if _hit:
                    artist_kw = str(_hit[0].get("name") or "").strip()
                    self.log.info(f"[flux_painter] 风格化需求 → 画师库随机抽中: {artist_kw}")
                else:
                    self.log.warning("[flux_painter] 风格化需求但画师库为空，跳过画师")
            named, manual = [], []
            if artist_kw:
                hit = None
                try:
                    if self.artist.ensure_data()[0]:
                        hit = self.artist.search(artist_kw, top=1)  # 精确优先
                except Exception:
                    hit = None
                if hit and hit[0].get("name") == artist_kw:
                    named = [hit[0]]
                elif hit:
                    manual.append("@" + str(hit[0].get("name") or "").strip())  # 点名近似→库内全名
                else:
                    manual.append("@" + artist_kw)                              # 库外/名单直接按原名
            for s in style_extra:
                s = str(s).strip()
                tag = "@" + s.lstrip("@").strip()
                if s and tag not in manual:
                    manual.append(tag)
            if artist_kw or manual:
                # 有明确画师意图（点名/风格化/@xxx）→ 只拼该画师，不再补默认画风
                parts = ["@" + str(a.get("name") or "").strip() for a in named if a.get("name")]
                parts += manual
                artist_tags = ", ".join(parts) + ", " if parts else ""
            else:
                # 默认：不加任何画师 tag（画师只在点名或要求风格化时出现）
                artist_tags = ""
            quality = self.config.quality_prefix
            final_positive = ((artist_tags + quality + ", " + positive)
                              if artist_tags else
                              ((quality + ", " + positive) if quality else positive))
            negative = self.config.negative_prompt or DEFAULT_NEGATIVE
            w, h = self._canvas_size(canvas_key)

            self._bcast(channel, {"type": "prompt",
                                  "positive": final_positive, "negative": negative,
                                  "title": title})

            # ComfyUI 出图
            ok, message = self._ensure_comfy()
            if not ok:
                self.log.error(f"[flux_painter] 绘图引擎未就绪: {message}")
                self._say(channel, f"绘图引擎没起来：{message}")
                return
            self.log.info("[flux_painter] 绘图引擎就绪")
            connector = create_connector(self.config)
            prefix = f"flux_{time.strftime('%Y%m%d_%H%M%S')}"

            def on_event(stage):
                self._bcast(channel, {"type": "progress", "text": stage})

            ok_done = False
            images, wmsg = [], ""
            # ===== 画质档位：fast 快速（现状单段采样）/ pro 清晰（04→05→06→07 全流程）=====
            mode = str(getattr(self.config, "quality_mode", "fast") or "fast").lower()
            pro_p = getattr(self.config, "pro", {}) or {}
            pro_on = bool(mode == "pro" and pro_p.get("enabled", True))
            if pro_on:
                try:
                    missing = connector.missing_pro_nodes()
                except Exception:
                    missing = []
                if missing:
                    self.log.warning(f"[flux_painter] pro 档位缺节点 {missing}，本次降级快速档"
                                     "（检查自定义节点是否已安装/加载）")
                    pro_on = False
                else:
                    self.log.info("[flux_painter] 画质档位=pro（04 基础→05 放大→06 分块→07 细化）")
            # 实时进度开关（画板显示阶段/百分比/步进）+ 历史耗时参考（ETA）
            progress_on = bool(getattr(self.config, "progress_detail", True))
            last_eta = self._last_paint_time(pro_on)
            for clip_type in ("qwen_image", "stable_diffusion", "flux2"):
                if pro_on:
                    graph = connector.build_pro_graph(final_positive, negative, w, h,
                                                      prefix=prefix, clip_type=clip_type,
                                                      params=pro_p)
                else:
                    graph = connector.build_graph(final_positive, negative, w, h,
                                                  prefix=prefix, clip_type=clip_type)
                on_event("提交任务…")
                sok, prompt_id, serr = connector.submit(graph, client_id=channel)
                if not sok and pro_on:
                    # pro 图被引擎拒绝（缺模型/节点/参数不符）→ 自动降级快速档重试，保证出图
                    self.log.warning(f"[flux_painter] pro 图提交失败，降级快速档重试: {serr[:200]}")
                    pro_on = False
                    graph = connector.build_graph(final_positive, negative, w, h,
                                                  prefix=prefix, clip_type=clip_type)
                    sok, prompt_id, serr = connector.submit(graph, client_id=channel)
                if not sok:
                    self.log.error(f"[flux_painter] 任务提交失败 clip={clip_type}: {serr[:200]}")
                    self._say(channel, f"画图任务没提交成功：{serr[:120]}")
                    return
                self.log.info(f"[flux_painter] 任务已提交 clip={clip_type} prompt_id={prompt_id}")
                self._bcast(channel, {"type": "status", "text": "AI 正在作画…"})
                t_paint0 = time.time()
                if progress_on:
                    self._bcast(channel, {"type": "progress", "stage": "已入队", "percent": 0,
                                          "step": "", "elapsed": 0, "eta": last_eta or 0})
                wok, images, wmsg = connector.watch(
                    prompt_id, graph=graph, timeout=900, client_id=channel,
                    on_progress=((lambda ev: self._bcast(
                        channel, dict(ev, type="progress", eta=last_eta or 0)))
                        if progress_on else None))
                if wok:
                    self._record_paint_time(pro_on, int(time.time() - t_paint0))
                    ok_done = True
                    self.log.info(f"[flux_painter] 出图完成 clip={clip_type}")
                    break
                self.log.error(f"[flux_painter] 出图失败 clip={clip_type}: {wmsg[:200]}")
                low = str(wmsg).lower()
                if not any(k in low for k in ("clip", "text encoder", "type", "load")):
                    break
                self.log.warning(f"[flux_painter] CLIP type {clip_type} 失败，切换重试: {wmsg[:160]}")
                on_event("切换文本编码重试…")
            if not ok_done:
                self.log.error(f"[flux_painter] 全部文本编码尝试均失败: {wmsg[:200]}")
                self._say(channel, "画失败了…" + str(wmsg)[:100])
                self._bcast(channel, {"type": "error", "text": str(wmsg)[:200]})
                return
            local_paths = connector.images_local(images)
            if not local_paths:
                self.log.error("[flux_painter] 图已生成但本地文件未找到")
                self._say(channel, "图出来了但没找到文件，奇怪…")
                return
            final_image = local_paths[0]
            self.log.info(f"[flux_painter] 图片文件: {final_image}")

            # 归档
            _pro_snap = None
            if pro_on:
                _pro_snap = {
                    "base_cfg": pro_p.get("base_cfg"), "base_steps": pro_p.get("base_steps"),
                    "hires": {k: (pro_p.get("hires") or {}).get(k)
                              for k in ("enabled", "upscale_model", "scale", "resize")},
                    "usdu": {k: (pro_p.get("usdu") or {}).get(k)
                             for k in ("enabled", "denoise", "steps", "tile_width", "tile_height")},
                    "detailers": {k: {kk: (pro_p.get("detailers", {}).get(k) or {}).get(kk)
                                      for kk in ("enabled", "denoise", "detector", "steps")}
                                  for k in ("hand", "face", "eye")},
                    "sam_model": pro_p.get("sam_model"),
                }
            aok, folder, saved = self.archive.save(
                title, final_image,
                meta={"request": request, "title": title,
                      "positive": final_positive, "negative": negative,
                      "reply": reply, "canvas": canvas_key, "channel": channel,
                      "quality_mode": ("pro" if pro_on else "fast"),
                      "pro_params": _pro_snap})
            self.archive.prune(self.config.keep_last_sessions)
            if not aok:
                self.log.warning("[flux_painter] 归档失败，改用源图")
                self._say(channel, "画好啦！但归档没成功…")
                saved = final_image
            else:
                self.log.info(f"[flux_painter] 画作已归档: {saved}")

            img_url = self._image_url(saved)
            session["final_image"] = saved
            session["reply"] = reply
            # 缓存本轮完整提示词（elements），供画完后窗口内的下一条消息做改图续画
            self._remember_paint(channel, request, elements, saved, session.get("owner_uid"))

            # QQ 渠道判定：私聊不审查；群聊照审（命中→群占位+图私发，分流逻辑在 _send_qq_image 内）
            _qc = session.get("qq_context") or {}
            _qq_private = bool(_qc) and str(_qc.get("message_type", "")) != "group"
            session["ok_show"] = (not self.config.review_enabled) or _qq_private
            rmode = str(getattr(self.config, "review_mode", "onnx") or "onnx").lower()
            if self.config.review_enabled and not _qq_private and rmode == "manual":
                self._say(channel, REVIEW_VOICE)
                self._review_flow(session, img_url, reply)
            elif self.config.review_enabled and not _qq_private:
                # ONNX 自动审查：命中则收起（不展示、不发 QQ、不进记忆展示）
                nsfw, why = self._nsfw_check(saved)
                session["nsfw"] = (nsfw, why)
                if nsfw:
                    session["ok_show"] = False
                    self.log.info(f"[flux_painter] 画板审查(onnx) 命中 -> {why}")
                    self._bcast(channel, {"type": "rejected", "text": REJECT_TEXT})
                    self._say(channel, "这张有点大胆，我先帮你收起来啦awa")
                else:
                    session["ok_show"] = True
                    self.log.info(f"[flux_painter] 画板审查(onnx) 通过 -> {why}")
                    self._bcast(channel, {"type": "done", "image": img_url})
                    self._say(channel, reply)
            else:
                if _qq_private:
                    self.log.info("[flux_painter] QQ 私聊渠道，跳过审查直发")
                self._bcast(channel, {"type": "done", "image": img_url})
                self._say(channel, reply)
            # QQ 发图：一律交给 _send_qq_image 自行分流
            #   群聊命中 → 群发 @+点评+【私】占位，图+点评私发发起人
            #   私聊     → 不审查，直接发
            if session.get("qq_context"):
                self._send_qq_image(session, saved)
            self._save_memory(username, request, reply)
        except Exception:
            self.log.exception(f"[flux_painter] 绘画异常 key={channel}")
            self._say(channel, "画画的时候出了点问题，抱歉…")
        finally:
            with self._lock:
                self._running.discard(channel)
            self._clear_review(channel)

    def _review_flow(self, session, img_url, reply):
        """审查开启：先语音不显示图，等主人按钮裁决；通过才展示"""
        channel = session["channel"]
        self._bcast(channel, {"type": "review", "image": img_url})
        ev = threading.Event()
        with self._lock:
            self._review_events[channel] = ev
            self._review_results.pop(channel, None)
        ok = False
        if ev.wait(timeout=240):
            with self._lock:
                ok = bool(self._review_results.get(channel))
        if ok:
            session["ok_show"] = True
            self._bcast(channel, {"type": "done", "image": img_url})
            self._say(channel, session.get("reply") or reply)
        else:
            session["ok_show"] = False
            self._bcast(channel, {"type": "rejected", "text": REJECT_TEXT})
            self._say(channel, "那这张就先收起来啦，不给看就不给看awa")

    def review_submit(self, channel, passed):
        """审查按钮结果回调（由画板服务 http 调用；manual 模式使用）"""
        with self._lock:
            self._review_results[channel] = bool(passed)
            ev = self._review_events.get(channel)
        if ev:
            ev.set()
        return True

    def _nsfw_check(self, image_path):
        """敏感/裸露判定（NudeNet onnx，与 QQ 群聊共用同一模型与阈值）。

        返回 (nsfw, detail)：
        - nsfw_check.enabled=false → 直接放行（safe(未开启)）
        - 模型不可用/推理异常 → 按 nsfw_check.fail_action 处理（dm=保守视为命中，pass=放行）
        """
        if not self.config.nsfw_enabled:
            return False, "safe(未开启)"
        try:
            from func.toolbox.flux_painter.nsfw_judge import TBNsfwJudge
            j = TBNsfwJudge(self.config)
            okm, mmsg = j.ensure_model()
            if okm:
                return j.judge(image_path)
            nsfw = self.config.nsfw_fail == "dm"
            return nsfw, "model:" + str(mmsg)
        except Exception as e:
            nsfw = self.config.nsfw_fail == "dm"
            return nsfw, f"judge_error:{e}"

    # ==================== 进度 / 耗时统计 ====================
    def _paint_stats_path(self):
        """耗时统计文件（按档位滚动平均，供画板 ETA 参考）"""
        return os.path.join(self.config.comfy_node_dir, "paint_stats.json")

    def _paint_stats(self):
        import json
        try:
            with open(self._paint_stats_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _last_paint_time(self, pro_on):
        """上次同档位耗时（秒），无记录返回 None"""
        item = self._paint_stats().get("pro" if pro_on else "fast") or {}
        try:
            v = int(float(item.get("last_sec") or 0))
            return v or None
        except Exception:
            return None

    def _record_paint_time(self, pro_on, sec):
        """记录本次耗时（滚动平均），供画板 ETA 参考"""
        import json
        key = "pro" if pro_on else "fast"
        st = self._paint_stats()
        item = st.get(key) or {}
        n = int(item.get("count") or 0) + 1
        avg = float(item.get("avg_sec") or 0)
        item["avg_sec"] = round((avg * (n - 1) + float(sec)) / n, 1)
        item["count"] = n
        item["last_sec"] = int(sec)
        st[key] = item
        try:
            os.makedirs(self.config.comfy_node_dir, exist_ok=True)
            with open(self._paint_stats_path(), "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        self.log.info(f"[flux_painter] 本次耗时 {sec}s（{key} 档，平均 {item['avg_sec']}s / {n} 次）")

    def _clear_review(self, channel):
        """清理该 channel 审查事件"""
        with self._lock:
            self._review_events.pop(channel, None)
            self._review_results.pop(channel, None)

    # ==================== 辅助 ====================
    def _ensure_comfy(self):
        """内置启动内核 / 外部探测，返回 (ok, 说明)"""
        if self.config.comfy_mode == "external":
            return create_connector(self.config).ensure_ready()
        from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter
        return get_managed_painter(self.config).start()

    def _canvas_size(self, canvas_key):
        """解析画布规格为 (宽, 高)；像素对齐 16 的倍数（latent/8 后为偶，
        满足 qwen_image 编码 spatial_patch_size=2 的整除校验，避免 (245,135) 类报错）"""
        k = str(canvas_key or "").lower()
        for w, h in self.config.canvas_sizes:
            if k in (f"{w}x{h}", f"{w}*{h}"):
                return w - (w % 16), h - (h % 16)
        w, h = self.config.canvas_default
        return w - (w % 16), h - (h % 16)

    def _style_hint(self, text):
        """识别用户点名的 @风格 与画师名，以及"要求风格化"的意图。

        返回 (style_extra, artist_kw, style_on)
        - style_extra: 文本里直接写的 @xxx 风格标签
        - artist_kw:   "用 xxx 的画风/风格" 形式点名的画师关键词（点名要求）
        - style_on:    用户是否要求「风格化」但没点名具体画师（此时从常驻名单随机抽 1）
        """
        text = text or ""
        style_extra = [t.strip() for t in re.findall(r"@[\w\-_()（）]+", text)]
        artist_kw = ""
        m = re.search(r"(?:按|用|学|参考|模仿|来点|想要)([^，。！？\n]{1,10}(?:画师|老师|画风|风格))", text)
        if m:
            kw = re.sub(r"(画师|老师|画风|风格|的|风格|画|用|参考|模仿|来点|想要)", "", m.group(1)).strip(" ，。")
            if len(kw) >= 2:
                artist_kw = kw
        # 风格化意图：只要点名到了画师就不再看关键词（点名优先）
        style_on = False
        if not artist_kw and not style_extra:
            low = text.lower()
            style_on = any(k.lower() in low for k in self.config.style_on_keywords)
        return style_extra, artist_kw, style_on

    def _image_url(self, abs_path):
        """生成画板可访问的图片地址"""
        if not abs_path:
            return ""
        import urllib.parse
        return (f"http://127.0.0.1:{self.config.http_port}/paint_img?path="
                + urllib.parse.quote(abs_path))

    def _bcast(self, channel, payload):
        """广播到画板对应 channel"""
        try:
            from func.toolbox.flux_painter.server import get_flux_painter_server
            get_flux_painter_server().broadcast(channel, payload)
        except Exception:
            pass

    def _say(self, channel, text):
        """经 toolbox_tts 播报（type=toolbox_painting）；QQ 渠道不播 TTS，文字点评随图发出"""
        if not text:
            return
        if str(channel or "").startswith("qq_"):
            return
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(text, source=self.config.tts_source)
        except Exception:
            self.log.exception("[flux_painter] TTS 播报失败")

    def _save_memory(self, username, user_text, reply):
        """记录需求与回复至短期/长期/用户记忆（提示词不入记忆）"""
        if not self.config.memory_enabled:
            return
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({"role": "user", "content": f"【绘画】{user_text}",
                                "type": self.config.memory_type}, self.config.memory_rounds,
                               trim_mode="rounds")
            ShortMemory().save({"role": "assistant", "content": f"【绘画】{reply}",
                                "type": self.config.memory_type}, self.config.memory_rounds,
                               trim_mode="rounds")
        except Exception:
            pass
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            from func.config.app_config import AppConfig
            bridge = MeowLLMLtMemBridge()
            name = username or "主人"
            bridge.record_user_message(name, f"（让我画图）{user_text}")
            bridge.record_ai_message(name, AppConfig().ai_name, f"（画了图）{reply}")
        except Exception:
            pass

    def _gen_short_reply(self, request):
        """AI 生成一句接单卖萌短句（非流式轻量单轮）"""
        try:
            port = self.producer._llm()
            messages = [
                {"role": "system", "content":
                 "你是会画画的喵系少女助手，说话软萌。主人在向你点单画图，请用一句话（30字内）可爱地接下任务，"
                 "可带 主人/喵 等口头语；不要括号、不要表情符号、不要多余符号，只输出这句话本身。"},
                {"role": "user", "content": str(request)[:200]},
            ]
            resp = port.chat(messages, tools=None, enable_thinking=False,
                             options={"temperature": 1.0, "max_tokens": 160})
            text = ""
            if resp is not None and getattr(resp, "choices", None):
                msg = resp.choices[0].message
                text = str(getattr(msg, "content", None) or "").strip()
            text = re.sub(r"[（(【\[][^）)】\]]*[）)】\]]", "", text)
            return " ".join(text.split())[:60]
        except Exception:
            self.log.exception("[flux_painter] 开场白生成失败")
            return ""

    def _qq_opener(self, qq_context, request):
        """QQ 渠道：异步 AI 开场白（生成失败则用兜底短句）"""
        text = self._gen_short_reply(request) or "好呀，这就给你画～画完连点评一起发给你！"
        self._qq_say_text(qq_context, text)

    def _qq_say_text(self, qq_context, text):
        """给 QQ 渠道回一条普通文本（私聊直发/群聊普通消息）"""
        if not text:
            return
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            ncore = TBNapCatCore()
            if str(qq_context.get("message_type", "")) == "group":
                gid = qq_context.get("target_id") or qq_context.get("group_id")
                if gid:
                    ncore.call_action_sync("send_group_msg", {
                        "group_id": int(gid),
                        "message": [{"type": "text", "data": {"text": text}}]})
            else:
                uid = qq_context.get("user_id") or qq_context.get("target_id")
                if uid:
                    ncore.call_action_sync("send_private_msg", {
                        "user_id": int(uid),
                        "message": [{"type": "text", "data": {"text": text}}]})
        except Exception:
            self.log.exception("[flux_painter] QQ 文本发送失败")

    def _send_qq_image(self, session, image_path):
        """把成品图+角色点评发给 QQ。
        群聊：先做裸露审查（nsfw_check.enabled）→ 命中则群聊只发 @+点评+【私】占位，
        成品图+点评仅私发给发起人；未命中照常群发图。私聊渠道不审查，原样发送。"""
        try:
            if not self.config.enabled or not image_path or not os.path.isfile(image_path):
                return
            channel = session.get("channel", "")
            reply = str(session.get("reply") or "画好啦！")
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            ncore = TBNapCatCore()
            qc = session.get("qq_context") or {}
            owner = str(session.get("owner_uid") or qc.get("user_id") or qc.get("target_id") or "")
            img = {"type": "image",
                   "data": {"file": ncore.api_client._to_file_uri(image_path)}}
            if channel.startswith("qq_group_"):
                gid = str(qc.get("target_id") or qc.get("group_id") or "")
                if not gid:
                    return
                # —— 群裸图审查（优先复用画板审查已算出的结果，避免同一张图推理两次）——
                nsfw, why = False, "safe(未开启)"
                cached = session.get("nsfw")
                if cached:
                    nsfw, why = cached
                elif self.config.nsfw_enabled:
                    nsfw, why = self._nsfw_check(image_path)
                    self.log.info(f"[flux_painter] 群裸图审查 {os.path.basename(image_path)} -> {why}")
                if nsfw:
                    # 群聊：@发起人 + 点评 + 【私】占位，不带图
                    msg = []
                    if owner:
                        msg.append({"type": "at", "data": {"qq": owner}})
                        msg.append({"type": "text",
                                    "data": {"text": " " + reply + "（这张比较大胆，已私发给你啦~【私】）"}})
                    else:
                        msg.append({"type": "text",
                                    "data": {"text": reply + "（已私发给你~【私】）"}})
                    ncore.call_action_sync("send_group_msg", {"group_id": int(gid), "message": msg})
                    # 图仅私发给发起人
                    if owner:
                        ncore.call_action_sync("send_private_msg", {
                            "user_id": int(owner),
                            "message": [{"type": "text", "data": {"text": reply}}, img]})
                    return
                msg = []
                if owner:
                    msg.append({"type": "at", "data": {"qq": owner}})
                    msg.append({"type": "text", "data": {"text": " " + reply}})
                else:
                    msg.append({"type": "text", "data": {"text": reply}})
                msg.append(img)
                ncore.call_action_sync("send_group_msg", {"group_id": int(gid), "message": msg})
            elif owner:
                ncore.call_action_sync("send_private_msg", {
                    "user_id": int(owner),
                    "message": [{"type": "text", "data": {"text": reply}}, img]})
        except Exception:
            self.log.exception("[flux_painter] QQ 发图失败")
