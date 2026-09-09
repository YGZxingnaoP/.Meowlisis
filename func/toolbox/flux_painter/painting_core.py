# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/painting_core.py
import os
import re
import threading
import time
import uuid

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

    def _open(self, channel, arguments, qq_context=None):
        """冷却检查并起后台绘画线程"""
        if not self.config.enabled:
            return "绘画模块未开启（请在工具箱-绘画配置中启用）"
        if self.is_painting():
            return "正在画画呢，画完这张再点下一张吧～"
        arguments = arguments or {}
        request = str(arguments.get("request") or self._context.get("text") or "").strip()
        if not request:
            return "想让我画什么呀？说说看～"
        username = str(arguments.get("username") or self._context.get("username") or "主人")
        session = {"channel": channel, "username": username, "request": request,
                   "topic": str(arguments.get("topic") or "").strip(),
                   "qq_context": qq_context,
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
        try:
            self._bcast(channel, {"type": "status", "text": "AI 正在构思画面…"})

            def on_stream(text):
                self._bcast(channel, {"type": "producing", "text": text})

            elements = self.producer.run(request, username=username,
                                         persona=str(self._context.get("system_prompt") or ""),
                                         on_stream=on_stream)
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

            # 画师/风格串 + 质量前缀（脚本侧拼接，模型不输出）
            style_extra, artist_kw = self._style_hint(request)
            named = []
            if artist_kw:
                try:
                    if self.artist.ensure_data()[0]:
                        named = self.artist.search(artist_kw, top=1)
                except Exception:
                    pass
            artist_tags = self.artist.build_artist_tags(named=named, style_tags=style_extra)
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
            for clip_type in ("qwen_image", "stable_diffusion", "flux2"):
                graph = connector.build_graph(final_positive, negative, w, h,
                                              prefix=prefix, clip_type=clip_type)
                on_event("提交任务…")
                sok, prompt_id, serr = connector.submit(graph, client_id=channel)
                if not sok:
                    self.log.error(f"[flux_painter] 任务提交失败 clip={clip_type}: {serr[:200]}")
                    self._say(channel, f"画图任务没提交成功：{serr[:120]}")
                    return
                self.log.info(f"[flux_painter] 任务已提交 clip={clip_type} prompt_id={prompt_id}")
                self._bcast(channel, {"type": "status", "text": "AI 正在作画…"})
                wok, images, wmsg = connector.wait(prompt_id, on_event=on_event)
                if wok:
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
            aok, folder, saved = self.archive.save(
                title, final_image,
                meta={"request": request, "title": title,
                      "positive": final_positive, "negative": negative,
                      "reply": reply, "canvas": canvas_key, "channel": channel})
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

            session["ok_show"] = not self.config.review_enabled
            # 审查模式：审查开先播检查语音等裁决，通过才展示+完成语音；关则直接展示+完成语音
            if self.config.review_enabled:
                self._say(channel, REVIEW_VOICE)
                self._review_flow(session, img_url, reply)
            else:
                self._bcast(channel, {"type": "done", "image": img_url})
                self._say(channel, reply)
            # QQ 发图：审查通过或未开启才发（图+角色点评文字）；QQ 渠道不走 TTS
            if session.get("qq_context") and session.get("ok_show"):
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
        """审查按钮结果回调（由画板服务 http 调用）"""
        with self._lock:
            self._review_results[channel] = bool(passed)
            ev = self._review_events.get(channel)
        if ev:
            ev.set()
        return True

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
        """解析画布规格为 (宽, 高)"""
        k = str(canvas_key or "").lower()
        for w, h in self.config.canvas_sizes:
            if k in (f"{w}x{h}", f"{w}*{h}"):
                return w, h
        return self.config.canvas_default

    def _style_hint(self, text):
        """识别用户点名的 @风格 与画师名（返回 style_extra, 画师搜索词）"""
        style_extra = [t.strip() for t in re.findall(r"@[\w\-_()（）]+", text or "")]
        artist_kw = ""
        m = re.search(r"(?:按|用|学|参考|模仿|来点|想要)([^，。！？\n]{1,10}(?:画师|老师|画风|风格))", text or "")
        if m:
            kw = re.sub(r"(画师|老师|画风|风格|的|风格|画|用|参考|模仿|来点|想要)", "", m.group(1)).strip(" ，。")
            if len(kw) >= 2:
                artist_kw = kw
        return style_extra, artist_kw

    def _image_url(self, abs_path):
        """生成画板可访问的图片地址"""
        if not abs_path:
            return ""
        import urllib.parse
        return (f"http://127.0.0.1:{self.config.http_port}/paint_img?"
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
                             temperature=1.0, max_tokens=160)
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
        """把成品图+角色点评发给 QQ（私聊：点评文字+图；群聊：@+点评+图）"""
        try:
            if not self.config.enabled or not image_path or not os.path.isfile(image_path):
                return
            channel = session.get("channel", "")
            reply = str(session.get("reply") or "画好啦！")
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            ncore = TBNapCatCore()
            qc = session.get("qq_context") or {}
            owner = str(session.get("owner_uid") or qc.get("user_id") or qc.get("target_id") or "")
            img = {"type": "image", "data": {"file": ncore._to_file_uri(image_path)}}
            if channel.startswith("qq_group_"):
                gid = str(qc.get("target_id") or qc.get("group_id") or "")
                if not gid:
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
