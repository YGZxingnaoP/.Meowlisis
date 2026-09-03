# ================== tts_core.py ==================
# TTS 核心调度：合成 + 顺序播放，组合 config/interrupt/subtitle/action 子模块
import json
import os
import queue
import random
import re
import threading
import time
import uuid
from threading import Lock, Thread
from concurrent.futures import ThreadPoolExecutor

from func.log.default_log import DefaultLog
from func.tts.config import TTSConfig
from func.tts.emotion import resolve_emotion, resolve_ref_audio
from func.tts.gpt_sovits import GptSovits
from func.tts.player import AudioPlayer
from func.tts.subtitle import SubtitleWorker
from func.tts.interrupt import InterruptManager
from func.pipeline.get_subtitle import GetSubtitleBridge
from func.tools.singleton_mode import singleton
from func.tts.state import TTsState
from func.llm.state import LLmState
from func.config.app_config import AppConfig
from func.pipeline.system_prompt import SystemPromptBridge
from func.pipeline.sensevoice_tts import SenseVoiceTtsBridge


class StreamSource:
    """流式音频源：生产者(pump线程)向 buffer 填字节，消费者(播放线程)从 buffer 取字节。"""

    _END = object()

    def __init__(self, generator, cancel_func=None, traceid="", seg_index=0,
                 sample_rate=None, channels=1, source="other"):
        self.generator = generator
        self.cancel_func = cancel_func
        self.traceid = traceid
        self.seg_index = seg_index
        self.sample_rate = sample_rate
        self.channels = channels
        self.source = source or "other"
        self.buffer = queue.Queue()
        self.cancelled = False
        self.finished = False
        self._lock = threading.Lock()

    def push(self, chunk: bytes) -> bool:
        """写入一块字节，返回是否成功（已取消则丢弃）"""
        with self._lock:
            if self.cancelled:
                return False
            self.buffer.put(chunk)
            return True

    def finish(self):
        """标记流结束（放入结束哨兵）"""
        with self._lock:
            if self.cancelled:
                return
            self.finished = True
            self.buffer.put(self._END)

    def pop(self, timeout: float = 0.5):
        """取出下一块字节，返回 (data, finished)。

        - data 为 bytes：正常音频块；
        - data 为 b"" 且 finished=False：暂时无数据（等待）；
        - data 为 None 且 finished=True：流结束或已被取消。
        """
        if self.cancelled:
            return None, True
        try:
            item = self.buffer.get(timeout=timeout)
        except queue.Empty:
            if self.cancelled:
                return None, True
            return b"", False
        if item is self._END:
            return None, True
        return item, False

    def cancel(self):
        """取消流：置取消标志、唤醒阻塞消费者并关闭 HTTP 连接（若提供）"""
        with self._lock:
            self.cancelled = True
            # 放入哨兵，唤醒可能阻塞在 get 的播放线程，避免最多等待 timeout
            self.buffer.put(self._END)
        if self.cancel_func:
            try:
                self.cancel_func()
            except Exception:
                pass


