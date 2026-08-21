# ================== tts_core.py ==================
# TTS 核心调度：合成 + 顺序播放，组合 config/interrupt/subtitle/action 子模块
import json
import os
import queue
import re
import threading
import time
import uuid
from threading import Lock, Thread
from concurrent.futures import ThreadPoolExecutor

from func.log.default_log import DefaultLog
from func.toolbox.vtuber.emote_oper import EmoteOper
from func.tts.config import TTSConfig
from func.tts.gpt_sovits import GptSovits
from func.tts.player import AudioPlayer
from func.tts.subtitle import SubtitleWorker
from func.tts.interrupt import InterruptManager
from func.toolbox.obs.browser_subtitle_server import get_subtitle_server
from func.tools.singleton_mode import singleton
from func.tts.state import TTsState
from func.llm.state import LLmState
from func.config.app_config import AppConfig
from func.pipeline.system_prompt import SystemPromptBridge
from func.pipeline.sensevoice_tts import SenseVoiceTtsBridge


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

        # 引擎、播放器、表情
        self.sovits = GptSovits()
        self.player = AudioPlayer()
        self.emoteOper = EmoteOper()

        # 字幕独立线程
        self.subtitle = SubtitleWorker(
            self.ttsData,
            get_subtitle_server(),
            is_paused=self._is_paused,
        )

        # 打断管理器（按键/pipeline 可配置）
        self.interrupt = InterruptManager(
            self.config,
            on_interrupt=self._interrupt_playback,
            sensevoice_tts=self.sensevoice_tts,
            is_paused=self._is_paused,
        )

        # 播放队列与分段顺序控制
        self.play_queue = queue.Queue()
        self.pending_lock = Lock()
        self.pending_segments = {}

        # 计数锁与暂停标志
        self.count_lock = Lock()
        self.paused = False
        self.pause_lock = Lock()

        # 合成互斥锁（保证任意时刻只有一个合成在进行，配合任务串行）
        self.synth_lock = threading.Lock()
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
        """按 source 映射语音优先级：weather/news(3) > 其它 toolbox(2) > llm/other(1)

        仅严格更高优先级才触发抢占；同优先级不抢占。
        """
        s = str(source or "")
        if s in ("toolbox_weather", "toolbox_news"):
            return 3
        if s.startswith("toolbox"):
            return 2
        return 1

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

    def _clear_play_queue(self):
        """清空播放队列并删除对应音频文件"""
        while not self.play_queue.empty():
            try:
                file_path, _, _, _ = self.play_queue.get_nowait()
                self._remove_file(file_path)
            except Exception:
                pass

    def _play_worker(self):
        """顺序播放线程：逐个播放音频，期间响应暂停与打断"""
        while True:
            if self._is_paused():
                time.sleep(0.1)
                continue
            try:
                file_path, subtitle_json, _, priority = self.play_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self._is_paused():
                self._remove_file(file_path)
                continue

            # 记录正在播放片段的优先级（供高优先级抢占判断）
            with self.priority_lock:
                self._playing_priority = int(priority or 0)

            # 仅在完整回复首次出现时推送浏览器字幕
            full_text = subtitle_json.get("text", "") if subtitle_json else ""
            if full_text:
                self.subtitle.send_full_text(full_text)

            try:
                # 阻塞播放，播放完成后删除文件
                self.player.play_file(file_path, self.config.volume)
            finally:
                with self.priority_lock:
                    self._playing_priority = 0
            self._remove_file(file_path)

    def _interrupt_playback(self):
        """执行打断：停止播放并清空所有任务（含排队中，信息已滞后）"""
        # 代际 +1：所有旧任务作废
        with self.ttsData.task_lock:
            self.ttsData.generation += 1
        self.player.stop()
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

    def _add_segment(self, traceid, seg_index, file_path, reply_json, is_end=False, priority=0):
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
            tracker["buffer"][seg_index] = (file_path, reply_json, is_end, priority)
            self._flush_buffer(tracker)

    def _flush_buffer(self, tracker):
        """按 seg_index 顺序刷新缓冲到播放与字幕队列"""
        while tracker["next"] in tracker["buffer"]:
            idx = tracker["next"]
            file_path, reply_json, is_end, priority = tracker["buffer"].pop(idx)
            self.subtitle.put(reply_json)
            if file_path is not None:
                self.log.info(f"[{tracker['traceid']}] 播放片段 {idx + 1}")
                self.play_queue.put((file_path, reply_json, is_end, priority))
            tracker["next"] += 1

            if is_end:
                with self.pending_lock:
                    if tracker["traceid"] in self.pending_segments:
                        del self.pending_segments[tracker["traceid"]]
                return

    def tts_say(self, text):
        """直接合成并播放一段语音（复读/欢迎语）"""
        try:
            traceid = str(uuid.uuid4())
            json = {"voiceType": "other", "traceid": traceid, "chatStatus": "end", "text": text, "lanuage": ""}
            self.tts_say_do(json, generation=self.ttsData.generation)
        except Exception:
            self.log.exception("【tts_say】发生异常：")

    def tts_chat_say(self, json):
        """聊天分段合成入口（线程池调用）"""
        try:
            self.tts_say_do(json, generation=self.ttsData.generation)
        except Exception:
            self.log.exception("【tts_chat_say】发生异常：")

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
            filename = f"say{self.ttsData.SayCount}"

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

        # 识别表情并累计感情值
        emote_json = self.emoteOper.emote_content(text)
        self.log.info(f"[{traceid}]输出表情{emote_json}")
        emotion = "happy"
        if emote_json:
            emotion = emote_json[0]["content"]
        self.emoteOper.mood(emotion)

        # 过滤影响合成的特殊字符
        text = re.sub(r"(《|》|（|）)", "", text)

        # 获取当前角色卡绑定的参考音频配置
        ref_audio = self._resolve_ref_audio()

        # 合成语音
        status = self.sovits.get_sovits(filename, text, ref_audio)
        if status == 0:
            return

        # 合成完成后再次检查：代际不匹配（已打断/暂停）或暂停状态，则不把音频入队
        if (generation is not None and generation != self.ttsData.generation) or self._is_paused():
            self._remove_file(os.path.join(self.config.output_dir, f"{filename}.wav"))
            return

        # 异步输出表情
        emote_thread = Thread(target=self.emoteOper.emote_show, args=(emote_json,))
        emote_thread.start()

        reply_json = {"traceid": traceid, "chatStatus": chat_status, "text": reply_text}
        audio_file = os.path.join(self.config.output_dir, f"{filename}.wav")

        if is_segmented:
            # 分段任务交给顺序缓冲，保证按序播放
            self._add_segment(traceid, seg_index, audio_file, reply_json,
                              is_end=(chat_status == "end"), priority=priority)
        else:
            # 非分段任务直接入队
            is_last = (chat_status == "end")
            self.subtitle.put(reply_json)
            self.play_queue.put((audio_file, reply_json, is_last, priority))

    def _resolve_ref_audio(self) -> dict:
        """从 system_prompt 获取当前角色卡绑定的参考音频配置"""
        try:
            return self.system_prompt.get_ref_audio() or {}
        except Exception:
            self.log.exception("获取参考音频配置失败")
            return {}

    def check_tts(self):
        """定时轮询回答队列，将合成请求按来源归组到任务队列"""
        if self._is_paused():
            return
        if not self.llmData.AnswerList.empty():
            json = self.llmData.AnswerList.get()
            # 有新的合成请求进入，解除此前的打断标志，让新代际任务正常处理
            self._interrupt_flag.clear()
            self._assign_to_task(json)

    # ==================== 任务队列（按来源分组串行） ====================
    def _assign_to_task(self, json: dict):
        """把一条合成请求归入任务：按 traceid 归组（一句话一个任务）。

        - 同一 traceid 的所有分段 → 同一个任务（一句话不拆）；
        - 不同 traceid → 不同任务（不同话不混）；
        - 收到 chatStatus=end 时，该句话完整，打包任务按 end 到达顺序入队。
        - source 仅作归属标记，不作为分组键。
        """
        traceid = json.get("traceid", "")
        source = json.get("source", "other")
        is_end = (json.get("chatStatus") == "end")
        new_task = None
        with self.ttsData.task_lock:
            cur = self.ttsData.pending_tasks.get(traceid)
            if cur is None:
                # 新句子：建新任务，登记 traceid
                self.ttsData.task_counter += 1
                cur = {
                    "task_id": self.ttsData.task_counter,
                    "traceid": traceid,
                    "source": source,
                    "segments": [],
                    "generation": self.ttsData.generation,
                    "priority": self._priority_of(source),
                }
                self.ttsData.pending_tasks[traceid] = cur
            # 同 traceid：并入当前任务
            cur["segments"].append(json)
            if is_end:
                # 一句话完整：先从缓冲移除
                self.ttsData.pending_tasks.pop(traceid, None)
                new_task = cur

        # 锁外：抢占判断（内部会获取 task_lock，避免嵌套死锁）+ 入队
        if new_task is not None:
            self._maybe_preempt(new_task)
            self.ttsData.task_queue.put(new_task)

    def _maybe_preempt(self, new_task: dict):
        """高优先级抢占：新任务优先级严格高于「正在播放 + 正在合成」时，掐断低优先级内容。

        - 停止当前播放、清空播放队列与任务队列、代际 +1 丢弃正在合成的旧任务；
        - 同优先级不抢占（保持原有 FIFO）。
        """
        new_pri = int(new_task.get("priority", 0) or 0)
        with self.priority_lock:
            current_max = max(self._playing_priority, self._synth_priority)
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
        self._clear_play_queue()
        self._clear_task_queue()
        with self.pending_lock:
            self.pending_segments.clear()

    def _task_worker(self):
        """串行处理任务队列：一个任务的所有分段合成+播放完，才轮到下一个任务"""
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
                for seg in task.get("segments", []):
                    if gen != self.ttsData.generation or self._is_paused():
                        break
                    self.tts_say_do(seg, gen)
            finally:
                with self.priority_lock:
                    self._synth_priority = 0

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
