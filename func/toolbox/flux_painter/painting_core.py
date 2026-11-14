import os
import re
import shutil
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.flux_painter.config import TBFluxPainterConfig
from func.toolbox.flux_painter.painting_pipeline import TBPaintPipelineMixin
from func.toolbox.flux_painter.archive import TBPainterArchive
from func.toolbox.flux_painter.prompt_producer import TBPromptProducer
from func.toolbox.flux_painter.comfy_connector import create_connector, TBArtistPicker
from func.toolbox.trigger_rules import forced

DEFAULT_NEGATIVE = ("lowres,bad anatomy,bad hands,error,missing fingers,extra digits,"
                    "worst quality,jpeg artifacts,watermark,signature,text")
REJECT_TEXT = "不给看不给看awa"

@singleton
class TBFluxPainterCore(TBPaintPipelineMixin):
    """ComfyUI 文生图一次性触发总入口（live/QQ），绘画中冷却，不长期接管"""

    TOOL_NAME = "flux_paint"

    PAINT_RULE_WORDS = (
        "画一幅", "画一张", "画个", "画张", "画一个", "画一只", "画一条", "画一棵",
        "画一朵", "画朵", "画一座", "画一栋", "画一下", "画一画",
        "画点", "画张图", "画幅画", "画张画", "画张涩图", "画张瑟图",
        "重画", "再画", "重新画", "画个图", "去画", "画画看",
        "帮我画", "给我画", "替我画", "给咱画", "给我来张", "帮我出张", "帮我整张",
        "想让你画", "你画个", "给我整张",
        "来张", "来幅", "来一张", "来一幅", "来点图", "来张图", "来张涩图", "来张色图",
        "要一张", "要张图", "想要一张", "想要张图", "想要张", "要张涩图",
        "生成一张图", "生成张图", "生成图片", "文生图", "出张图", "出图",
        "涩图", "瑟图", "色图", "整张图",
    )

    TRIGGER_RULES = (
        forced(TOOL_NAME, PAINT_RULE_WORDS,
               args=lambda text: {"request": text, "topic": "规则硬触发绘画"}),
    )

    def __init__(self):
        """初始化。"""
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
        self._last_paint = {}
        self._last_lock = threading.Lock()
        self._pending_ref = {}
        self._pending_lock = threading.Lock()
        self._quote_images = {}
        self._quote_lock = threading.Lock()
        self._opener_recent = {}
        self._opener_lock = threading.Lock()
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

    def set_meowid(self, uid):
        """框架注入当前说话人的内部编号（身份标准）。昵称只用于展示，不进这里。"""
        if uid:
            self._context["meowid"] = uid

    def set_context(self, context):
        """写入框架上下文（说话人编号/QQ 上下文）。"""
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

    def _reference_path(self, channel):
        """参考图的稳定副本路径（源图可能被清理，改图召回时用它兜底）"""
        safe = re.sub(r'[\\/:*?"<>|]', "_", str(channel or "")) or "channel"
        return os.path.join(self.config.ref_dir, f"last_{safe}.png")

    def _persist_reference(self, channel, init_image):
        """把本轮参考图另存一份稳定副本，供后续改图召回"""
        try:
            src = str(init_image or "")
            if not src or not os.path.isfile(src):
                return
            dst = self._reference_path(channel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        except Exception:
            self.log.exception("[flux_painter] 缓存参考图副本失败")

    def _last_reference(self, channel):
        """改图时可召回的参考图：只有上一轮本身就是图生图才召回"""
        with self._last_lock:
            item = self._last_paint.get(str(channel)) or {}
        init_image = str(item.get("init_image") or "")
        if not init_image:
            return ""
        if os.path.isfile(init_image):
            return init_image
        stable = self._reference_path(channel)
        return stable if os.path.isfile(stable) else ""

    def _drop_reference(self, channel):
        """本轮是纯文生图：清掉旧的参考图副本，避免被后续改图误召回"""
        try:
            path = self._reference_path(channel)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

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

    def continue_paint(self, channel, edit_instruction, qq_context, uid=None):
        """以上一轮缓存提示词为底，执行改图（纯 txt2img 增量重绘）"""
        if uid:
            self._context["meowid"] = str(uid)
        if self.is_painting(channel):
            return "正在画画呢，画完这张再点下一张吧～"
        item = self.get_last_paint(channel)
        if not item:
            return "没有可续画的上一张图"
        base_elements = item.get("elements") or {}
        arguments = {"request": str(edit_instruction or item.get("request") or ""),
                     "topic": str(base_elements.get("title") or "改图")}
        init_image = self._last_reference(channel)
        return self.open_paint(channel, arguments, qq_context=qq_context,
                               base_elements=base_elements,
                               base_request=str(item.get("request") or ""),
                               init_image=init_image)

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

    def dispatch(self, name, arguments):
        """live 开局（父级 decide 命中 flux_paint 时调用）"""
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        try:
            from func.toolbox.flux_painter.img2img.chain import TBImg2ImgChain
            opened = TBImg2ImgChain().open_screen(arguments, channel="live")
            if opened:
                return opened
        except Exception:
            self.log.exception("[flux_painter] 屏幕参考判断失败，按文生图继续")
        from func.toolbox.flux_painter.txt2img.chain import TBTxt2ImgChain
        return TBTxt2ImgChain().open_live(arguments)

    def dispatch_qq(self, name, arguments, qq_context):
        """QQ 开局（QQ 只走文生图，图生图看附图那条路）"""
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        if not self.config.enabled:
            return "绘画模块未开启"
        from func.toolbox.flux_painter.txt2img.chain import TBTxt2ImgChain
        return TBTxt2ImgChain().open_qq(arguments, qq_context)

    @staticmethod
    def channel_of(qq_context):
        """QQ 上下文 → 绘画通道名（群聊/私聊各自隔离）"""
        ctx = qq_context or {}
        if str(ctx.get("message_type", "")) == "group":
            return f"qq_group_{ctx.get('target_id')}"
        return f"qq_private_{ctx.get('user_id') or ctx.get('target_id')}"

    @classmethod
    def hits_paint_keywords(cls, text):
        """这句话是否命中绘画关键词"""
        body = str(text or "").lower()
        return bool(body) and any(str(w).lower() in body for w in cls.PAINT_RULE_WORDS)

    def broadcast_status(self, channel, text):
        """向画板广播一句状态（供两条链路模块调用）"""
        self._bcast(channel, {"type": "status", "text": text})

    def has_identity(self):
        """当前上下文是否已注入内部编号（链路层在截图/取景前先问一下，免得白跑）"""
        return bool(str(self._context.get("meowid") or ""))

    def context_text(self):
        """当前上下文里的用户原话（链路层做语义判断时用）"""
        return str(self._context.get("text") or "")

    def open_paint(self, channel, arguments, qq_context=None, base_elements=None,
                   base_request="", init_image="", ref_note=""):
        """冷却检查并起后台绘画线程（base_elements 非空=续画/改图，init_image 非空=图生图）。"""
        if not self.config.enabled:
            return "绘画模块未开启（请在工具箱-绘画配置中启用）"
        if self.is_painting(channel):
            self.log.info(f"[flux_painter] 拒绝开画：{channel} 仍在作画中（占用={sorted(self._running)}）")
            return "正在画画呢，画完这张再点下一张吧～"
        arguments = arguments or {}
        request = str(arguments.get("request") or self._context.get("text") or "").strip()
        if not request:
            return "想让我画什么呀？说说看～"
        uid = str(self._context.get("meowid") or "")
        if not uid:
            self.log.error("[flux_painter] 缺少身份编号(meowid)，拒绝开画（禁止用默认身份兜底）")
            return "身份没认出来，这次先不画了～"
        try:
            persona = str(self._context.get("system_prompt") or "")
            memories = self._context.get("short_memory")
            if not memories:
                from func.pipeline.short_memory import ShortMemory
                memories = ShortMemory().load()[-10:]
        except Exception:
            persona, memories = "", []
        session = {"channel": channel, "meowid": uid, "request": request,
                   "topic": str(arguments.get("topic") or "").strip(),
                   "persona": persona, "memories": memories,
                   "qq_context": qq_context,
                   "base_elements": base_elements, "base_request": base_request,
                   "init_image": str(init_image or ""),
                   "ref_note": str(ref_note or ""),
                   "owner_uid": str((qq_context or {}).get("user_id") or
                                    (qq_context or {}).get("target_id") or "")}
        try:
            from func.pipeline.short_memory import ShortMemory
            session["memory_scope"] = ShortMemory.scope_of_channel(channel)
        except Exception:
            session["memory_scope"] = "main"
        with self._lock:
            self._running.add(channel)
        t = threading.Thread(target=self._run, args=(session,), daemon=True,
                             name=f"flux_painter_{channel}")
        try:
            t.start()
        except Exception:
            with self._lock:
                self._running.discard(channel)
            raise
        if qq_context:
            threading.Thread(target=self._qq_opener, args=(qq_context, request, channel),
                             daemon=True).start()
        else:
            threading.Thread(target=self._live_opener, args=(channel, request),
                             daemon=True).start()
        return ("开始作画…画完把图发给你～" if qq_context
                else "开始作画…（画作完成后会展示；画板页面可实时看进度）")

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
            text = session.get("reply") or reply
            if text:
                self._say(channel, text)
        else:
            session["ok_show"] = False
            self._bcast(channel, {"type": "rejected", "text": REJECT_TEXT})
            self._say_need(channel, "主人没通过这张，你把它收起来了，跟他说一句。")

    def review_submit(self, channel, passed):
        """审查按钮结果回调（由画板服务 http 调用；manual 模式使用）"""
        with self._lock:
            self._review_results[channel] = bool(passed)
            ev = self._review_events.get(channel)
        if ev:
            ev.set()
        return True

    def _paint_stats_path(self):
        """耗时统计文件（按档位滚动平均，供画板 ETA 参考）"""
        return os.path.join(self.config.comfy_node_dir, "paint_stats.json")

    def _paint_stats(self):
        """累计出图耗时统计。"""
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

    def _ensure_comfy(self):
        """内置启动内核 / 外部探测，返回 (ok, 说明)"""
        if self.config.comfy_mode == "external":
            return create_connector(self.config).ensure_ready()
        from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter
        return get_managed_painter(self.config).start()

    _GENERIC_TAG_WORDS = (
        "hair", "eyes", "bangs", "ponytail", "braid", "twintails", "dress", "shirt", "skirt",
        "uniform", "jacket", "coat", "sweater", "cardigan", "socks", "stockings", "thighhighs",
        "pantyhose", "panties", "bra", "underwear", "gloves", "boots", "shoes", "ribbon",
        "bow", "hat", "glasses", "earrings", "halo", "ears", "tail", "wings", "bed", "room",
        "window", "wall", "chair", "desk", "outdoors", "indoors", "sky", "night", "light",
        "lighting", "shadows", "background", "view", "shot", "angle", "pov", "close", "body",
        "breasts", "hips", "thighs", "skin", "smile", "blush", "tears", "sweat", "pose",
        "sitting", "standing", "lying", "kneeling", "leaning", "looking", "holding", "hands",
        "fingers", "legs", "arms", "head", "face", "girl", "boy", "solo", "quality", "highres",
        "masterpiece", "aesthetic", "score", "detailed", "soft", "warm", "color", "style",
    )

    _INTERACTION_TAGS = (
        "1boy", "2boys", "3boys", "male", "males", "hetero", "yuri", "yaoi", "2girls",
        "3girls", "multiple boys", "multiple girls", "multiple views", "couple",
        "kiss", "hug", "hugging", "handholding", "hand holding", "holding hands",
        "paizuri", "fellatio", "irrumatio", "handjob", "footjob", "cunnilingus",
        "vaginal", "anal", "sex", "penetration", "fingering", "masturbation",
        "pov", "pov hands", "male hand", "male hands", "on top of another", "missionary",
        "doggystyle", "cowgirl position", "spooning", "orgy", "threesome",
        "leg lock", "legs wrapped around", "straddling a person",
    )

    @staticmethod
    def _wants_multiple(request):
        """需求里是否明确要多人，或点名了必须有对方的体位（骑乘/后入等）。"""
        text = str(request or "").lower()
        keys = ("双人", "两人", "二人", "多人", "群", "3p", "双飞", "一起", "互相",
                "两个人", "three people", "two girls", "两女", "一男一女", "男方", "男主",
                "骑乘", "骑乘位", "跨坐", "后入", "后入位", "传教士", "火车便当", "种付",
                "口交", "足交", "乳交", "素股", "手交", "内射", "中出", "插入", "抽插",
                "性交", "做爱", "被操", "操她", "睡奸", "拘束", "绑起来", "双飞")
        return any(k in text for k in keys)

    def _strip_cinema_interaction(self, cinema):
        """cinema 句子里描述第二人的分句一并清掉（solo 时模型爱在句子里加个男的）。"""
        import re
        text = str(cinema or "").strip()
        if not text:
            return text
        patterns = (
            r"[^.]*\b(a|the|his|her)\s+(man|boy|male|partner|client|customer)\b[^.]*\.",
            r"[^.]*\b(his|their)\s+(hand|hands|fingers|arm|arms|lap)\b[^.]*\.",
            r"[^.]*\b(he|they)\b[^.]*\.",
            r"[^.]*\b(pov|point of view)\b[^.]*\.",
            r"[^.]*\b(handjob|footjob|fellatio|paizuri|penetrat\w*)\b[^.]*\.",
        )
        for pat in patterns:
            text = re.sub(pat, "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text != str(cinema or "").strip():
            self.log.info("[flux_painter] solo 场景已清理 cinema 里的第二人描述")
        return text

    def _strip_interaction(self, positive):
        """删掉交互类 tag，让单人场景不出现第二个人/手。"""
        parts = [p.strip() for p in str(positive or "").split(",")]
        kept, dropped = [], []
        for p in parts:
            low = p.lower()
            if not p:
                continue
            if any(t == low or (len(t) > 4 and t in low) for t in self._INTERACTION_TAGS):
                dropped.append(p)
                continue
            kept.append(p)
        if dropped:
            self.log.info("[flux_painter] solo 场景已移除交互 tag: %s" % ", ".join(dropped))
        return ", ".join(kept)

    def _verified_positive(self, positive):
        """删掉查证不过的角色 tag（模型音译编造的那种），返回清理后的正向提示词。"""
        from func.toolbox.flux_painter.prompts.danbooru_tool import verify_tag
        parts = [p.strip() for p in str(positive or "").split(",")]
        kept, dropped = [], []
        for p in parts:
            if not p:
                continue
            low = p.lower()
            generic = any(w in low for w in self._GENERIC_TAG_WORDS)
            if ("(" in p and p.rstrip().endswith(")")) or (not generic and len(p.split()) >= 2):
                ok, canon = verify_tag(p, config=self.config, log=self.log)
                if not ok:
                    dropped.append(p)
                    continue
                kept.append(canon if canon else p)
            else:
                kept.append(p)
        if dropped:
            self.log.warning("[flux_painter] 角色 tag 查证未通过，已删除: %s"
                             % ", ".join(dropped))
        return ", ".join(kept)

    def _canvas_size(self, canvas_key):
        """解析画布规格为 (宽, 高)；像素对齐 16 的倍数（latent/8 后为偶，"""
        k = str(canvas_key or "").lower()
        for w, h in self.config.canvas_sizes:
            if k in (f"{w}x{h}", f"{w}*{h}"):
                return w - (w % 16), h - (h % 16)
        w, h = self.config.canvas_default
        return w - (w % 16), h - (h % 16)

    def _style_hint(self, text):
        """识别用户点名的 @风格 与画师名，以及"要求风格化"的意图。"""
        text = text or ""
        style_extra = [t.strip() for t in re.findall(r"@[\w\-_()（）]+", text)]
        artist_kw = ""
        m = re.search(r"(?:按|用|学|参考|模仿|来点|想要)([^，。！？\n]{1,10}(?:画师|老师|画风|风格))", text)
        if m:
            kw = re.sub(r"(画师|老师|画风|风格|的|风格|画|用|参考|模仿|来点|想要)", "", m.group(1)).strip(" ，。")
            if len(kw) >= 2:
                artist_kw = kw
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

    def _line_need(self, need, max_chars=40):
        """让角色现说一句（台词不写死；生成失败返回空串，绝不退回固定台词）"""
        uid = str(self._context.get("meowid") or "")
        history = self._context.get("short_memory") or []
        for _ in range(2):
            try:
                from func.toolbox.character_voice import TBoxCharacterVoice
                line = TBoxCharacterVoice().line(need, uid, history=history, max_chars=max_chars)
            except Exception:
                self.log.exception("[flux_painter] 台词生成失败")
                line = ""
            if line:
                return line
        self.log.warning(f"[flux_painter] 台词生成失败，本次不说：{need[:40]}")
        return ""

    def _say_need(self, channel, need, max_chars=40):
        """把内部需求交给角色说一句并播报（QQ 渠道不本地播报）"""
        if str(channel or "").startswith("qq_"):
            return ""
        line = self._line_need(need, max_chars)
        if line:
            self._say(channel, line)
        return line

    def say_need(self, channel, need, max_chars=40):
        """链路层的开口入口：让角色用自己的话问一句（屏幕没找到东西时用）"""
        return self._say_need(channel, need, max_chars)

    REF_WAIT_SECONDS = 60.0

    def cache_quote_images(self, channel, images):
        """记下本条消息引用的图（分析层判定要画图时直接取用，避免二次判定后去等图）"""
        if not images:
            return
        with self._quote_lock:
            self._quote_images[str(channel)] = {"images": list(images), "ts": time.time()}

    def take_quote_images(self, channel, ttl=90.0):
        """取走并清空本条消息的引用图；过期返回空列表（一次性）"""
        with self._quote_lock:
            item = self._quote_images.pop(str(channel), None)
        if not item:
            return []
        if time.time() - float(item.get("ts") or 0) > float(ttl):
            return []
        return list(item.get("images") or [])

    def wait_reference(self, channel, request, qq_context, seconds=None):
        """判定要参考图但本条消息没带图：挂起等用户补图，绝不先开画"""
        secs = float(seconds or self.REF_WAIT_SECONDS)
        with self._pending_lock:
            old = self._pending_ref.pop(str(channel), None)
            if old and old.get("timer"):
                old["timer"].cancel()
            timer = threading.Timer(secs, self._on_ref_timeout, args=(str(channel),))
            timer.daemon = True
            self._pending_ref[str(channel)] = {
                "request": str(request or ""),
                "qq_context": dict(qq_context or {}),
                "deadline": time.time() + secs,
                "timer": timer,
            }
            timer.start()
        self.log.info(f"[flux_painter] 等 {secs:.0f}s 参考图 channel={channel}")
        return secs

    def take_pending_reference(self, channel):
        """有挂起的等图请求就取走并返回原需求（配套「这张图到了」），没有返回空串"""
        with self._pending_lock:
            item = self._pending_ref.pop(str(channel), None)
            if not item:
                return ""
            if item.get("timer"):
                item["timer"].cancel()
            if time.time() > float(item.get("deadline") or 0):
                return ""
        self.log.info(f"[flux_painter] 收到补的参考图 channel={channel}")
        return str(item.get("request") or "")

    def _on_ref_timeout(self, channel):
        """等图超时：只问一句，不开画"""
        with self._pending_lock:
            item = self._pending_ref.pop(str(channel), None)
        if not item:
            return
        need = "主人说要参考一张图，可一直没发，问一句是不是忘了、还要不要画。"
        line = self._line_need(need, 30) or "图还没等到，你把参考图发我一下？"
        ctx = item.get("qq_context") or {}
        if ctx:
            self._qq_say_text(ctx, line)
        else:
            self._say(str(channel), line)
        self.log.info(f"[flux_painter] 等参考图超时，已问一句 channel={channel}")

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

    def _live_opener(self, channel, request):
        """live 渠道：角色应一声（经 TTS 说出来）"""
        self._say(channel, self._opener_line(channel, request))

    def _qq_opener(self, qq_context, request, channel):
        """QQ 渠道：角色应一声（文字随消息发出）"""
        self._qq_say_text(qq_context, self._opener_line(channel, request))

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

    @staticmethod
    def _qq_send_ok(resp):
        """QQ 发送是否成功。"""
        if not isinstance(resp, dict):
            return False
        if str(resp.get("status", "")).lower() == "ok":
            return True
        return str(resp.get("retcode", "")).strip() in ("0",)

    def _qq_private_send(self, ncore, user_id, group_id, message):
        """私聊发图。"""
        uid = int(user_id)
        if self._qq_send_ok(ncore.call_action_sync(
                "send_private_msg", {"user_id": uid, "message": message})):
            return True
        gid = int(group_id) if str(group_id or "").isdigit() else 0
        if gid:
            return self._qq_send_ok(ncore.call_action_sync(
                "send_private_msg", {"user_id": uid, "group_id": gid, "message": message}))
        return False
