import os
import re
import threading
import time

from .config import EpubConfig
from .parser import (list_books, match_book, load_book, split_sections, query_volumes,
                     explicit_volume, strip_volume_phrase, series_summary, recent_state_book)
from .store import load_state, save_state
from .port import EpubLLM
from .brain import BookBrain


# 续读意图
CONTINUE_WORDS = ("继续", "接着", "然后呢", "后来", "读下去", "别停", "往下读",
                  "念下去", "再读", "go on", "continue")

# 停止朗读意图（仅这些词才接管并停下朗读，其余输入一律放行给主链路）
STOP_WORDS = ("停", "别读", "不要读", "不读了", "不听了", "别念", "不要念",
              "别讲了", "打住", "暂停", "不用读了", "读到这里", "stop", "pause")

# 读完后窗口内：只有像「点书/续读」的话才接管，普通对话一律放行（否则会吞输入）
BOOK_HINT_WORDS = ("书", "读", "念", "小说", "下一本", "换一本", "接着", "继续", "听完")


class BookSession:
    # 询问书名时的等待上限（秒）：过长会一直吞掉用户的正常对话
    ASK_TIMEOUT = 25

    def __init__(self):
        """读书会话：单本朗读 + 续读窗口"""
        self.ctx = None
        self.log = None
        self._active = False
        self._asking = False          # 是否正在等用户回答"读哪一本"（防重入）
        self._last_title = ""         # 本次/上次在读的书（用于只报卷号时消歧）
        self._stop = threading.Event()
        self._window = None
        self._username = ""
        self._lock = threading.Lock()
        self._overrides = {}

    # ==================== 基础 ====================
    def set_ctx(self, ctx):
        """注入插件上下文"""
        self.ctx = ctx
        self.log = ctx.log

    def is_active(self):
        """是否正在朗读"""
        return self._active

    def config(self):
        """当前配置"""
        return EpubConfig(self.ctx.config if self.ctx else {})

    # ==================== 启动 ====================
    def start(self, request, book_query, mode, username):
        """开始或续读（后台线程）

        重量级动作（LLM 探测、书名匹配、TTS 播报）全部放在锁外，
        锁内只做"占位 + 起线程"，避免长时间持锁。
        """
        if not self.ctx:
            return "插件未初始化"
        with self._lock:
            if self._active:
                busy = True
            else:
                busy = False
        if busy:
            return self._tip_busy()

        cfg = self.config()
        probe = EpubLLM(cfg)
        if not probe.available():
            return self._tip_unavailable(probe.last_error)
        if not self._last_title:
            # 进程重启后沿用「上次在读的书」，让"接着读第二本"也能正确定位到同一系列
            self._last_title = recent_state_book(cfg.state_dir)
        path, title = match_book(cfg.books_dir, book_query or request, cfg.state_dir,
                                 prefer=self._last_title)
        if not path and self._last_title and self._is_continue(request, book_query):
            # 「继续读 / 接着念」但没点名书 → 接着上次那本（窗口过期后也能续上）
            path, title = match_book(cfg.books_dir, self._last_title, cfg.state_dir)
            if path:
                self.log.info(f"续读意图命中上次的书：{title}")
        if not path:
            self._ask_book(cfg, username)
            return "待选书"

        with self._lock:
            if self._active:                 # 二次检查：锁外可能已被别的请求占位
                return self._tip_busy()
            self._clear_window()
            self._active = True              # 先占位，避免并发双开
            self._username = str(username or "")
            self._last_title = title         # 记下在读的书，供"接着读第二本"消歧
            threading.Thread(target=self._run, args=(cfg, path, title, username),
                             daemon=True).start()
        return "已开始"

    def _tip_busy(self):
        """已在朗读中的提示"""
        self._speak("已经有一本在读啦，先等这本读完吧")
        return "已有读书会话"

    def _tip_unavailable(self, err):
        """LLM 未配置的提示"""
        self._speak(f"读书助手还没配置好呢：{err}")
        return f"不可用：{err}"

    # ==================== 会话拦截 ====================
    def route_text(self, text, username=""):
        """会话拦截：朗读中打断 / 窗口内续读

        原则：除「明确的停/继续指令」外，绝不吞掉用户输入。
        """
        if not self.ctx:
            return False
        text = str(text or "").strip()
        if not text:
            return False

        # ---- 朗读中 ----
        if self._active:
            return self._route_active(text, username)

        # ---- 续读窗口内 ----
        cfg = self.config()
        win = self._get_window(cfg)
        if not win:
            return False
        if not self._looks_like_read_request(text):
            # 与读书无关的普通对话：放行且不关窗口
            # （窗口是「朗读结束后 followup_window 秒」内的续读机会，期间随便聊不影响续读）
            return False
        if win.get("finished"):
            self._clear_window()
            self._speak("这本已经读完啦，想听别的跟我说书名就行")
            return True
        if any(w in text for w in CONTINUE_WORDS):
            go = True
        else:
            probe = EpubLLM(cfg)
            if probe.available():
                go = BookBrain(probe, self.ctx).judge_continue(win["book"], text)
            else:
                self.log.warning("续读判定不可用（LLM 未配置），按不继续处理")
                go = False
        if go:
            self.start(text, win["book"], "resume", username)
            return True
        self._clear_window()
        return False

    def _route_active(self, text, username):
        """朗读中的输入：停止词接管；纯继续词忽略；其它一律放行（先打断避免混音）"""
        # 说话人未知时（框架没注入 username），把首个输入者认定为朗读者，
        # 否则会把所有人的话都当成「本人」，一有声音就打断朗读。
        if not self._username and username:
            self._username = str(username)
        same_user = (not self._username) or (str(username or "") == self._username)

        if any(w in text for w in STOP_WORDS):
            self._interrupt()
            self._speak("好，那先停在这里吧")
            return True

        if any(w in text for w in CONTINUE_WORDS):
            # 只有「纯继续词」（去掉继续词后没有别的内容）才忽略；
            # 「继续读别的书」这类含新意图的话要按正常输入处理，不能吞掉。
            rest = text
            for w in CONTINUE_WORDS:
                rest = rest.replace(w, "")
            if len(re.sub(r"[\s,，。！!？?、~～.·]+", "", rest)) <= 1:
                return True
            self.log.info("朗读中收到含新意图的输入：按正常输入处理")

        if same_user:
            self.log.info("朗读中收到新输入：先停下朗读，并把该输入放行给主链路")
            self._interrupt()
        return False

    @staticmethod
    def _is_continue(request, book_query=""):
        """是否续读意图（含继续类词且没点名具体书）"""
        text = f"{request or ''} {book_query or ''}"
        return any(w in text for w in CONTINUE_WORDS)

    @staticmethod
    def _looks_like_read_request(text):
        """判断是否像「点书/续读」的表达（用于续读窗口的接管判定与续读判定前置过滤）"""
        return (any(w in text for w in BOOK_HINT_WORDS)
                or any(w in text for w in CONTINUE_WORDS))

    # ==================== 朗读主流程 ====================
    def _run(self, cfg, path, title, username):
        """朗读主流程"""
        self._active = True
        self._stop.clear()
        read_buf = []
        char_count = 0
        chapter_idx = 0
        section_idx = 0
        finished = False
        readable = False          # 是否真的解析出可读章节（决定要不要开续读窗口）
        self._overrides = self._apply_overrides(cfg)
        self._enter_state()
        try:
            book = load_book(path)
            chapters = book.get("chapters") or []
            if not chapters:
                self._speak("这本书没有可读的内容呢")
                return
            readable = True
            state = load_state(cfg.state_dir, title)
            if state and not state.get("finished"):
                chapter_idx = max(0, int(state.get("chapter", 0)))
                section_idx = max(0, int(state.get("section", 0)))
                # 进度越界校验：书目升级/章节数变化时不能静默跳章，更不能误判成「读完」
                if chapter_idx >= len(chapters):
                    self.log.warning("阅读进度越界（章节数已变化），从第一章重新开始")
                    chapter_idx, section_idx = 0, 0
                else:
                    total = len(split_sections(chapters[chapter_idx]["text"], cfg.section_paras))
                    if section_idx > total:
                        self.log.warning("本节进度越界，从本章开头继续")
                        section_idx = 0
            self._speak(f"那我开始读《{title}》啦")
            while chapter_idx < len(chapters) and not self._stop.is_set():
                sections = split_sections(chapters[chapter_idx]["text"], cfg.section_paras)
                for si in range(section_idx, len(sections)):
                    if self._stop.is_set():
                        break
                    if not self._read_section(cfg, sections[si]):
                        break          # 被打断：本节未读完，不推进进度（续读时重读）
                    read_buf.append(sections[si])
                    char_count += len(sections[si])
                    section_idx = si + 1
                    save_state(cfg.state_dir, title, chapter_idx, section_idx, False)
                if self._stop.is_set():
                    break
                chapter_idx += 1
                section_idx = 0
                if char_count >= cfg.min_chars:
                    break
            if chapter_idx >= len(chapters):
                finished = True
            save_state(cfg.state_dir, title, chapter_idx, section_idx, finished)
            # 被打断时也要把「已读完的部分」写进记忆：只写记忆，不概括出声、不点评
            self._finish(cfg, title, username, "\n".join(read_buf), finished,
                         interrupted=self._stop.is_set())
        except Exception:
            self.log.exception("读书流程异常")
        finally:
            self._restore_overrides()
            self._exit_state()
            self._active = False
            if readable:
                self._open_window(title, chapter_idx, section_idx, finished)
            else:
                self._clear_window()      # 没读成（空书/异常）：不开续读窗口

    def _read_section(self, cfg, text):
        """朗读一小节；返回 True=完整读完，False=被打断"""
        if not text or not text.strip():
            return True
        try:
            self.ctx.tts().send_stream(text, source="toolbox_epub_reader", emotion=cfg.emotion)
        except Exception:
            self.log.exception("朗读失败")
            return False
        return self._wait(cfg, text)

    def _wait(self, cfg, text):
        """等待本节读完；返回 True=自然读完，False=被打断。

        队列里可能排着别的语音（待办提醒、礼物感谢等），它们会让 TTS 持续忙，
        因此这里不按固定时长超时，而是等总线彻底空闲——保证「本节念完 → 提醒播完
        → 再读下一节」，既不掐断提醒，也不会把本节没播完的内容冲掉。
        兜底上限：估算时长的 2 倍 + 60 秒（防止 TTS 异常时线程卡死）。
        """
        speed = max(0.3, float(getattr(cfg, "speed", 1.0) or 1.0))
        estimate = max(cfg.section_wait, len(text) / (5.0 * speed))
        deadline = time.time() + estimate * 2 + 60
        time.sleep(min(1.0, estimate))
        while time.time() < deadline:
            if self._stop.is_set():
                return False
            time.sleep(0.3)
            try:
                if not self.ctx.tts().is_busy():
                    return not self._stop.is_set()
            except Exception:
                return True
        self.log.warning("等待本节播报超时，继续朗读下一节")
        return True

    def _interrupt(self):
        """打断朗读（停止推送 + 清空 TTS 队列）"""
        self._stop.set()
        try:
            self.ctx.tts().interrupt()
        except Exception:
            self.log.exception("打断朗读失败")

    # ==================== 概括 / 记忆 / 点评 ====================
    def _finish(self, cfg, title, username, read_text, finished, interrupted=False):
        """概括 → 写记忆 →（未被打断时）点评

        被打断时：仍然概括已读内容并写短期/长期记忆，但不出声、不点评，
        避免和用户刚说的话抢话。
        """
        if not read_text.strip():
            if finished and not interrupted:
                self._speak(f"《{title}》读完啦")
            return
        brain = BookBrain(EpubLLM(cfg), self.ctx)
        summary = brain.summarize(title, read_text)
        if summary:
            self._save_memory(cfg, username, title, summary)
        if interrupted:
            self.log.info("朗读被打断：已把读过的内容概括写入记忆，跳过出声点评")
            return
        if finished:
            self._speak(f"《{title}》到这里就读完啦～")
        comment = brain.comment(username, title, summary)
        if comment:
            self._speak(comment)

    def _save_memory(self, cfg, username, title, summary):
        """把概括写入短期/长期/用户记忆"""
        content = f"【读书】《{title}》{summary}"
        try:
            self.ctx.short_memory().save(
                {"role": "assistant", "content": content, "type": "epub_reader"},
                cfg.short_mem_limit, trim_mode="items")
        except Exception:
            self.log.exception("读书短期记忆写入失败")
        try:
            self.ctx.ltmem().record_ai_message(username or "用户", self.ctx.ai_name(), content)
        except Exception:
            self.log.exception("读书长期记忆写入失败")

    def _speak(self, text):
        """语音播报（朗读声线）"""
        if not text:
            return
        try:
            self.ctx.tts().send_stream(text, source="toolbox_epub_reader",
                                       emotion=self.config().emotion)
        except Exception:
            self.log.exception("读书播报失败")

    def _ask_book(self, cfg, username):
        """excuse 询问读哪一本（短等待；回复支持书名或口语序号）

        防重入：excuse 内部按用户名为 key 保存等待队列，若并发第二次询问会把
        第一次的队列顶掉，两个询问都会拿不到答案，因此这里直接拒绝重复询问。
        """
        if self._asking:
            self.log.info("已在等待用户回答书名，忽略重复询问")
            return
        self._asking = True
        try:
            books = [os.path.splitext(b)[0] for b in list_books(cfg.books_dir)]
            tip = "要读哪一本呢？"
            series = series_summary(cfg.books_dir)
            if series:
                tip += "我这儿有：" + "、".join(
                    f"{s['name']}（{s['count']}卷）" for s in series[:6])
            try:
                reply = self.ctx.excuse().ask(tip, username, timeout=self.ASK_TIMEOUT)
            except Exception:
                self.log.exception("读书询问失败")
                return
            if not reply:
                return
            path, title = self._pick_book(cfg, reply, books, prefer=self._last_title)
            if path:
                self.start(reply, title, "read", username)
            else:
                self._speak("没找到这本书呢，说书名里的几个字、或者第几卷就行")
        finally:
            self._asking = False

    # 仅当回复"整串就是一个序号"时，才按库内顺序兜底取书
    _PICK_INDEX = re.compile(r"^\s*第?\s*\d{1,2}\s*[本卷册部集]?\s*$")

    @classmethod
    def _pick_book(cls, cfg, reply, books, prefer=""):
        """按回复选书

        1) 先交给 match_book：它已支持「只报卷号」（第二本 / 第2卷 / 从第二本开始读），
           并能按「在读系列（prefer）」在多系列间消歧；
        2) 只有回复是纯序号、且书名匹配不到时，才按库内顺序取第 N 本兜底。
        """
        path, title = match_book(cfg.books_dir, reply, cfg.state_dir, prefer=prefer)
        if path:
            return path, title
        text = str(reply or "").strip()
        if cls._PICK_INDEX.match(text) and not strip_volume_phrase(text).strip():
            idx = int(re.sub(r"\D", "", text) or 0) - 1
            if 0 <= idx < len(books):
                return match_book(cfg.books_dir, books[idx], cfg.state_dir)
        return "", ""

    # ==================== 插件状态（标准接口） ====================
    def _state_handle(self):
        """取插件状态句柄（框架未提供时返回 None）"""
        try:
            return self.ctx.state()
        except Exception:
            self.log.exception("获取插件状态句柄失败")
            return None

    def _enter_state(self):
        """进入插件状态：不读弹幕 + 暂停主动回复计时（能力位见 plugin.state_decl）"""
        handle = self._state_handle()
        if handle is None:
            return
        try:
            handle.enter()
        except Exception:
            self.log.exception("进入插件状态失败")

    def _exit_state(self):
        """退出插件状态：释放能力位占用（幂等，异常路径也会调到）"""
        handle = self._state_handle()
        if handle is None:
            return
        try:
            handle.exit()
        except Exception:
            self.log.exception("退出插件状态失败")

    # ==================== 语速 / 声线临时覆盖 ====================
    def _apply_overrides(self, cfg):
        """朗读期间让「朗读语速 / 朗读声线」真正生效。

        框架的 TTS 队列不支持按段透传 speed / emotion（tts_core._synth_task 重建
        消息时只保留 7 个字段），所以这里在朗读期间临时覆盖全局 TTS 配置，
        读完（或异常退出）立即还原，改动全部收敛在本插件内。
        """
        old = {}
        try:
            from func.tts.tts_core import TTsCore
            conf = getattr(getattr(TTsCore(), "sovits", None), "config", None)
            speed = float(getattr(cfg, "speed", 0) or 0)
            if conf is not None and speed > 0:
                cur = float(getattr(conf, "speed", 1.0))
                if abs(speed - cur) > 1e-6:
                    old["speed_conf"] = conf
                    old["speed"] = cur
                    old["speed_set"] = speed          # 记录"我们设的值"，还原前核对
                    conf.speed = speed
                    self.log.info(f"朗读语速临时覆盖：{cur} → {speed}")
        except Exception:
            self.log.exception("设置朗读语速失败")

        try:
            from func.pipeline.llm_emotion import LLMEmotionBridge
            bridge = LLMEmotionBridge()
            emotion = str(getattr(cfg, "emotion", "") or "")
            cur_emotion = getattr(bridge, "_emotion", None)
            if emotion and cur_emotion and emotion != cur_emotion:
                old["emotion_bridge"] = bridge
                old["emotion_old"] = (cur_emotion, getattr(bridge, "_intensity", 3.0))
                old["emotion_forced"] = emotion
                bridge._emotion = emotion          # 直接写内存，不触发表情订阅
                bridge._intensity = 3.0
                self.log.info(f"朗读声线临时覆盖：{cur_emotion} → {emotion}")
        except Exception:
            self.log.exception("设置朗读声线失败")
        return old

    def _restore_overrides(self):
        """还原朗读期间的临时全局覆盖"""
        over = self._overrides or {}
        self._overrides = {}
        conf = over.get("speed_conf")
        if conf is not None and "speed" in over:
            try:
                # 只有当前值仍是我们设的那个才还原，避免覆盖用户/其它逻辑中途的改动
                cur = float(getattr(conf, "speed", 0))
                if abs(cur - float(over.get("speed_set", -1))) < 1e-6:
                    conf.speed = over["speed"]
                    self.log.info(f"朗读语速已还原：{over['speed']}")
                else:
                    self.log.warning(f"语速当前为 {cur}（已被其它逻辑改写），跳过还原")
            except Exception:
                self.log.exception("还原朗读语速失败")
        bridge = over.get("emotion_bridge")
        if bridge is not None and over.get("emotion_forced"):
            try:
                if getattr(bridge, "_emotion", None) == over["emotion_forced"]:
                    bridge._emotion, bridge._intensity = over["emotion_old"]
                    self.log.info("朗读声线已还原")
            except Exception:
                self.log.exception("还原朗读声线失败")

    # ==================== 续读窗口 ====================
    def _open_window(self, title, chapter, section, finished=False):
        """开启续读窗口"""
        self._window = {"ts": time.time(), "book": title,
                        "chapter": chapter, "section": section, "finished": bool(finished)}

    def _clear_window(self):
        """关闭续读窗口"""
        self._window = None

    def _get_window(self, cfg):
        """取有效续读窗口"""
        if not self._window or not cfg.followup_enabled:
            return None
        if time.time() - self._window["ts"] > cfg.followup_window:
            self._window = None
            return None
        return self._window


SESSION = BookSession()
