# ================== tts_core.py ==================
# TTS 核心调度：合成 + 顺序播放，组合 config/interrupt/subtitle/action 子模块
import os
import queue
import re
import threading
import time
import uuid
from threading import Lock, Thread
from concurrent.futures import ThreadPoolExecutor

from func.log.default_log import DefaultLog
from func.vtuber.emote_oper import EmoteOper
from func.tts.config import TTSConfig
from func.tts.gpt_sovits import GptSovits
from func.tts.player import AudioPlayer
from func.tts.subtitle import SubtitleWorker
from func.tts.interrupt import InterruptManager
from func.obs.obs_init import ObsInit
from func.obs.browser_subtitle_server import get_subtitle_server
from func.tools.singleton_mode import singleton
from func.gobal.data import TTsData, LLmData
from func.pipeline.system_prompt import SystemPromptBridge
from func.pipeline.sensevoice_tts import SenseVoiceTtsBridge


@singleton
class TTsCore:
    log = DefaultLog().getLogger()

    def __init__(self):
        # 数据实体与集中配置
        self.ttsData = TTsData()
        self.llmData = LLmData()
        self.config = TTSConfig()

        # 桥接依赖：角色提示词（未实现）与说话状态（打断）
        self.system_prompt = SystemPromptBridge()
        self.sensevoice_tts = SenseVoiceTtsBridge()

        # 引擎、播放器、OBS、表情、动作
        self.sovits = GptSovits()
        self.player = AudioPlayer()
        self.obs = ObsInit().get_ws()
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

        # 当前角色卡
        self.current_character = None

        # 合成线程池
        self.tts_chat_say_pool = ThreadPoolExecutor(
            max_workers=self.config.synth_workers,
            thread_name_prefix="tts_chat_say",
        )

        # 启动播放线程与子模块后台线程
        self.play_thread = Thread(target=self._play_worker, daemon=True)
        self.play_thread.start()
        self.subtitle.start()
        self.interrupt.start()

    def _is_paused(self):
        """线程安全地读取暂停状态"""
        with self.pause_lock:
            return self.paused

    def set_current_character(self, char_name: str):
        """设置当前激活的角色卡名称"""
        self.current_character = char_name
        if hasattr(self.sovits, 'set_character'):
            self.sovits.set_character(char_name)

    def pause(self):
        """暂停：停止播放并清空队列，阻止新任务"""
        with self.pause_lock:
            if self.paused:
                return
            self.paused = True
            self.log.info("TTS 暂停")
            self.player.stop()
            self._clear_play_queue()
            self.subtitle.clear()
            with self.pending_lock:
                self.pending_segments.clear()

    def resume(self):
        """恢复播放"""
        with self.pause_lock:
            if not self.paused:
                return
            self.paused = False
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
            self.llmData.is_stream_out = False
            self.ttsData.is_tts_ready = True
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
                file_path, _, _ = self.play_queue.get_nowait()
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
                file_path, subtitle_json, _ = self.play_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self._is_paused():
                self._remove_file(file_path)
                continue

            # 仅在完整回复首次出现时推送浏览器字幕
            full_text = subtitle_json.get("text", "") if subtitle_json else ""
            if full_text:
                self.subtitle.send_full_text(full_text)

            # 阻塞播放，播放完成后删除文件
            self.player.play_file(file_path, self.config.volume)
            self._remove_file(file_path)

    def _interrupt_playback(self):
        """执行打断：停止播放并丢弃本轮未播出的分段"""
        self.player.stop()
        self._clear_play_queue()
        with self.pending_lock:
            self.pending_segments.clear()
        while not self.llmData.AnswerList.empty():
            try:
                self.llmData.AnswerList.get_nowait()
            except Exception:
                pass
        self.subtitle.clear()

    def _add_segment(self, traceid, seg_index, total, file_path, reply_json, is_end=False):
        """将分段放入顺序缓冲，按序进入播放队列"""
        with self.pending_lock:
            if traceid not in self.pending_segments:
                self.pending_segments[traceid] = {
                    "next": 0,
                    "total": total,
                    "buffer": {},
                    "lock": Lock(),
                    "traceid": traceid,
                }
            tracker = self.pending_segments[traceid]

        with tracker["lock"]:
            tracker["buffer"][seg_index] = (file_path, reply_json, is_end)
            self._flush_buffer(tracker)

    def _flush_buffer(self, tracker):
        """按 seg_index 顺序刷新缓冲到播放与字幕队列"""
        while tracker["next"] in tracker["buffer"]:
            idx = tracker["next"]
            file_path, reply_json, is_end = tracker["buffer"].pop(idx)
            self.log.info(f"[{tracker['traceid']}] 播放片段 {idx + 1}/{tracker['total']}")
            self.subtitle.put(reply_json)
            self.play_queue.put((file_path, reply_json, is_end))
            tracker["next"] += 1

            # total 未知且当前段为结束段时清理
            if tracker["total"] == -1 and is_end:
                with self.pending_lock:
                    if tracker["traceid"] in self.pending_segments:
                        del self.pending_segments[tracker["traceid"]]
                return

        # total 已知且所有分段已入队时清理
        if tracker["total"] != -1 and tracker["next"] >= tracker["total"]:
            with self.pending_lock:
                if tracker["traceid"] in self.pending_segments:
                    del self.pending_segments[tracker["traceid"]]

    def tts_say(self, text):
        """直接合成并播放一段语音（复读/欢迎语）"""
        try:
            traceid = str(uuid.uuid4())
            json = {"voiceType": "other", "traceid": traceid, "chatStatus": "end", "question": "", "text": text, "lanuage": ""}
            self.tts_say_do(json)
        except Exception:
            self.log.exception("【tts_say】发生异常：")

    def tts_chat_say(self, json):
        """聊天分段合成入口（线程池调用）"""
        try:
            self.tts_say_do(json)
        except Exception:
            self.log.exception("【tts_chat_say】发生异常：")

    def tts_say_do(self, json):
        """核心合成流程：文本清洗→选角色→合成→入队播放"""
        if self._is_paused():
            self.log.info("TTS 已暂停，取消合成")
            return

        seg_index = json.get("seg_index", 0)
        total_segments = json.get("total_segments", 1)
        is_segmented = "seg_index" in json

        with self.count_lock:
            self.ttsData.SayCount += 1
            filename = f"say{self.ttsData.SayCount}"

        question = json.get("question", "")
        text = json.get("text", "")
        reply_text = text
        traceid = json.get("traceid", "")
        chat_status = json.get("chatStatus", "end")

        # 空文本 + end 作为结束标记
        if text == "" and chat_status == "end":
            reply_json = {"traceid": traceid, "chatStatus": chat_status, "text": ""}
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

        # 解析参考音频角色
        character = self._resolve_character()

        # 合成语音
        status = self.sovits.get_sovits(filename, text, character)
        if status == 0:
            return
        if question != "":
            self.obs.show_text("状态提示", f'{self.llmData.Ai_Name}语音合成"{question}"完成')

        # 异步输出表情
        emote_thread = Thread(target=self.emoteOper.emote_show, args=(emote_json,))
        emote_thread.start()

        reply_json = {"traceid": traceid, "chatStatus": chat_status, "text": reply_text}
        audio_file = os.path.join(self.config.output_dir, f"{filename}.wav")

        if is_segmented:
            # 分段任务交给顺序缓冲，保证按序播放
            self._add_segment(traceid, seg_index, total_segments, audio_file, reply_json, is_end=(chat_status == "end"))
        else:
            # 非分段任务直接入队
            is_last = (chat_status == "end")
            self.subtitle.put(reply_json)
            self.play_queue.put((audio_file, reply_json, is_last))

    def _resolve_character(self):
        """从角色提示词/当前角色卡解析参考音频角色名"""
        # 1. 从 system_prompt 获取角色提示词（未实现，先保留接口）
        prompt = ""
        try:
            prompt = self.system_prompt.get_system_prompt() or ""
        except Exception:
            pass
        character = self.sovits.resolve_character(prompt)
        if character:
            return character
        # 2. 使用当前角色卡
        if self.current_character:
            return self.current_character
        # 3. 随机角色
        character = self.sovits.get_random_character()
        if character:
            return character
        return None

    def check_tts(self):
        """定时轮询回答队列，提交语音合成任务"""
        if self._is_paused():
            return
        if not self.llmData.AnswerList.empty():
            json = self.llmData.AnswerList.get()
            traceid = json.get("traceid", "")
            text = json.get("text", "")
            self.log.info(f"[{traceid}]text:{text},SayCount:{self.ttsData.SayCount}")
            self.tts_chat_say_pool.submit(self.tts_chat_say, json)

    def http_chatreply(self):
        """返回聊天回复 JSON（供前端轮询）"""
        if self.ttsData.ReplyTextList.empty():
            return "({})"
        json_str = self.ttsData.ReplyTextList.get()
        text = json_str["text"]
        traceid = json_str["traceid"]
        chat_status = json_str["chatStatus"]
        content = text.replace("\"", "'").replace("\r", " ").replace("\n", "<br/>")
        return "({\"traceid\": \"" + traceid + "\",\"chatStatus\": \"" + chat_status + "\",\"status\": \"成功\",\"content\": \"" + content + "\"})"
