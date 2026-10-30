# -*- coding: utf-8 -*-
"""观影会话：开播 → （每 3~4 分钟随机）截一帧 → 安静记录评价 → 用户发问时作答
→ 用户说结束后给一段整体影评并归档。整个过程不出声（除了开播一句与收尾影评）。"""

import os
import random
import shutil
import threading
import time

from . import prompts, store
from .brain import MovieBrain
from .capture import ScreenCapture
from .config import MovieConfig
from .dialogue import DialogueListener
from .vision import MovieVision

# 结束意图（仅观影进行中才接管）
STOP_WORDS = ("观影结束", "结束观影", "结束看电影", "看电影结束", "电影结束了", "片看完了",
              "看完了", "看完了吗", "不看了", "别看了", "关掉吧", "不看了吧", "收工吧",
              "看片结束", "结束吧", "停了吧", "stop")

# 提问意图（观影进行中，用户问剧情/评价）
ASK_WORDS = ("演到哪", "演到哪儿", "放到哪", "看到哪", "看到哪儿", "看到些什么",
             "什么电影", "什么片", "剧情", "讲什么", "讲了什么", "好不好看", "好看吗",
             "你的评价", "评价一下", "感觉怎么样", "你觉得怎么样", "感想", "观后感",
             "你看到", "你记得", "刚才演", "现在演", "这一幕", "这个画面", "记录了什么",
             "台词", "说了什么")

# 开播意图（非观影状态下用于兜底判定）
START_WORDS = ("陪我看电影", "陪我看部电影", "陪我看片", "陪我看剧", "一起看电影",
               "一起看片", "观影", "看电影", "看剧", "看片")

# 「别管窗口判定，就按我说的来」的显式指令
FORCE_WORDS = ("整屏", "整个屏幕", "全屏", "全屏幕", "所有屏幕", "全部屏幕",
               "就这个窗口", "就盯这个", "盯这个窗口", "这个窗口就行", "别管窗口")