@singleton
class TTsCore:
    log = DefaultLog().getLogger()

    def __init__(self):
        # 数据实体与集中配置
        self.ttsData = TTsState()
        self.llmData = LLmState()
        self.config = TTSConfig()

        # 桥接依赖：角色提示词（未实现）与说话状态（打断）
        self.system_prompt = SystemPromptBridge()
        self.sensevoice_tts = SenseVoiceTtsBridge()

        # 引擎、播放器
        self.sovits = GptSovits()
        self.player = AudioPlayer()

        # 字幕独立线程
        self.subtitle = SubtitleWorker(
            self.ttsData,
            is_paused=self._is_paused,
        )

        # 打断管理器（按键/pipeline 可配置）
        self.interrupt = InterruptManager(
            self.config,
            on_interrupt=self._interrupt_playback,
            sensevoice_tts=self.sensevoice_tts,
            is_paused=self._is_paused,
            on_speech_end=self._resume_after_interrupt,
        )

        # 播放队列与分段顺序控制
        self.play_queue = queue.Queue()
        self.pending_lock = Lock()
        self.pending_segments = {}

        # 活跃流式源：source -> priority，打断/暂停时统一取消（关闭 HTTP 拉取）
        self._streams_lock = Lock()
        self._active_streams = {}

        # 计数锁与暂停标志
        self.count_lock = Lock()
        self.paused = False
        self.pause_lock = Lock()

        # 合成互斥锁（保证任意时刻只有一个合成在进行，配合任务串行）
        self.synth_lock = threading.Lock()
        # 任务入队锁：串行化「创建任务 + 抢占判断 + 入队」，避免并发抢占重复触发
        self._assign_lock = threading.Lock()
        # 打断标志：置位后丢弃后续待合成/待入队内容
        self._interrupt_flag = threading.Event()

        # ===== 语音优先级抢占 =====
        # 正在播放片段的优先级 / 正在合成任务的优先级（0=空闲）
        self.priority_lock = threading.Lock()
        self._playing_priority = 0
        self._synth_priority = 0

        # 任务调度线程：按来源分组串行处理 TTS 任务
        self.task_thread = Thread(target=self._task_worker, daemon=True)
        self.task_thread.start()

        # 启动播放线程与子模块后台线程
        self.play_thread = Thread(target=self._play_worker, daemon=True)
        self.play_thread.start()
        self.subtitle.start()
        self.interrupt.start()

    @staticmethod
    def _priority_of(source) -> int:
        """按 source 映射语音优先级：weather/news/礼物感谢(3) > 其它 toolbox(2) > llm/other(1)

        仅严格更高优先级才触发抢占；同优先级不抢占。
        """
        s = str(source or "")
        if s in ("toolbox_weather", "toolbox_news", "toolbox_danmaku_gift"):
            return 3
        if s.startswith("toolbox"):
            return 2
        return 1

    def is_busy(self) -> bool:
        """检测当前是否有 TTS 说话任务（弹幕消费调度轮询用）。

        任一为真即忙：
        - 任务队列非空 / 未完成句子缓冲非空；
        - 活跃流式源非空；
        - 播放队列非空；
        - 正在播放或正在合成（优先级 > 0）。
        """
        try:
            if not self.llmData.AnswerList.empty():
                return True
            if not self.ttsData.task_queue.empty():
                return True
            with self.ttsData.task_lock:
                if self.ttsData.pending_tasks:
                    return True
            with self._streams_lock:
                if self._active_streams:
                    return True
            if not self.play_queue.empty():
                return True
            with self.priority_lock:
                if self._playing_priority > 0 or self._synth_priority > 0:
                    return True
            return False
        except Exception:
            self.log.exception("TTS is_busy 检测异常")
            return False

    def _is_paused(self):
        """线程安全地读取暂停状态"""
        with self.pause_lock:
            return self.paused

    def pause(self):
        """暂停：停止播放并清空队列，阻止新任务"""
        with self.pause_lock:
            if self.paused:
                return
            self.paused = True
            self.log.info("TTS 暂停")
            # 代际 +1：所有旧任务作废
            with self.ttsData.task_lock:
                self.ttsData.generation += 1
            self.player.stop()
            self._cancel_active_streams()
            self._clear_play_queue()
            self.subtitle.clear()
            with self.pending_lock:
                self.pending_segments.clear()
            self._clear_task_queue()
            self._interrupt_flag.set()
            with self.priority_lock:
                self._playing_priority = 0
                self._synth_priority = 0

    def resume(self):
        """恢复播放"""
        with self.pause_lock:
            if not self.paused:
                return
            self.paused = False
            self._interrupt_flag.clear()
            self.log.info("TTS 恢复")

    def stop_all(self):
        """彻底清除：停止播放、清空所有队列并删除音频文件"""
        self.log.info("TTS 彻底清除")
        with self.pause_lock:
            self.player.stop()
            time.sleep(0.1)
            self._cancel_active_streams()
            self._clear_play_queue()
            self.subtitle.clear()
            while not self.llmData.AnswerList.empty():
                try:
                    self.llmData.AnswerList.get_nowait()
                except Exception:
                    pass
            while not self.llmData.QuestionList.empty():
                try:
                    self.llmData.QuestionList.get_nowait()
                except Exception:
                    pass
            with self.pending_lock:
                self.pending_segments.clear()
            with self.count_lock:
                self.ttsData.SayCount = 0
            # 删除输出目录下所有语音文件
            output_dir = self.config.output_dir
            if os.path.exists(output_dir):
                for f in os.listdir(output_dir):
                    if f.endswith((".wav", ".mp3")):
                        try:
                            os.remove(os.path.join(output_dir, f))
                        except Exception:
                            pass
            self.paused = True
            self.ttsData.is_tts_ready = True
            with self.priority_lock:
                self._playing_priority = 0
                self._synth_priority = 0
        self.log.info("TTS 彻底清除完成")

    def _remove_file(self, file_path):
        """删除音频文件（忽略异常）"""
        try:
            if isinstance(file_path, str) and os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

    def _cancel_active_streams(self):
        """取消所有活跃流式源（关闭 HTTP 拉取），打断/暂停/抢占时调用"""
        with self._streams_lock:
            streams = list(self._active_streams.keys())
            self._active_streams.clear()
        for s in streams:
            try:
                s.cancel()
            except Exception:
                pass

    def _active_max_priority(self) -> int:
        """当前活跃流中的最大优先级（用于抢占判断）"""
        with self._streams_lock:
            return max([int(p or 0) for p in self._active_streams.values()], default=0)

    def _clear_play_queue(self):
        """清空播放队列并取消其中的流式源"""
        while not self.play_queue.empty():
            try:
                source, _, _, _ = self.play_queue.get_nowait()
                if hasattr(source, "cancel"):
                    source.cancel()
            except Exception:
                pass

    def _play_worker(self):
        """顺序播放线程：逐个消费流式源，期间响应暂停与打断"""
        while True:
            if self._is_paused():
                time.sleep(0.1)
                continue
            try:
                source, subtitle_json, _, priority = self.play_queue.get(timeout=0.5)
            except queue.Empty:
                # 完全空闲时关闭常驻 mpv 进程，避免进程挂着占资源
                if not self.is_busy():
                    self.player.shutdown()
                continue

            if self._is_paused():
                source.cancel()
                continue

            # 记录正在播放片段的优先级（供高优先级抢占判断）
            with self.priority_lock:
                self._playing_priority = int(priority or 0)

            # 仅在完整回复首次出现时推送浏览器字幕
            full_text = subtitle_json.get("text", "") if subtitle_json else ""
            if full_text:
                GetSubtitleBridge().send_tts(full_text)

            # 歌词字幕同步（预合成音频如即兴哼唱片段，随播放开始逐句刷新）
            lyric_syncer = None
            lyric_info = getattr(source, "lyric", None)
            if lyric_info:
                try:
                    from func.meowsinger.subtitle.lyric_syncer import MeowLyricSyncer
                    lyric_syncer = MeowLyricSyncer()
                    lyric_syncer.start(
                        lyric_info.get("lines") or [],
                        start_idx=lyric_info.get("start_idx", 0),
                        end_idx=lyric_info.get("end_idx"),
                    )
                except Exception:
                    self.log.exception("启动歌词字幕同步失败")
                    lyric_syncer = None

            try:
                self._play_stream_source(source)
            finally:
                if lyric_syncer:
                    lyric_syncer.stop()
                with self.priority_lock:
                    self._playing_priority = 0
                source.cancel()

            # 段间随机停顿（播放层）：每播完一段后停顿 pause_min~max 秒，可被暂停/打断/抢占中断
            self._segment_pause(source)

    def _segment_pause(self, source=None):
        """段间随机停顿：不按标点，每段播完后停顿 0.5~1s（配置 pause_min/max_ms）。

        - 仅当 pause_enabled 开启；
        - pause_sources 非空时仅对指定来源停顿（空=所有来源）；
        - 每 30ms 检查暂停与代际（打断/抢占/停止都会 generation+1），可立即中断。
        """
        try:
            cfg = self.config
            if not getattr(cfg, "pause_enabled", False):
                return
            if cfg.pause_sources:
                src_name = getattr(source, "source", "") if source else ""
                if src_name not in cfg.pause_sources:
                    return
            if self._is_paused():
                return
            duration = random.uniform(cfg.pause_min_ms, cfg.pause_max_ms) / 1000.0
            gen = self.ttsData.generation
            end = time.time() + duration
            while time.time() < end:
                if self._is_paused():
                    return
                if gen != self.ttsData.generation:
                    return
                time.sleep(0.03)
        except Exception as e:
            self.log.debug(f"段间停顿异常: {e}")

    def _play_stream_source(self, source: StreamSource):
        """阻塞播放一个流式源：边收边播直到结束/打断"""
        samplerate = int(source.sample_rate or self.config.sample_rate or 32000)
        channels = source.channels or 1

        if source.cancelled or self._is_paused():
            self._drain_stream(source)
            return

        if not self.player.open_stream(samplerate, channels):
            # 播放器不可用：丢弃该流剩余数据
            self._drain_stream(source)
            return

        try:
            while True:
                data, finished = source.pop(timeout=0.5)
                if finished:
                    break
                if data:
                    if not self.player.write(data, self.config.volume):
                        break
        finally:
            self.player.close_stream()

    def _drain_stream(self, source: StreamSource):
        """丢弃流式源剩余数据（播放器不可用时）"""
        while True:
            _, finished = source.pop(timeout=0.1)
            if finished:
                break

    def _interrupt_playback(self):
        """执行打断：停止播放并清空所有任务（含排队中，信息已滞后）"""
        # 代际 +1：所有旧任务作废
        with self.ttsData.task_lock:
            self.ttsData.generation += 1
        self.player.stop()
        self._cancel_active_streams()
        self._clear_play_queue()
        with self.pending_lock:
            self.pending_segments.clear()
        while not self.llmData.AnswerList.empty():
            try:
                self.llmData.AnswerList.get_nowait()
            except Exception:
                pass
        self._clear_task_queue()
        self._interrupt_flag.set()
        self.subtitle.clear()
        with self.priority_lock:
            self._playing_priority = 0
            self._synth_priority = 0

    def _resume_after_interrupt(self):
        """用户说话结束后恢复 TTS：解除打断标志，让 check_tts 重新取消息"""
        self._interrupt_flag.clear()

    def _add_segment(self, traceid, seg_index, source, reply_json, is_end=False, priority=0):
        """将分段放入顺序缓冲，按序进入播放队列"""
        with self.pending_lock:
            if traceid not in self.pending_segments:
                self.pending_segments[traceid] = {
                    "next": 0,
                    "buffer": {},
                    "lock": Lock(),
                    "traceid": traceid,
                }
            tracker = self.pending_segments[traceid]

        with tracker["lock"]:
            tracker["buffer"][seg_index] = (source, reply_json, is_end, priority)
            self._flush_buffer(tracker)

    def _flush_buffer(self, tracker):
        """按 seg_index 顺序刷新缓冲到播放与字幕队列"""
        while tracker["next"] in tracker["buffer"]:
            idx = tracker["next"]
            source, reply_json, is_end, priority = tracker["buffer"].pop(idx)
            self.subtitle.put(reply_json)
            if source is not None:
                self.log.info(f"[{tracker['traceid']}] 播放片段 {idx + 1}")
                self.play_queue.put((source, reply_json, is_end, priority))
            tracker["next"] += 1

            if is_end:
                with self.pending_lock:
                    if tracker["traceid"] in self.pending_segments:
                        del self.pending_segments[tracker["traceid"]]
                return

    def play_audio(self, audio, sr, source="meowsongs", traceid=None,
                   lyric_lines=None, lyric_start_idx=0, lyric_end_idx=None):
        """播放预合成音频（如哼唱片段），走 TTS 播放队列，可打断、后续回复排队"""
        try:
            import numpy as np
            audio = np.asarray(audio)
            channels = 1 if audio.ndim == 1 else audio.shape[1]
            sr = int(sr or self.config.sample_rate or 32000)
            if audio.dtype != np.int16:
                audio = np.clip(audio, -1.0, 1.0)
                audio = (audio * 32767.0).astype(np.int16)
            raw = audio.tobytes()

            traceid = traceid or str(uuid.uuid4())
            source = StreamSource(None, None, traceid, 0,
                                  sample_rate=sr, channels=channels,
                                  source=source)
            source.push(raw)
            source.finish()

            priority = self._priority_of("meowsongs")
            if lyric_lines:
                source.lyric = {
                    "lines": lyric_lines,
                    "start_idx": lyric_start_idx,
                    "end_idx": lyric_end_idx,
                }
            reply_json = {"traceid": traceid, "chatStatus": "end", "text": ""}
            self.play_queue.put((source, reply_json, True, priority))
        except Exception:
            self.log.exception("【play_audio】播放预合成音频异常：")

    def tts_say(self, text):
        """直接合成并播放一段语音（复读/欢迎语）"""
        try:
            traceid = str(uuid.uuid4())
            json = {"voiceType": "other", "traceid": traceid, "chatStatus": "end", "text": text, "lanuage": ""}
            self.tts_say_do(json, generation=self.ttsData.generation)
        except Exception:
            self.log.exception("【tts_say】发生异常：")

    def tts_say_do(self, json, generation=None):
        """核心合成流程：文本清洗→选角色→合成→入队播放（串行加锁，代际不匹配时丢弃）"""
        if self._is_paused():
            self.log.info("TTS 已暂停，取消合成")
            return
        if self._interrupt_flag.is_set():
            return

        # 合成互斥：串行合成，避免并发导致播放顺序错乱
        with self.synth_lock:
            return self._tts_say_do_locked(json, generation)

    def _tts_say_do_locked(self, json, generation=None):
        """tts_say_do 的加锁主体（调用方已持有 synth_lock）"""
        seg_index = json.get("seg_index", 0)
        is_segmented = "seg_index" in json

        with self.count_lock:
            self.ttsData.SayCount += 1

        text = json.get("text", "")
        reply_text = text
        traceid = json.get("traceid", "")
        chat_status = json.get("chatStatus", "end")
        priority = self._priority_of(json.get("source", "other"))

        # 空文本 + end 作为结束标记
        if text == "" and chat_status == "end":
            reply_json = {"traceid": traceid, "chatStatus": chat_status, "text": ""}
            if is_segmented:
                # 分段场景：空结束段仅用于清理顺序缓冲，不入播放队列
                self._add_segment(traceid, seg_index, None, reply_json, is_end=True, priority=priority)
            else:
                self.subtitle.put(reply_json)
                self.log.info(reply_json)
            return

        # 过滤影响合成的特殊字符
        text = re.sub(r"(《|》|（|）)", "", text)

        # 获取当前情绪与强度（用于选择参考音频 + 采样参数）
        emotion, intensity = self._resolve_emotion()

        # 获取当前角色卡绑定的参考音频配置（按情绪选择）
        ref_audio = self._resolve_ref_audio(emotion)

        # 流式合成：创建流式源（生成器 + 取消函数）
        generator, cancel_func = self.sovits.get_sovits_stream(
            text, ref_audio, emotion=emotion, intensity=intensity
        )
        if generator is None:
            return

        source = StreamSource(generator, cancel_func, traceid, seg_index,
                              source=json.get("source", "other"))

        # 入队前再次检查：代际不匹配（已打断/暂停）或暂停状态，则丢弃该流
        if (generation is not None and generation != self.ttsData.generation) or self._is_paused():
            source.cancel()
            return

        # 注册活跃流（供打断统一取消 + 抢占优先级判断）
        with self._streams_lock:
            self._active_streams[source] = priority

        reply_json = {"traceid": traceid, "chatStatus": chat_status, "text": reply_text}

        if is_segmented:
            # 分段任务交给顺序缓冲，保证按序播放
            self._add_segment(traceid, seg_index, source, reply_json,
                              is_end=(chat_status == "end"), priority=priority)
        else:
            # 非分段任务直接入队
            is_last = (chat_status == "end")
            self.subtitle.put(reply_json)
            self.play_queue.put((source, reply_json, is_last, priority))

        # 同步拉取字节填充缓冲：调用方持有 synth_lock，保证同一时刻只有一个流式请求，
        # 播放线程并行消费 source.buffer，实现"边合成边播放"
        self._pump_stream(source, generation)

    def _pump_stream(self, source: StreamSource, generation=None):
        """同步拉取流式字节填充到 source.buffer（调用方持有 synth_lock，保证串行）"""
        try:
            for chunk in source.generator:
                if source.cancelled:
                    break
                if generation is not None and generation != self.ttsData.generation:
                    source.cancel()
                    break
                if self._is_paused():
                    source.cancel()
                    break
                if chunk:
                    source.push(chunk)
        except Exception as e:
            self.log.debug(f"[{source.traceid}] 流式拉取异常: {e}")
        finally:
            source.finish()
            with self._streams_lock:
                self._active_streams.pop(source, None)

    def _resolve_emotion(self):
        """读取当前情绪与强度（逻辑委托 func.tts.emotion.resolve_emotion）"""
        return resolve_emotion()

    def _resolve_ref_audio(self, emotion: str = "neutral") -> dict:
        """按情绪选择参考音频（逻辑委托 func.tts.emotion.resolve_ref_audio）"""
        try:
            ref = self.system_prompt.get_ref_audio() or {}
        except Exception:
            self.log.exception("获取参考音频配置失败")
            return {}
        if not ref:
            return {}
        return resolve_ref_audio(emotion, ref, getattr(self.config, "emotion_audio", {}))

    def check_tts(self):
        """定时轮询回答队列，将合成请求按来源归组到任务队列"""
        if self._is_paused():
            return
        # 打断状态中：消息保留在队列，等用户说话结束后恢复（_resume_after_interrupt 解除标志）
        if self._interrupt_flag.is_set():
            return
        if not self.llmData.AnswerList.empty():
            json = self.llmData.AnswerList.get()
            self._assign_to_task(json)

    # ==================== 任务队列（按来源分组串行） ====================
    def _assign_to_task(self, json: dict):
        """把一条合成请求立即入队（边收边发：收到小句即合成，不等整句 end）。

        - 每个非空小句独立成一个任务，收到即入队；
        - 空文本 + end 是结束标记，同样入队（仅用于清理顺序缓冲，不入播放队列）；
        - 同一 traceid 的小句仍由 _add_segment 按 seg_index 保证字幕/播放有序。
        """
        traceid = json.get("traceid", "")
        source = json.get("source", "other")
        text = (json.get("text") or "").strip()
        is_end = (json.get("chatStatus") == "end")

        # 空文本且非 end：无效请求，忽略
        if not text and not is_end:
            return

        with self._assign_lock:
            with self.ttsData.task_lock:
                self.ttsData.task_counter += 1
                task = {
                    "task_id": self.ttsData.task_counter,
                    "traceid": traceid,
                    "source": source,
                    "segments": [json],
                    "generation": self.ttsData.generation,
                    "priority": self._priority_of(source),
                }
            self._maybe_preempt(task)
            self.ttsData.task_queue.put(task)

    def _maybe_preempt(self, new_task: dict):
        """高优先级抢占：新任务优先级严格高于「正在播放 + 正在合成」时，掐断低优先级内容。

        - 停止当前播放、清空播放队列与任务队列、代际 +1 丢弃正在合成的旧任务；
        - 同优先级不抢占（保持原有 FIFO）。
        """
        new_pri = int(new_task.get("priority", 0) or 0)
        with self.priority_lock:
            current_max = max(self._playing_priority, self._synth_priority)
        # 纳入正在拉取的活跃流优先级（流式后 pump 在后台线程，需单独统计）
        current_max = max(current_max, self._active_max_priority())
        if new_pri <= current_max:
            return
        # 完全空闲（无播放、无合成）时无需抢占，也避免多余的 player.stop()
        if current_max == 0:
            return

        self.log.info(
            f"[TTS] 高优先级语音抢占：source={new_task.get('source')} pri={new_pri} > 当前={current_max}"
        )
        # 代际 +1：所有旧任务（含正在合成、排队）作废
        with self.ttsData.task_lock:
            self.ttsData.generation += 1
            new_task["generation"] = self.ttsData.generation
        self.player.stop()
        self._cancel_active_streams()
        self._clear_play_queue()
        self._clear_task_queue()
        with self.pending_lock:
            self.pending_segments.clear()
        # 抢占后立即重置优先级，避免残留导致后续同优先级任务连锁抢占
        with self.priority_lock:
            self._playing_priority = 0
            self._synth_priority = 0

    def _task_worker(self):
        """串行处理任务队列：一个任务（一句话）合并为单个流式请求，流拉完才处理下一个任务"""
        while True:
            task = self.ttsData.task_queue.get()
            gen = task.get("generation", 0)
            # 任务代际不匹配（已打断/暂停）→ 丢弃
            if gen != self.ttsData.generation:
                continue
            if self._is_paused():
                continue
            # 记录正在合成任务的优先级（供高优先级抢占判断）
            with self.priority_lock:
                self._synth_priority = int(task.get("priority", 0) or 0)
            try:
                self._synth_task(task, gen)
            finally:
                with self.priority_lock:
                    self._synth_priority = 0

    def _synth_task(self, task: dict, gen):
        """逐个小句单独合成（小句单发，字幕按小句分段）"""
        segments = task.get("segments", [])
        for seg in segments:
            seg_json = {
                "voiceType": "chat",
                "source": task.get("source", "llm"),
                "traceid": task.get("traceid", ""),
                "chatStatus": seg.get("chatStatus", ""),
                "text": seg.get("text", ""),
                "language": "AutoChange",
                "seg_index": seg.get("seg_index", 0),
            }
            self.tts_say_do(seg_json, gen)

    def _clear_task_queue(self):
        """清空任务队列与未完成句子缓冲（暂停/打断时调用）"""
        while not self.ttsData.task_queue.empty():
            try:
                self.ttsData.task_queue.get_nowait()
            except Exception:
                pass
        with self.ttsData.task_lock:
            self.ttsData.pending_tasks.clear()

    def http_chatreply(self):
        """返回聊天回复 JSON（供前端轮询）"""
        if self.ttsData.ReplyTextList.empty():
            return "({})"
        item = self.ttsData.ReplyTextList.get()
        payload = {
            "traceid": item.get("traceid", ""),
            "chatStatus": item.get("chatStatus", ""),
            "status": "成功",
            "content": item.get("text", "").replace("\r", " ").replace("\n", "<br/>"),
        }
        return "(" + json.dumps(payload, ensure_ascii=False) + ")"
