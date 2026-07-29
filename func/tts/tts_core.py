# ================== tts_core.py ==================
# tts语音合成
import uuid
import logging
import traceback
import re
import subprocess
import queue
import os
import threading
import time
import sys
import atexit
from threading import Lock
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

from func.log.default_log import DefaultLog
from func.vtuber.emote_oper import EmoteOper
from func.vtuber.action_oper import ActionOper
from func.tools.string_util import StringUtil
from func.translate.duckduckgo_translate import DuckduckgoTranslate
from func.tts.gtp_vists import GtpVists
from func.tts.bert_vits2 import BertVis2
from func.tts.edge_tts_vits import EdgeTTs
from func.tts.edge_tts_pro import EdgeTtsPro
from func.tts.player import MpvPlay
from func.obs.obs_init import ObsInit
from func.obs.browser_subtitle_server import get_subtitle_server
from func.tools.singleton_mode import singleton
from func.gobal.data import TTsData
from func.gobal.data import LLmData
from func.gobal.data import SingData
from func.config.default_config import defaultConfig

@singleton
class TTsCore:
    # 设置控制台日志
    log = DefaultLog().getLogger()

    mpvPlay = MpvPlay()  # 播放器
    emoteOper = EmoteOper()  # 表情
    actionOper = ActionOper()  # 动作
    duckduckgoTranslate = DuckduckgoTranslate()  # 翻译

    ttsData = TTsData()  # tts数据
    llmData = LLmData()  # llm数据
    singData = SingData()  # 唱歌数据
    # 选择语音
    select_vists = ttsData.select_vists
    if select_vists == "gpt-sovits":
        vists = GtpVists()
    elif select_vists == "bert-vists":
        vists = BertVis2()
    elif select_vists == "edge-tts":
        vists = EdgeTTs()
    elif select_vists == "edge-tts-pro":
        vists = EdgeTtsPro()
    else:
        vists = GtpVists()


    def __init__(self):
        self.proxy_process = None
        self._start_proxy()
        self.obs = ObsInit().get_ws()
        # 播放队列（文件路径）
        self.play_queue = queue.Queue()
        # 字幕队列（字幕JSON）
        self.subtitle_queue = queue.Queue()
        # 保护 SayCount 的锁（已有 ttsData.SayCount，但为了线程安全，可以加锁）
        self.count_lock = Lock()

        # 顺序控制结构
        self.pending_lock = Lock()
        self.pending_segments = {}   # traceid -> 状态字典

        # ====== 新增：暂停标志 ======
        self.paused = False
        self.pause_lock = Lock()
        # ====== 新增：防止重复生成“喵喵喵”的简单标志 ======
        self._meow_generating = False

        # 启动播放线程
        self.play_thread = Thread(target=self._play_worker, daemon=True)
        self.play_thread.start()
        # 启动字幕线程
        self.subtitle_thread = Thread(target=self._subtitle_worker, daemon=True)
        self.subtitle_thread.start()

        # 加载复读配置
        config = defaultConfig().get_config()
        speech_cfg = config.get('speech', {}).get('gpt-sovits', {})
        self.repeat_enabled = speech_cfg.get('repeat_enabled', False)
        self.repeat_timeout = speech_cfg.get('repeat_timeout', 2)
        self.subtitle_server = get_subtitle_server()
        self.current_full_subtitle = None
        self.current_character = None

    def _start_proxy(self):
        """启动 pproxy 代理服务"""
        # 读取代理配置，判断是否需要启动
        config = defaultConfig().get_config()
        proxy_addr = config.get("translate", {}).get("HttpProxies", None)
        if not proxy_addr:
            return  # 未配置代理，不启动

        # 解析代理地址，获取端口
        # 假设格式为 http://127.0.0.1:8080
        if not proxy_addr.startswith("http://"):
            return
        try:
            import urllib.parse
            parsed = urllib.parse.urlparse(proxy_addr)
            host = parsed.hostname
            port = parsed.port
            if host != "127.0.0.1" or not port:
                return
        except:
            return

        # 检查端口是否已被占用（避免重复启动）
        if self._is_port_in_use(port):
            print(f"代理端口 {port} 已被占用，假设已有代理运行")
            return

        # 启动 pproxy 子进程
        try:
            # 命令：runtime\python.exe -m pproxy -l http://127.0.0.1:8080
            # 如果需要通过现有 SOCKS5 转发，可以添加 -r 参数
            # 这里以最简单的纯 HTTP 代理为例
            python_exe = os.path.join(os.path.dirname(sys.executable), "python.exe")
            cmd = [python_exe, "-m", "pproxy", "-l", proxy_addr]
            self.proxy_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            print(f"代理服务已启动: {proxy_addr}")
            # 注册退出时关闭
            atexit.register(self._stop_proxy)
        except Exception as e:
            print(f"启动代理失败: {e}")

    def _is_port_in_use(self, port):
        """检查端口是否被占用"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return False
            except OSError:
                return True

    def _stop_proxy(self):
        """终止代理进程"""
        if self.proxy_process:
            try:
                self.proxy_process.terminate()
                self.proxy_process.wait(timeout=3)
                print("代理服务已停止")
            except:
                self.proxy_process.kill()
            self.proxy_process = None

    # ====== 加载角色卡 ======
    def set_current_character(self, char_name: str):
        """设置当前激活的角色卡名称，用于 TTS 选择参考音频"""
        self.current_character = char_name
        # 同时通知 vists 实例（如果是 GtpVists）
        if hasattr(self.vists, 'set_character'):
            self.vists.set_character(char_name)

    # ====== 暂停/恢复方法 ======
    def pause(self):
        with self.pause_lock:
            if self.paused:
                return
            self.paused = True
            self.log.info("TTS 暂停：停止所有语音合成与播放")

            # 清空播放队列和字幕队列
            while not self.play_queue.empty():
                try:
                    self.play_queue.get_nowait()
                except:
                    pass
            while not self.subtitle_queue.empty():
                try:
                    self.subtitle_queue.get_nowait()
                except:
                    pass

            # 清空待处理分段
            with self.pending_lock:
                self.pending_segments.clear()

    def stop_all(self):
        """彻底清除所有TTS播放和合成"""
        self.log.info("TTS 彻底清除：停止播放、清空队列、删除文件")
    
        with self.pause_lock:
            # 1. 立即停止当前播放
            self.mpvPlay.stop()
        
            # 等待一小段时间确保进程完全退出
            time.sleep(0.1)
        
            # 2. 清空播放队列（同时删除文件）
            while not self.play_queue.empty():
                try:
                    item = self.play_queue.get_nowait()
                    if len(item) >= 1:
                        file_path = item[0]
                        if isinstance(file_path, str) and os.path.exists(file_path):
                            try:
                                os.remove(file_path)
                            except:
                                pass
                except:
                    pass
        
            # 3. 清空字幕队列
            while not self.subtitle_queue.empty():
                try:
                    self.subtitle_queue.get_nowait()
                except:
                    pass
        
            # 4. 清空LLM回复队列（阻止新的TTS任务）
            while not self.llmData.AnswerList.empty():
                try:
                    self.llmData.AnswerList.get_nowait()
                except:
                    pass
        
            # 5. 清空问题队列
            while not self.llmData.QuestionList.empty():
                try:
                    self.llmData.QuestionList.get_nowait()
                except:
                    pass
        
            # 6. 清空待处理分段
            with self.pending_lock:
                self.pending_segments.clear()
        
            # 7. 重置TTS计数
            with self.count_lock:
                self.ttsData.SayCount = 0
        
            # 8. 删除output目录所有mp3
            try:
                output_dir = "./output"
                if os.path.exists(output_dir):
                    for file in os.listdir(output_dir):
                        if file.endswith(".mp3"):
                            try:
                                os.remove(os.path.join(output_dir, file))
                            except:
                                pass
            except:
                pass
        
            # 9. 设置暂停标志阻止新任务
            self.paused = True
        
            # 10. 重置流式输出状态
            self.llmData.is_stream_out = False
            self.ttsData.is_tts_ready = True
        
            self.log.info("TTS 彻底清除完成")
        
    def resume_from_stop(self):
        """从彻底清除状态恢复"""
        with self.pause_lock:
            self.paused = False
            self.log.info("TTS 从彻底清除状态恢复")

    def resume(self):
        with self.pause_lock:
            if not self.paused:
                return
            self.paused = False
            self.log.info("TTS 恢复")

    # ====== 生成“喵喵喵”语音（在播放线程超时时调用）======
    def _generate_meow(self):
        if self._meow_generating:
            return  # 避免短时间内重复生成
        self._meow_generating = True
        try:
            self.log.info("生成“喵喵喵”语音")
            # 直接调用 tts_say，但需要确保不会在 paused 状态下生成
            # 这里我们绕过暂停检查，因为超时发生时应播放喵喵喵
            # 但为了安全，临时恢复 paused 状态？
            with self.pause_lock:
                was_paused = self.paused
                self.paused = False  # 临时允许合成
            try:
                self.tts_say("喵喵喵")
            finally:
                with self.pause_lock:
                    self.paused = was_paused
        finally:
            self._meow_generating = False

    def _send_subtitle_to_browser(self, text: str):
        if not hasattr(self, 'subtitle_server') or self.subtitle_server is None:
            return
        try:
            self.subtitle_server.send_subtitle(text)
        except Exception as e:
            self.log.error(f"发送字幕失败: {e}")

    def _play_worker(self):
        """顺序播放音频文件的线程，等待每个文件播放完成后再播放下一个
           字幕逻辑：只在每个完整回复的第一个片段播放时，发送完整回复文本
           后续片段不再发送字幕，保持当前显示直到下一个回复开始
        """
        while True:
            # 检查暂停标志
            with self.pause_lock:
                if self.paused:
                    time.sleep(0.1)
                    continue

            # 获取下一个播放任务
            try:
                file_path, subtitle_json, is_last = self.play_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # 播放前再次检查暂停（防止在等待过程中暂停）
            with self.pause_lock:
                if self.paused:
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except:
                        pass
                    continue

            # ========== 字幕发送逻辑 ==========
            # 获取当前回复的完整文本
            full_text = subtitle_json.get("text", "") if subtitle_json else ""
        
            # 如果是新的完整回复（文本不同），则发送完整字幕并记录
            # 注意：空字符串不发送，避免清空已有字幕（除非需要清空）
            if full_text and full_text != self.current_full_subtitle:
                self._send_subtitle_to_browser(full_text)
                self.current_full_subtitle = full_text
                self.log.info(f"发送完整回复字幕: {full_text[:10]}{'...' if len(full_text) > 10 else ''}")
            # ==================================

            # 启动播放
            try:
                self.mpvPlay.mpv_play("mpv.exe", file_path, 100, "0")
            except Exception as e:
                self.log.exception(f"播放启动失败: {file_path}")
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except:
                    pass
                continue

            # 等待播放结束，或被打断
            while True:
                with self.pause_lock:
                    if self.paused:
                        # 被打断，停止播放并删除文件
                        self.log.debug(f"播放被打断，停止播放: {file_path}")
                        self.mpvPlay.stop()
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                        except:
                            pass
                        break

                # 检查进程状态
                if self.mpvPlay.current_process is None:
                    # 没有播放进程
                    break

                ret = self.mpvPlay.current_process.poll()
                if ret is not None:
                    # 进程已自然退出，播放完成
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except:
                        pass
                    break

                # 等待100ms再检查
                time.sleep(0.1)

    def _subtitle_worker(self):
        """顺序处理字幕的线程"""
        while True:
            reply_json = self.subtitle_queue.get()
            # 暂停时不处理字幕（但字幕队列已被清空，此处不会阻塞）
            with self.pause_lock:
                if self.paused:
                    continue
            self.ttsData.ReplyTextList.put(reply_json)
            self.log.info(reply_json)

    def _add_segment(self, traceid, seg_index, total, file_path, reply_json, is_end=False):
        """将分段添加到顺序缓冲区，当轮到它时自动放入播放和字幕队列"""
        with self.pending_lock:
            if traceid not in self.pending_segments:
                self.pending_segments[traceid] = {
                    "next": 0,
                    "total": total,
                    "buffer": {},
                    "lock": Lock(),
                    "traceid": traceid
                }
            tracker = self.pending_segments[traceid]

        with tracker["lock"]:
            tracker["buffer"][seg_index] = (file_path, reply_json, is_end)
            self._flush_buffer(tracker)

    def _flush_buffer(self, tracker):
        while tracker["next"] in tracker["buffer"]:
            idx = tracker["next"]
            file_path, reply_json, is_end = tracker["buffer"].pop(idx)
            self.log.info(f"[{tracker['traceid']}] 播放片段 {idx+1}/{tracker['total']}")
            self.subtitle_queue.put(reply_json)
            self.play_queue.put((file_path, reply_json, is_end))
            tracker["next"] += 1

            # 如果 total 未知且当前片段是 end，则立即清理
            if tracker["total"] == -1 and is_end:
                with self.pending_lock:
                    if tracker["traceid"] in self.pending_segments:
                        del self.pending_segments[tracker["traceid"]]
                return  # 已清理，退出

        # 如果 total 已知且所有分段已播放，则清理
        if tracker["total"] != -1 and tracker["next"] >= tracker["total"]:
            with self.pending_lock:
                if tracker["traceid"] in self.pending_segments:
                    del self.pending_segments[tracker["traceid"]]
    # 直接合成语音播放
    def tts_say(self,text):
        try:
            traceid = str(uuid.uuid4())
            json =  {"voiceType":"other","traceid":traceid,"chatStatus":"end","question":"","text":text,"lanuage":""}
            self.tts_say_do(json)
        except Exception as e:
            self.log.exception("【tts_say】发生了异常：")

    # 直接合成语音播放-聊天用
    def tts_chat_say(self,json):
        try:
            self.tts_say_do(json)
        except Exception as e:
            #self.is_tts_ready = True
            #self.llmData.is_stream_out = False
            self.log.exception(f"【tts_chat_say】发生了异常：")

    # 直接合成语音播放 {"question":question,"text":text,"lanuage":"ja"}
    def tts_say_do(self,json):

        # ====== 新增：暂停检查 ======
        with self.pause_lock:
            if self.paused:
                self.log.info("TTS 已停止，取消合成")
                return

        # 提取字段（包括可选的 seg_index/total_segments）
        seg_index = json.get("seg_index", 0)
        total_segments = json.get("total_segments", 1)
        is_segmented = "seg_index" in json   # 判断是否为分段任务

        # 安全递增 SayCount（使用锁）
        with self.count_lock:
            self.ttsData.SayCount += 1
            filename = f"say{self.ttsData.SayCount}"

        question = json["question"]
        text = json["text"]
        replyText = text
        lanuage = json["lanuage"]
        voiceType = json["voiceType"]
        traceid = json["traceid"]
        chatStatus = json["chatStatus"]

        # 退出标识
        if text == "" and chatStatus == "end":
            replyText_json = {"traceid": traceid, "chatStatus": chatStatus, "text": ""}
            self.subtitle_queue.put(replyText_json)  # 通过队列处理
            self.log.info(replyText_json)
            return

        # 识别表情
        jsonstr = self.emoteOper.emote_content(text)
        self.log.info(f"[{traceid}]输出表情{jsonstr}")
        emotion = "happy"
        if len(jsonstr) > 0:
            emotion = jsonstr[0]["content"]

        # 感情值增加
        moodNum = self.emoteOper.mood(emotion)

        # 触发翻译日语
        if lanuage == "AutoChange":
            self.log.info(f"[{traceid}]当前感情值:{moodNum}")
            if re.search(".*日(文|语).*", question) or re.search(".*日(文|语).*说.*", text):
                trans_json = self.duckduckgoTranslate.translate(text, "zh-Hans", "ja")
                if StringUtil.has_field(trans_json, "translated"):
                    text = trans_json["translated"]
            elif re.search(".*英(文|语).*", question) or re.search(
                    ".*英(文|语).*说.*", text
            ):
                trans_json = self.duckduckgoTranslate.translate(text, "zh-Hans", "en")
                if StringUtil.has_field(trans_json, "translated"):
                    text = trans_json["translated"]
            elif moodNum > 270 or emotion == "angry":
                trans_json = self.duckduckgoTranslate.translate(text, "zh-Hans", "ja")
                if StringUtil.has_field(trans_json, "translated"):
                    text = trans_json["translated"]

        # 合成语音
        pattern = "(《|》|（|）)"  # 过滤特殊字符，这些字符会影响语音合成
        text = re.sub(pattern, "", text)
        character_for_tts = getattr(self, 'current_character', None)
        if not character_for_tts:
            # 尝试从 vists 随机获取一个角色名
            if hasattr(self.vists, 'get_random_character'):
                character_for_tts = self.vists.get_random_character()
                if character_for_tts:
                    self.log.info("未设置当前角色卡，随机选择角色: %s", character_for_tts)
                else:
                    # 连随机都失败（无任何角色配置），则使用 "default" 并警告
                    character_for_tts = "default"
                    self.log.warning("未设置当前角色卡且无法随机选择，使用默认角色: %s", character_for_tts)
            else:
                character_for_tts = "default"
                self.log.warning("未设置当前角色卡，使用默认角色: %s", character_for_tts)

        status = self.vists.get_vists(filename, text, character_for_tts)
        if status == 0:
            return
        if question != "":
            self.obs.show_text("状态提示", f'{self.llmData.Ai_Name}语音合成"{question}"完成')


        # 判断同序列聊天语音合成时候，其他语音合成任务等待
        # if voiceType!="chat":
        #     while self.llmData.is_stream_out==True:
        #         time.sleep(1)

        # ============ 【线程锁】播放语音【时间会很长】 ==================
        #self.ttsData.say_lock.acquire()
        #self.ttsData.is_tts_ready = False
        #if chatStatus == "start":
            #self.llmData.is_stream_out = True

        # 输出表情
        emote_thread = Thread(target=self.emoteOper.emote_show, args=(jsonstr,))
        emote_thread.start()

        # 输出回复字幕
        replyText_json = {"traceid": traceid, "chatStatus": chatStatus, "text": replyText}
        self.subtitle_queue.put(replyText_json)

        # 循环摇摆动作
        yaotou_thread = Thread(target=self.actionOper.auto_swing)
        yaotou_thread.start()

        # 将音频文件路径放入播放队列（由播放线程顺序播放）
        # 构建音频路径（使用 os.path.join 更安全）
        audio_file = os.path.join(".", "output", f"{filename}.mp3")
        # 构建字幕 JSON
        replyText_json = {"traceid": traceid, "chatStatus": chatStatus, "text": replyText}

        if is_segmented:
            # 分段任务：交给顺序缓冲区，并标记是否为 end 段
            self._add_segment(traceid, seg_index, total_segments, audio_file, replyText_json, is_end=(chatStatus=="end"))
        else:
            # 非分段任务（如欢迎语）：直接入队
            self.subtitle_queue.put(replyText_json)
            is_last = (chatStatus == "end")   # 标记是否为最后一句
            self.play_queue.put((audio_file, replyText_json, is_last))
        # ========================= end =============================

        # 删除语音文件
        #subprocess.run(f"del /f .\output\{filename}.mp3 1>nul", shell=True)

    # 语音合成线程池
    tts_chat_say_pool = ThreadPoolExecutor(
        max_workers=2, 
        thread_name_prefix="tts_chat_say"
    )
    # 如果语音已经放完且队列中还有回复 则创建一个生成并播放TTS的线程
    def check_tts(self):
        # ====== 暂停时不处理新任务 ======
        with self.pause_lock:
            if self.paused:
                return
        if not self.llmData.AnswerList.empty():
            json = self.llmData.AnswerList.get()
            traceid = json["traceid"]
            text = json["text"]
            self.log.info(
                f"[{traceid}]text:{text},is_tts_ready:{self.ttsData.is_tts_ready},SayCount:{self.ttsData.SayCount},is_singing:{self.singData.is_singing}")
            # 合成语音
            self.tts_chat_say_pool.submit(self.tts_chat_say, json)


    # http接口：聊天回复弹框处理
    def http_chatreply(self):
        status = "失败"
        if not self.ttsData.ReplyTextList.empty():
            json_str = self.ttsData.ReplyTextList.get()
            text = json_str["text"]
            traceid = json_str["traceid"]
            chatStatus = json_str["chatStatus"]
            status = "成功"
        jsonStr = "({\"traceid\": \"" + traceid + "\",\"chatStatus\": \"" + chatStatus + "\",\"status\": \"" + status + "\",\"content\": \"" + text.replace(
            "\"", "'").replace("\r", " ").replace("\n", "<br/>") + "\"})"
        return jsonStr