class MovieSession:
    """单场观影会话（同时只允许一场）"""

    def __init__(self):
        self.ctx = None
        self.log = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._active = False
        self._finalized = True
        self._uid = ""
        self._sid = ""
        self._dir = ""
        self._meta = {}
        self._notes = []
        self._started = 0.0
        self._capture = None
        self._gone_since = None
        self._dialogue = None
        self._last_capture_ts = 0.0     # 上一次成功落帧的时刻（台词窗口从它算起）

    # ==================== 基础 ====================
    def set_ctx(self, ctx):
        self.ctx = ctx
        self.log = ctx.log

    def config(self):
        return MovieConfig(self.ctx)

    def is_active(self):
        return bool(self._active)

    def status_text(self):
        with self._lock:
            if not self._active:
                return "现在没有在观影"
            return (f"观影中：{self._meta.get('window_title') or '整块屏幕'}，"
                    f"已看 {self._duration_text(time.time() - self._started)}，"
                    f"记录 {len(self._notes)} 条")

    # ==================== 入口分发 ====================
    def handle_action(self, action, text, uid="", window="", speak=True):
        """按 action 执行；action 为空时按当前状态与文本自动判定。返回 (状态, 文本)"""
        action = str(action or "").strip().lower()
        if action not in ("start", "ask", "stop", "status"):
            action = self._infer_action(text)
        if action == "start":
            return self.start(text, uid, window, speak)
        if action == "ask":
            return self.ask(text, uid, speak)
        if action == "stop":
            return self.stop(uid, "user", speak)
        return "status", self.status_text()

    def _infer_action(self, text):
        text = str(text or "")
        if self._active:
            return "stop" if self.is_stop_text(text) else "ask"
        if self.is_ask_text(text):
            return "ask"
        if self.is_start_text(text) or not text.strip():
            return "start"
        return "status"

    @staticmethod
    def is_stop_text(text):
        text = str(text or "")
        return any(word in text for word in STOP_WORDS)

    @staticmethod
    def is_ask_text(text):
        text = str(text or "").strip()
        if not text or len(text) > 60:
            return False
        return any(word in text for word in ASK_WORDS)

    @staticmethod
    def is_start_text(text):
        text = str(text or "")
        return any(word in text for word in START_WORDS)

    # ==================== 开播 ====================
    def _line(self, brain, uid, instruction, fallback=""):
        """让角色自己说一句话（模型不可用才用兜底文案）"""
        try:
            return brain.say(instruction, uid, fallback)
        except Exception:
            self.log.exception("[movie_watch] 生成台词失败")
            return fallback

    def start(self, request="", uid="", window="", speak=True):
        if not self.ctx:
            return "error", "插件还没准备好"
        with self._lock:
            if self._active:
                busy = True
            else:
                busy = False
        cfg = self.config()
        brain = MovieBrain(self.ctx, cfg, self.log)
        if busy:
            text = self._line(brain, uid,
                              "主人又说要看片，可你已经在陪他看了；告诉主人已经在看，别重复开。",
                              prompts.FALLBACK_BUSY)
            if speak:
                self._speak(text)
            return "busy", text

        vision = MovieVision(cfg, self.log)
        if not vision.available():
            text = self._line(brain, uid,
                              f"你发现这次看不了画面（原因：{vision.detail}），"
                              "跟主人说一声这会儿看不了，等弄好再一起看。",
                              prompts.FALLBACK_UNAVAILABLE)
            if speak:
                self._speak(text)
            return "unavailable", text

        # ---------- 窗口绑定 + 确认（防误触发/误绑） ----------
        capture = ScreenCapture(cfg, self.log)
        force_any = self.is_force_text(request)
        dialogue = DialogueListener(cfg, self.log)
        started_dialogue = [False]

        def ensure_dialogue():
            if not started_dialogue[0]:
                started_dialogue[0] = dialogue.preflight() and dialogue.start()
            return started_dialogue[0]

        if cfg.mode == "window":
            bound = capture.bind(window)
            if not bound:
                if not (cfg.allow_fullscreen_fallback or force_any):
                    text = self._line(
                        brain, uid,
                        "你没找到正在放片的窗口。让主人先把片打开、或者把播放器窗口名告诉你；"
                        "顺便告诉主人，如果就想看整屏，说一句「看整屏」也行。",
                        prompts.FALLBACK_NEED_WINDOW)
                    if speak:
                        self._speak(text)
                    return "need_window", text
                cfg.mode = "fullscreen"
                self.log.info("[movie_watch] 没绑到窗口，本次按整屏截屏")
            elif cfg.confirm_video_window and not force_any and not capture.is_video_window():
                # 标题不像播放器（浏览器看片常见）：开台词识别，用它自己的回环试听
                level = 0.0
                if cfg.confirm_by_audio and ensure_dialogue():
                    level = dialogue.wait_audio(cfg.confirm_audio_seconds,
                                                cfg.confirm_audio_level)
                    self.log.info(f"[movie_watch] 试听回环峰值 RMS={level:.0f}"
                                  f"（阈值 {cfg.confirm_audio_level}）")
                if level < cfg.confirm_audio_level:
                    dialogue.stop()
                    started_dialogue[0] = False
                    title = self._short(capture.title, 18)
                    text = self._line(
                        brain, uid,
                        f"你绑到的是「{title}」这个窗口，但它看着不像在放片、"
                        "电脑也没有在出声。跟主人确认一下：要就这个窗口就说一声，"
                        "不然把播放器窗口名告诉你。",
                        prompts.FALLBACK_NEED_CONFIRM.format(title=title))
                    if speak:
                        self._speak(text)
                    return "need_confirm", text
                self.log.info("[movie_watch] 窗口不像播放器，但回环有声音，按在放片处理")
        window_title = capture.title if cfg.mode == "window" else "整块屏幕"
        if not window_title:
            window_title = "（未知窗口）"

        # ---------- 台词识别（扬声器回环 + SenseVoice，独立会话） ----------
        dialogue_ok = ensure_dialogue()
        if not dialogue_ok:
            self.log.info(f"[movie_watch] 台词识别不可用：{dialogue.detail}")

        session_id = store.new_session_id()
        try:
            session_dir = store.prepare(store.session_dir(cfg, session_id))
        except Exception:
            self.log.exception("[movie_watch] 创建缓存目录失败")
            dialogue.stop()
            return "error", "缓存目录建不起来，先看不成啦"

        started = time.time()
        meta = {
            "session": session_id,
            "uid": str(uid or ""),
            "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
            "started_ts": started,
            "window_title": window_title,
            "capture_mode": cfg.mode,
            "interval_text": f"{cfg.min_interval}~{cfg.max_interval} 秒（随机）",
            "vision": vision.detail,
            "dialogue": dialogue.detail,
            "ended": "",
            "duration_text": "",
            "notes": 0,
        }
        try:
            store.write_json(store.meta_path(session_dir), meta)
        except Exception:
            self.log.exception("[movie_watch] 写 meta 失败")

        with self._lock:
            if self._active:
                shutil.rmtree(session_dir, ignore_errors=True)
                dialogue.stop()
                text = self._line(brain, uid,
                                  "主人又说要看片，可你已经在陪他看了；说一声已经在看。",
                                  prompts.FALLBACK_BUSY)
                return "busy", text
            self._active = True
            self._finalized = False
            self._stop = threading.Event()
            self._uid = str(uid or "")
            self._sid = session_id
            self._dir = session_dir
            self._meta = meta
            self._notes = []
            self._started = started
            self._capture = capture
            self._gone_since = None
            self._dialogue = dialogue if dialogue_ok else None
            self._last_capture_ts = started
            self._thread = threading.Thread(
                target=self._loop, args=(cfg, vision, session_dir), daemon=True)
            self._thread.start()

        self._enter_state()
        self.log.info(f"[movie_watch] 开播：{window_title}，视觉={vision.detail}，"
                      f"台词={dialogue.detail}，间隔={cfg.min_interval}~{cfg.max_interval}s")
        ack = ""
        if cfg.start_line:
            facts = []
            if cfg.report_window and cfg.mode == "window" and capture.title:
                facts.append(f"你绑到了「{self._short(capture.title, 20)}」这个窗口")
            if not dialogue_ok:
                facts.append(f"台词识别没连上（{dialogue.detail}），这次只能看画面")
            instruction = (
                "你已经安顿下来、准备安静陪主人看这场片了。"
                + ("；".join(facts) + "。" if facts else "")
                + (f"另外要传达：{cfg.start_hint}。" if cfg.start_hint else "")
                + "告诉主人你要安静陪看、接下来好一会儿不会说话、看完跟主人说一声就行。")
            ack = self._line(brain, uid, instruction, prompts.FALLBACK_START)
        if speak and ack:
            self._speak(ack)
        return "started", ack or "开始看了"

    @staticmethod
    def is_force_text(text):
        text = str(text or "")
        return any(word in text for word in FORCE_WORDS)

    @staticmethod
    def _short(text, limit=20):
        text = str(text or "").strip()
        return text if len(text) <= limit else text[:limit] + "…"

    # ==================== 用户提问 ====================
    def ask(self, question="", uid="", speak=True):
        if not self.ctx:
            return "error", "插件还没准备好"
        cfg = self.config()
        with self._lock:
            active = self._active
            notes = list(self._notes)
            meta = dict(self._meta)
        if not active:
            notes, meta = self._archived_notes(cfg, uid)
        if not notes:
            brain = MovieBrain(self.ctx, cfg, self.log)
            if active:
                text = self._line(brain, uid,
                                  "主人问剧情，可你还没记到任何画面；跟主人说再等一会儿。",
                                  prompts.FALLBACK_NO_NOTES)
                if speak:
                    self._speak(text)
                return "ok", text
            text = self._line(brain, uid,
                              "主人问的像是观影内容，但你们这场还没一起看过片；"
                              "告诉主人还没一起看过，说一句「陪我看电影」你就来。",
                              prompts.FALLBACK_NO_SESSION)
            if speak:
                self._speak(text)
            return "idle", text
        brain = MovieBrain(self.ctx, cfg, self.log)
        answer = brain.answer(question, notes, meta, uid)
        if speak and answer:
            self._speak(answer)
        return "ok", answer

    def _archived_notes(self, cfg, uid):
        """读最近一场归档（先按本人，再按共享目录，最后扫全场次）"""
        candidates = [uid, ""]
        seen = []
        for owner in candidates:
            latest = store.load_latest(cfg, owner)
            folder = latest.get("dir") or ""
            if folder and folder not in seen and os.path.isdir(folder):
                seen.append(folder)
                meta = store.read_json(os.path.join(folder, "meta.json"), {}) or {}
                notes = store.load_notes(folder)
                if notes or meta:
                    return notes, meta if isinstance(meta, dict) else {}
        # 兜底：直接找归档根目录下最新的 latest.json
        base = cfg.archive_base
        best = None
        try:
            for name in os.listdir(base) if os.path.isdir(base) else []:
                path = os.path.join(base, name, "latest.json")
                data = store.read_json(path, {})
                if not isinstance(data, dict):
                    continue
                if best is None or str(data.get("started", "")) > str(best.get("started", "")):
                    best = data
        except Exception:
            best = None
        if best:
            folder = best.get("dir") or ""
            if folder and os.path.isdir(folder):
                meta = store.read_json(os.path.join(folder, "meta.json"), {}) or {}
                return store.load_notes(folder), meta if isinstance(meta, dict) else {}
        return [], {}

    # ==================== 结束 ====================
    def stop(self, uid="", reason="user", speak=True):
        with self._lock:
            active = self._active
            thread = self._thread
        if not active:
            text = "现在没有在观影呀"
            if self.ctx:
                brain = MovieBrain(self.ctx, self.config(), self.log)
                text = self._line(brain, uid,
                                  "主人说要结束观影，可你们现在并没有在看片；"
                                  "跟主人说一声现在没在陪看。", text)
            if speak:
                self._speak(text)
            return "idle", text
        self._stop.set()
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=10)
        return self._finalize(reason=reason, speak=speak)

    def _finalize(self, reason="user", speak=True):
        """收尾：整体影评 → 写 ending → 归档 → 写短期记忆 → 退状态"""
        with self._lock:
            if self._finalized or not self._active:
                return "idle", ""
            self._finalized = True
            self._active = False
            notes = list(self._notes)
            meta = dict(self._meta)
            session_id = self._sid
            session_dir = self._dir
            uid = self._uid
            dialogue = self._dialogue
            self._dialogue = None
        if dialogue is not None:
            try:
                dialogue.stop()
            except Exception:
                self.log.exception("[movie_watch] 停止台词识别失败")

        cfg = self.config()
        elapsed = time.time() - float(meta.get("started_ts") or time.time())
        meta.update({
            "ended": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_text": self._duration_text(elapsed),
            "duration_seconds": int(elapsed),
            "notes": len(notes),
            "reason": reason,
        })
        brain = MovieBrain(self.ctx, cfg, self.log)
        ending = brain.finish_review(notes, meta, uid)
        if not cfg.keep_shots:
            self._drop_shots(notes, session_dir)
        try:
            store.write_json(store.meta_path(session_dir), meta)
            store.write_text(store.ending_path(session_dir), ending)
        except Exception:
            self.log.exception("[movie_watch] 写收尾文件失败")
        dest = ""
        try:
            dest = store.archive(cfg, session_dir, uid, session_id, meta, notes, ending)
        except Exception:
            self.log.exception("[movie_watch] 归档失败")
        if dest:
            self.log.info(f"[movie_watch] 已归档：{dest}（{len(notes)} 条记录）")
        else:
            self.log.warning("[movie_watch] 归档未完成，缓存保留在 .temp")
        self._save_short_memory(cfg, meta, ending, notes)
        self._exit_state()

        with self._lock:
            self._thread = None
            self._dir = ""
            self._sid = ""
            self._meta = {}
            self._notes = []
            self._capture = None
            self._started = 0.0
        if speak and ending:
            self._speak(ending)
        return "finished", ending

    def _drop_shots(self, notes, session_dir):
        """不留截图：连文件一起清掉，记录里去掉路径"""
        for note in notes:
            note["shot"] = ""
        try:
            import shutil
            shutil.rmtree(store.shots_dir(session_dir), ignore_errors=True)
        except Exception:
            pass

    def _save_short_memory(self, cfg, meta, ending, notes):
        """结束后留一条短期记忆，日常聊天也能提到这一场"""
        if not cfg.short_memory:
            return
        content = (f"【观影】刚和主人一起看了场电影（{meta.get('window_title') or '一部片'}），"
                   f"看了{meta.get('duration_text') or '一会儿'}，"
                   f"我记了{len(notes)}幕。整体感觉：{ending[:100]}")
        try:
            self.ctx.short_memory().save(
                {"role": "assistant", "content": content, "type": "movie_watch"},
                20, trim_mode="items")
        except Exception:
            self.log.exception("[movie_watch] 写短期记忆失败")

    # ==================== 后台循环 ====================
    def _loop(self, cfg, vision, session_dir):
        reason = "user"
        try:
            while not self._stop.is_set():
                interval = random.uniform(cfg.min_interval, cfg.max_interval)
                self.log.info(f"[movie_watch] 下次截屏在 {int(interval)} 秒后")
                if not self._wait(interval, cfg):
                    reason = "window_gone"
                    break
                if self._stop.is_set():
                    reason = "user"
                    break
                if self._elapsed() >= cfg.max_duration:
                    reason = "timeout"
                    break
                self._capture_once(cfg, vision, session_dir)
        except Exception:
            self.log.exception("[movie_watch] 观影循环异常")
            reason = "error"
        finally:
            if reason in ("window_gone", "timeout", "error"):
                self._finalize(reason=reason, speak=True)

    def _wait(self, seconds, cfg):
        """分片等待；绑定窗口消失并持续确认后返回 False"""
        deadline = time.time() + max(1.0, float(seconds))
        confirm = int(cfg.window_gone_confirm)
        while not self._stop.is_set():
            now = time.time()
            if now >= deadline:
                return True
            if confirm > 0 and self._capture and self._capture.hwnd:
                if self._capture.is_alive():
                    self._gone_since = None
                else:
                    if self._gone_since is None:
                        self._gone_since = now
                    elif now - self._gone_since >= confirm:
                        self.log.info("[movie_watch] 播放器窗口消失，判定观影结束")
                        return False
            self._stop.wait(min(3.0, max(0.2, deadline - now)))
        return True

    def _elapsed(self):
        with self._lock:
            started = self._started
        return time.time() - started if started else 0.0

    def _capture_once(self, cfg, vision, session_dir):
        with self._lock:
            index = len(self._notes) + 1
            uid = self._uid
            title = str(self._meta.get("window_title") or "")
            started = self._started
            dialogue = self._dialogue
            last_ts = self._last_capture_ts or started
        if index > cfg.max_notes:
            self.log.info("[movie_watch] 记录条数已达上限，本场不再记录新画面")
            return
        clock = self._clock_text(time.time() - started)
        if (cfg.mode == "window" and self._capture and self._capture.hwnd
                and not self._capture.is_alive()):
            self.log.info("[movie_watch] 播放器窗口不在了，这一帧跳过")
            return
        name = f"{index:03d}_{time.strftime('%H%M%S')}.jpg"
        image_path = os.path.join(store.shots_dir(session_dir), name)
        ok, width, height = self._capture.grab(image_path)
        if not ok:
            self.log.warning("[movie_watch] 这一帧没截到，跳过")
            return

        # 台词窗口 = 上一帧到现在，保证「这一帧的画面」配「这一段的台词」
        frame_ts = time.time()
        span = max(5.0, min(frame_ts - last_ts, float(cfg.dialogue_window)))
        heard = dialogue.window_text(seconds=int(span)) if dialogue is not None else ""
        system = self._review_system(uid)
        user = prompts.REVIEW_USER.format(
            title=title, clock=clock, index=index,
            heard=(prompts.HEARD_WITH_TEXT.format(dialogue=heard) if heard
                   else prompts.HEARD_EMPTY))
        result = vision.observe(image_path, system, user)
        if result is None:
            self.log.warning("[movie_watch] 这一帧没看懂，跳过")
            self._remove_file(image_path)
            return

        comment = str(result.get("comment") or "").strip()
        if len(comment) > cfg.comment_chars:
            comment = comment[:cfg.comment_chars - 1].rstrip("，。,.、 ") + "…"
        note = {
            "ts": frame_ts,
            "clock": clock,
            "time": time.strftime("%H:%M:%S", time.localtime(frame_ts)),
            "span": int(span),
            "shot": f"shots/{name}",
            "scene": str(result.get("scene") or ""),
            "comment": comment,
            "dialogue": heard,
            "size": f"{width}x{height}",
        }
        if not cfg.keep_shots:
            note["shot"] = ""
            self._remove_file(image_path)
        with self._lock:
            self._last_capture_ts = frame_ts
            self._notes.append(note)
            total = len(self._notes)
            self._meta["notes"] = total
            meta = dict(self._meta)
        try:
            store.append_note(session_dir, note)
            store.write_json(store.meta_path(session_dir), meta)
        except Exception:
            self.log.exception("[movie_watch] 写记录失败")
        self.log.info(f"[movie_watch] 第 {total} 幕（{clock}）："
                      f"{(note['scene'] or note['comment'])[:40]}")

    @staticmethod
    def _remove_file(path):
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    def _review_system(self, uid):
        brain = MovieBrain(self.ctx, self.config(), self.log)
        persona = brain.persona(uid)
        return f"{persona}\n\n{prompts.REVIEW_SYSTEM}" if persona else prompts.REVIEW_SYSTEM

    # ==================== 会话拦截 ====================
    def route_text(self, text, uid="", channel=""):
        """观影进行中：接管「结束」与「提问」，其余输入放行给主链路"""
        if not self.ctx or not self._active:
            return False
        text = str(text or "").strip()
        if not text:
            return False
        if self.is_stop_text(text):
            self.log.info(f"[movie_watch] 用户告知观影结束：{text[:20]}")
            self.stop(uid, "user", speak=True)
            return True
        if self.is_ask_text(text):
            self.log.info(f"[movie_watch] 用户提问观影内容：{text[:20]}")
            self.ask(text, uid, speak=True)
            return True
        return False

    # ==================== 插件状态 / 语音 ====================
    def _state_handle(self):
        try:
            return self.ctx.state()
        except Exception:
            self.log.exception("[movie_watch] 获取插件状态句柄失败")
            return None

    def _enter_state(self):
        handle = self._state_handle()
        if handle is None:
            return
        try:
            handle.enter()
        except Exception:
            self.log.exception("[movie_watch] 进入插件状态失败")

    def _exit_state(self):
        handle = self._state_handle()
        if handle is None:
            return
        try:
            handle.exit()
        except Exception:
            self.log.exception("[movie_watch] 退出插件状态失败")

    def _speak(self, text):
        if not text:
            return
        # 自己在说话：这段时间别把喇叭里的声音当成台词
        dialogue = self._dialogue
        if dialogue is not None:
            try:
                dialogue.suppress_for(max(3.0, len(str(text)) / 5.0) + 1.5)
            except Exception:
                pass
        try:
            emotion = getattr(self.config(), "emotion", "") if self.ctx else ""
            self.ctx.tts().send_stream(str(text), source="toolbox_movie_watch",
                                       emotion=emotion)
        except Exception:
            self.log.exception("[movie_watch] 语音播报失败")

    @staticmethod
    def _clock_text(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    @staticmethod
    def _duration_text(seconds):
        seconds = max(0, int(seconds))
        hours, rest = divmod(seconds, 3600)
        minutes = rest // 60
        if hours:
            return f"{hours}小时{minutes}分钟"
        if minutes:
            return f"{minutes}分钟"
        return f"{seconds}秒"

    def teardown(self):
        """插件卸载：停掉循环，尽量把已有记录归档"""
        if not self._active:
            return
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._finalize(reason="teardown", speak=False)


SESSION = MovieSession()
