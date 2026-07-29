# -*- coding: utf-8 -*-
import os
import glob
import random
import time
import uuid
import re
import json
from threading import Thread, Lock

from func.tools.singleton_mode import singleton
from func.log.default_log import DefaultLog
from func.gobal.data import SingData
from func.obs.obs_init import ObsInit
from func.tools.string_util import StringUtil
from func.tts.tts_core import TTsCore
from func.llm.llm_core import LLmData
from func.search.search_core import SearchCore
from func.image.image_core import ImageCore
from func.obs.obs_websocket import VideoControl
from func.obs.browser_subtitle_server import get_subtitle_server
from func.vtuber.emote_oper import EmoteOper
from func.vtuber.action_oper import ActionOper
from func.tts.player import MpvPlay

from .sing_config import (SERVER_URL, SONG_CACHE_DIR, RVC_ENABLED, RVC_API_URL, RVC_VOICE_ID,
                          HUM_THRESHOLD, HUM_RANDOM_RANGE, HUM_TRIGGER_PROB)
from .lyric_handler import LyricHandler
from .rvc_handler import RVCHandler
from .playback_handler import PlaybackHandler
from .utils.comment_generator import CommentGenerator
from .utils.intro_generator import IntroGenerator
from .utils.song_downloader import SongDownloader


@singleton
class SingCore:
    log = DefaultLog().getLogger()
    singData = SingData()
    llmData = LLmData()
    ttsCore = TTsCore()
    imageCore = ImageCore()
    emoteOper = EmoteOper()
    actionOper = ActionOper()
    mpvPlay = MpvPlay()

    def __init__(self):
        self.obs = ObsInit().get_ws()
        self.lyric_handler = LyricHandler(SONG_CACHE_DIR, self.log)
        self.rvc_handler = RVCHandler(RVC_ENABLED, RVC_API_URL, RVC_VOICE_ID, SONG_CACHE_DIR, self.log)
        subtitle_srv = get_subtitle_server()
        self.playback = PlaybackHandler(SONG_CACHE_DIR, self.log, subtitle_srv)
        self.stop_requested = False
        self.singData.play_song_lock = Lock()
        self.song_comment_cache = {}
        self.comment_lock = Lock()

        # 配置触发词
        from func.config.default_config import defaultConfig
        config = defaultConfig().get_config()
        sing_cfg = config.get('sing', {})
        self.stop_keywords = sing_cfg.get('stop_keywords', ["停下", "停止"])
        self.learn_keywords = sing_cfg.get('learn_keywords', ["学一下这首歌", "学一下歌", "学习这首歌", "学歌"])
        self.sing_for_me_keywords = sing_cfg.get('sing_for_me_keywords', ["想听喵呜唱歌", "喵呜唱首歌", "唱首歌听", "来首翻唱"])
        self.sing_keywords = sing_cfg.get('sing_keywords', ["唱一下", "唱一首", "唱歌", "点歌", "点播", "找歌", "找首歌听", "来首歌", "播放", "来点音乐", "点个歌"])

        # 初始化工具模块
        self.comment_gen = CommentGenerator(self.lyric_handler, self.log)
        self.intro_gen = IntroGenerator(self.ttsCore, self.log)
        self.song_downloader = SongDownloader(self.log)

    # ================== 辅助方法 ==================
    def _wait_tts_finish(self, timeout=10):
        start = time.time()
        while self.ttsCore.mpvPlay.current_process is not None:
            if time.time() - start > timeout:
                break
            time.sleep(0.1)

    def _record_conversation(self, user_msg, ai_msg, user_name="系统", uid=0):
        """仅记录 LLM 生成的回复（非固定模板）"""
        try:
            from func.llm.llm_core import LLmCore
            llm_core = LLmCore()
            llm_core._write_chat_record(user_name, user_msg, user_name)
            llm_core._write_chat_record(user_name, ai_msg, llm_core.llmData.Ai_Name)
            uid_str = str(uid)
            memory = llm_core._ensure_memory_manager(uid_str, user_name)
            if memory:
                memory.add_user_message(user_msg, user_name)
                memory.add_assistant_message(ai_msg)
        except Exception as e:
            self.log.warning(f"记录对话失败: {e}")

    # ================== 点歌流程 ==================
    def singTry(self, songname, username, uid=0):
        try:
            if songname:
                self.sing(songname, username, uid)
        except Exception:
            self.log.exception("【singTry】异常")
            self.singData.is_singing = 2

    def sing(self, songname, username, uid=0):
        songname = songname.strip()
        if not songname:
            self._random_play(username, uid)
            return
        if self.exist_song_queues(self.singData.SongMenuList, songname):
            self.ttsCore.tts_say(f"回复{username}：歌曲《{songname}》已经在歌单中")
            return
        local_mp3 = self.song_downloader.find_local_song(songname)
        if local_mp3:
            self.log.info(f"找到本地歌曲: {local_mp3}")
            intro_text, llm_gen = self.intro_gen.generate_intro(songname, username, "", uid)
            self._wait_tts_finish()
            if llm_gen:
                self._record_conversation(f"点播《{songname}》", intro_text, username, uid)
            if RVC_ENABLED:
                cover_path = self.rvc_handler.generate_cover(local_mp3, songname)
                if cover_path:
                    local_mp3 = cover_path
            self.singData.SongMenuList.put({
                "username": username, "songname": songname, "mp3_path": local_mp3,
                "query": songname, "uid": uid
            })
            return
        self.ttsCore.tts_say(f"{username}，我去找找《{songname}》这首歌，等一下哦")
        self._wait_tts_finish()
        local_path, real_name, song_id = self.song_downloader.download_song(songname, username)
        if local_path:
            self.log.info(f"服务端下载成功: {local_path}")
            if RVC_ENABLED:
                cover_path = self.rvc_handler.generate_cover(local_path, real_name)
                if cover_path:
                    local_path = cover_path
            self.song_downloader.download_lyric(song_id, real_name, self.lyric_handler)
            intro_text, llm_gen = self.intro_gen.generate_intro(real_name, username, "", uid)
            self._wait_tts_finish()
            if llm_gen:
                self._record_conversation(f"点播《{real_name}》", intro_text, username, uid)
            self.singData.SongMenuList.put({
                "username": username, "songname": real_name, "mp3_path": local_path,
                "query": songname, "uid": uid
            })
        else:
            self.ttsCore.tts_say(f"回复{username}：找不到《{songname}》这首歌曲")

    def _random_play(self, username, uid=0):
        mp3_files = glob.glob(os.path.join(SONG_CACHE_DIR, "*.mp3"))
        mp3_files = [f for f in mp3_files if not os.path.basename(f).startswith("[喵呜翻唱]")]
        if not mp3_files:
            self.ttsCore.tts_say(f"回复{username}：到底唱什么好呢，那就随便来一首吧")
            return
        random_mp3 = random.choice(mp3_files)
        songname = os.path.splitext(os.path.basename(random_mp3))[0]
        self.log.info(f"随机播放歌曲: {songname}")
        intro_text, llm_gen = self.intro_gen.generate_intro(songname, username, "随机播放", uid)
        self._wait_tts_finish()
        if llm_gen:
            self._record_conversation("随机播放", intro_text, username, uid)
        self.singData.SongMenuList.put({
            "username": username, "songname": songname, "mp3_path": random_mp3,
            "query": songname, "uid": uid
        })

    # ================== 播放核心 ==================
    def play_song(self, songname, mp3_path, username, query, uid=0):
        try:
            self.log.info(f"开始播放《{songname}》")
            Thread(target=self.imageCore.searchimg_output, args=({"prompt": query, "username": username},)).start()
            self.emoteOper.emote_ws(1, 0.2, "唱歌")
            Thread(target=self.actionOper.auto_swing).start()
            self.playback.play_with_lyrics(mp3_path)
            return 1
        except Exception:
            self.log.exception(f"《{songname}》播放异常")
            return 3
        finally:
            self.emoteOper.emote_ws(1, 0.2, "唱歌")

    # ================== 队列轮询 ==================
    def check_playSongMenuList(self):
        if self.singData.SongMenuList.empty() or self.singData.is_singing != 2:
            return
        self.singData.play_song_lock.acquire()
        try:
            if self.singData.SongMenuList.empty():
                return
            mlist = self.singData.SongMenuList.get()
            self.singData.SongNowName = mlist
            self.singData.is_singing = 1
            if self.obs:
                self.obs.control_video("背景音乐", VideoControl.PAUSE.value)
            self.stop_requested = False
            self.playback.stop_requested = False
            # 后台生成解说（不阻塞播放）
            Thread(target=self._prepare_song_comment, args=(mlist["songname"], mlist["username"], mlist.get("uid", 0), mlist["query"]), daemon=True).start()
        except Exception:
            self.log.exception("获取队列异常")
            self.singData.is_singing = 2
            self.singData.SongNowName = {}
            return
        finally:
            self.singData.play_song_lock.release()

        try:
            uid = mlist.get("uid", 0)
            self.play_song(mlist["songname"], mlist["mp3_path"], mlist["username"], mlist["query"], uid)
        except Exception:
            self.log.exception("播放过程异常")

        # 歌曲播放完毕，立即重置唱歌状态（允许新的点歌）
        self.singData.is_singing = 2

        if not self.playback.stop_requested:
            time.sleep(3)
            comment = None
            with self.comment_lock:
                cached = self.song_comment_cache.get(mlist["songname"])
                if cached and cached.get("ready"):
                    comment = cached["text"]
                if mlist["songname"] in self.song_comment_cache:
                    del self.song_comment_cache[mlist["songname"]]
            if not comment:
                comment = f"《{mlist['songname']}》是一首很棒的歌曲。"
                self.log.warning(f"歌曲《{mlist['songname']}》解说缓存未就绪，使用默认语句")

            comment = re.sub(r'[（(][^）)]*[）)]', '', comment)
            comment = re.sub(r'\s+', ' ', comment).strip()

            # 批量分段播放感谢语和解说
            traceid = str(uuid.uuid4())
            all_sentences = [f"《{mlist['songname']}》唱完啦"]
            final_segments = self._split_comment(comment)
            all_sentences.extend(final_segments)
            total = len(all_sentences)
            for idx, sent in enumerate(all_sentences):
                if not sent.strip():
                    continue
                json_data = {
                    "voiceType": "chat", "traceid": traceid,
                    "chatStatus": "end" if idx == total-1 else "middle",
                    "question": "", "text": sent, "lanuage": "AutoChange",
                    "seg_index": idx, "total_segments": total
                }
                self.ttsCore.tts_say_do(json_data)

            # 仅记录 LLM 生成的解说内容（comment 可能是默认或 LLM 生成）
            # 注意：comment 如果是默认语句，则不记录（避免记录固定模板）
            if comment and comment != f"《{mlist['songname']}》是一首很棒的歌曲。":
                self._record_conversation(f"听完《{mlist['songname']}》", comment, mlist["username"], uid)
        else:
            self.log.info(f"歌曲《{mlist['songname']}》被用户停止，不进行解说")

        # 清空当前歌曲记录
        self.singData.SongNowName = {}
        if self.singData.SongMenuList.qsize() == 0 and self.obs:
            self.obs.control_video("背景音乐", VideoControl.PLAY.value)

    def _split_comment(self, comment):
        if not comment:
            return []
        split_pattern = r'([。！？；：，,.;:!?])'
        parts = re.split(split_pattern, comment)
        segments = []
        buffer = ""
        for part in parts:
            if re.match(split_pattern, part):
                buffer += part
                if buffer.strip():
                    segments.append(buffer.strip())
                buffer = ""
            else:
                buffer += part
        if buffer.strip():
            segments.append(buffer.strip())
        final = []
        for seg in segments:
            if len(seg) > 15:
                sub_parts = re.split(r'([，, ])', seg)
                sub_buf = ""
                for sp in sub_parts:
                    sub_buf += sp
                    if len(sub_buf) > 6 and (sp in ['，', ',', ' '] or sub_buf.endswith(('。','！','？','；','：'))):
                        if sub_buf.strip():
                            final.append(sub_buf.strip())
                        sub_buf = ""
                if sub_buf.strip():
                    final.append(sub_buf.strip())
            else:
                final.append(seg)
        return final if final else [comment]

    def _prepare_song_comment(self, songname, username, uid, query):
        try:
            comment = self.comment_gen.generate_comment(songname, username, uid, query)
            with self.comment_lock:
                self.song_comment_cache[songname] = {"text": comment, "ready": True}
            self.log.info(f"歌曲《{songname}》解说内容已准备好: {comment}")
        except Exception as e:
            self.log.warning(f"提前准备解说失败: {e}")
            with self.comment_lock:
                self.song_comment_cache[songname] = {"text": f"《{songname}》是一首很棒的歌曲。", "ready": True}

    # ================== 点歌队列处理 ==================
    def check_sing(self):
        if not self.singData.SongQueueList.empty():
            song_json = self.singData.SongQueueList.get()
            if self.singData.is_singing == 1:
                self.log.info("正在唱歌，点歌任务延迟处理")
                time.sleep(1)
                self.singData.SongQueueList.put(song_json)
                return
            self.log.info(f"收到点歌: {song_json}")
            uid = song_json.get("uid", 0)
            Thread(target=self.singTry, args=(song_json["prompt"], song_json["username"], uid)).start()

    # ================== 停止指令 ==================
    def stopTry(self):
        try:
            self.stop_playing()
            self.ttsCore.tts_say("好的，已停止播放")
        except Exception:
            self.log.exception("【stopTry】异常")

    def stop_playing(self):
        try:
            self.singData.play_song_lock.acquire()
            self.playback.stop_requested = True
            self.playback.stop()
            while not self.singData.SongMenuList.empty():
                self.singData.SongMenuList.get()
            self.singData.SongNowName = {}
            self.singData.is_singing = 2
            if self.obs:
                self.obs.control_video("背景音乐", VideoControl.PLAY.value)
            self.log.info("唱歌已停止，队列清空")
        except Exception:
            self.log.exception("stop_playing 异常")
        finally:
            self.singData.play_song_lock.release()

    # ================== 哼歌模块 ==================
    def try_hum_song(self, text: str, username: str, uid: int = 0):
        if random.random() > HUM_TRIGGER_PROB:
            return False
        if len(text) <= 15:
            return False
        matched = self.lyric_handler.match_lyric(text, HUM_THRESHOLD)
        if not matched:
            return False
        song_name, start_timestamp, matched_text, sim = matched
        self.log.info(f"哼歌匹配成功: 歌曲《{song_name}》 歌词“{matched_text}” 相似度 {sim}%")

        all_sentences = self.lyric_handler.get_all_sentences(song_name)
        if not all_sentences:
            return False
        match_idx = None
        for i, (ts, line) in enumerate(all_sentences):
            if abs(ts - start_timestamp) < 0.5 and line == matched_text:
                match_idx = i
                break
        if match_idx is None:
            return False
        extra = random.randint(*HUM_RANDOM_RANGE)
        end_idx = min(match_idx + extra + 1, len(all_sentences))
        start_ts = all_sentences[match_idx][0]
        end_ts = all_sentences[end_idx-1][0] + 3

        cover_file = self.rvc_handler.get_cover_path(song_name)
        original_file = os.path.join(SONG_CACHE_DIR, f"{song_name}.mp3")
        play_file = None
        file_type = None
        if cover_file:
            play_file = cover_file
            file_type = "cover"
        elif os.path.exists(original_file):
            play_file = original_file
            file_type = "original"
        else:
            self.ttsCore.tts_say(f"喵呜还没学会《{song_name}》这首歌呢")
            return True

        if file_type == "cover":
            trans = random.choice([
                "喵呜想起了一首歌的哪一段",
                "让我想想，好像是这样的",
                "哼，这一句我记得",
                "啊，是这首歌里的",
                "喵~ 这一段我很喜欢"
            ])
            self.ttsCore.tts_say(trans)
            self._wait_tts_finish()
            # 固定过渡语不记录到聊天记录
        else:
            llm_prompt = f"用户刚刚的对话让你想起了歌曲《{song_name}》中的一句歌词“{matched_text}”。告诉用户你想起了一句歌词，并准备哼唱出来。"
            intro = f"之前《{song_name}》有一句歌词，刚刚的对话让你想起来了，告诉大家吧"
            try:
                from func.llm.llm_core import LLmCore
                llm_core = LLmCore()
                if llm_core.local_llm_type == "ollama":
                    from func.llm.port.ollama import Ollama
                    client = Ollama()
                    intro = client.generate(llm_prompt, system="你是一个虚拟主播，直接输出回复。")
                elif llm_core.local_llm_type == "aliyun":
                    from func.llm.port.aliyun_stream import AliyunStreamLLM
                    client = AliyunStreamLLM()
                    messages = [{"role": "user", "content": llm_prompt}]
                    full = ""
                    for chunk in client.generate_stream(messages, options={"max_tokens": 50}):
                        full += chunk
                    intro = full.strip()
                elif llm_core.local_llm_type == "deepseek":
                    from func.llm.port.deepseek import DeepSeekLLM
                    client = DeepSeekLLM()
                    messages = [{"role": "user", "content": llm_prompt}]
                    try:
                        intro = client.generate(messages, options={"max_tokens": 50}).strip()
                    except TypeError:
                        intro = client.generate(messages).strip()
            except Exception as e:
                self.log.warning(f"LLM 生成过渡语句失败: {e}")
            self.ttsCore.tts_say(intro)
            self._wait_tts_finish()
            self.ttsCore.tts_say("喵呜不会翻唱，喵呜放原唱吧")
            self._wait_tts_finish()
            # 记录 LLM 生成的 intro
            self._record_conversation(text, intro, username, uid)

        segment_sentences = all_sentences[match_idx:end_idx]
        self.playback.play_fragment_with_lyrics(play_file, start_ts, end_ts, segment_sentences)
        return True

    # ================== HTTP 接口 ==================
    def http_sing(self, songname, username):
        self.log.info(f'HTTP点歌: "{username}" 点播《{songname}》')
        self.singData.SongQueueList.put({"prompt": songname, "username": username, "uid": 0})

    def http_songlist(self, _):
        jsonstr = []
        if self.singData.SongNowName:
            jsonstr.append({
                "songname": f"'{self.singData.SongNowName['username']}'点播《{self.singData.SongNowName['songname']}》"
            })
        for i in range(self.singData.SongMenuList.qsize()):
            data = self.singData.SongMenuList.queue[i]
            jsonstr.append({"songname": f"'{data['username']}'点播《{data['songname']}》"})
        return f'({"status": "成功","content": {json.dumps(jsonstr)}})'

    # ================== 指令识别 ==================
    def msg_deal(self, traceid, query, uid, user_name):
        if self._handle_stop_command(traceid, query, user_name):
            return True
        if self._handle_learn_command(traceid, query, user_name, uid):
            return True
        if self._handle_sing_for_me_command(traceid, query, user_name, uid):
            return True
        if self.singData.is_singing == 1:
            self.ttsCore.tts_say("喵呜正在唱歌，请稍后再点歌喵～")
            return True
        if self._handle_sing_command(traceid, query, user_name, uid):
            return True
        if self.try_hum_song(query, user_name, uid):
            return True
        return False

    def _handle_stop_command(self, traceid, query, user_name):
        for kw in self.stop_keywords:
            if kw in query:
                self.log.info(f"[{traceid}] 停止指令: {query}")
                Thread(target=self.stopTry).start()
                return True
        return False

    def _handle_learn_command(self, traceid, query, user_name, uid):
        for kw in self.learn_keywords:
            if kw in query:
                songname = self._extract_songname_by_llm(query, traceid)
                if not songname:
                    self.ttsCore.tts_say("哪一首？")
                    return True
                self.ttsCore.tts_say(f"《{songname}》吗，那喵呜学一下吧")
                self._learn_song(songname, user_name, traceid, uid)
                return True
        return False

    def _handle_sing_for_me_command(self, traceid, query, user_name, uid):
        if not any(kw in query for kw in self.sing_for_me_keywords):
            return False
        covers = glob.glob(os.path.join(SONG_CACHE_DIR, "[喵呜翻唱]*.mp3"))
        if not covers:
            self.ttsCore.tts_say("我还没学会任何歌曲呢")
            return True
        cover_path = random.choice(covers)
        songname = os.path.basename(cover_path).replace("[喵呜翻唱]", "").replace(".mp3", "")
        # 生成开场白（可能 LLM 生成）
        intro_text, llm_gen = self.intro_gen.generate_intro(songname, user_name, query, uid)
        self._wait_tts_finish()
        if llm_gen:
            self._record_conversation(query, intro_text, user_name, uid)
        self.singData.SongMenuList.put({
            "username": user_name, "songname": songname, "mp3_path": cover_path,
            "query": songname, "uid": uid
        })
        return True

    def _handle_sing_command(self, traceid, query, user_name, uid):
        if not any(kw in query for kw in self.sing_keywords):
            return False

        # 优先检测随机播放意图
        random_keywords = ["随便唱", "随意唱", "来一首", "随便来一首", "随便点一首", "随便唱一首"]
        if any(kw in query for kw in random_keywords):
            self.log.info(f"[{traceid}] 检测到随机播放意图，触发随机播放")
            self._random_play(user_name, uid)
            return True

        song_query = ""
        if getattr(self.singData, 'enable_llm_extract_song', True):
            song_query = self._extract_songname_by_llm(query, traceid)
    
        # 如果 LLM 没有提取到有效歌名，尝试正则匹配书名号
        if not song_query:
            import re
            match = re.search(r'《([^》]+)》', query)
            if match:
                song_query = match.group(1).strip()
                self.log.info(f"[{traceid}] 正则提取歌名: {song_query}")
    
        # 如果仍然没有，则不再进行截取，直接提示用户
        if not song_query:
            self.ttsCore.tts_say("喵呜没听懂你要点哪首歌，可以说清楚歌名或者用书名号括起来吗？")
            return True

        self.log.info(f"[{traceid}] 点歌: {song_query}")
        self.singData.SongQueueList.put({
            "traceid": traceid, "prompt": song_query, "username": user_name, "uid": uid
        })
        return True

    def _extract_songname_by_llm(self, query: str, traceid: str = "") -> str:
        try:
            from func.llm.llm_core import LLmCore
            llm_core = LLmCore()
            prompt = (
                f"请从以下用户消息中提取他想点的歌曲名称。\n"
                f"要求：\n"
                f"1. 如果用户没有明确点歌意图或没有歌曲名，请只输出'无'。\n"
                f"2. 如果用户使用了书名号《》，请原样输出书名号内的全部内容（例如《letter song》输出 'letter song'）。\n"
                f"3. 歌名可能包含多个单词、空格或标点，请输出完整的歌名，不要只输出第一个单词。\n"
                f"4. 只输出歌曲名本身，不要输出任何额外解释、歌手信息或标点符号。\n"
                f"5. 如果用户说'随便唱一首'、'随便来首歌'等，输出'无'。\n\n"
                f"用户消息：{query}"
            )
            songname = ""
            if llm_core.local_llm_type == "ollama":
                from func.llm.port.ollama import Ollama
                client = Ollama()
                response = client.generate(prompt, system="你是一个歌名提取助手，只输出完整歌名或'无'，不要其他内容。")
                songname = response.strip()
            elif llm_core.local_llm_type == "aliyun":
                from func.llm.port.aliyun_stream import AliyunStreamLLM
                client = AliyunStreamLLM()
                messages = [{"role": "user", "content": prompt}]
                full = ""
                for chunk in client.generate_stream(messages, options={"max_tokens": 60, "temperature": 0.7}):
                    full += chunk
                songname = full.strip()
            elif llm_core.local_llm_type == "deepseek":
                from func.llm.port.deepseek import DeepSeekLLM
                client = DeepSeekLLM()
                messages = [{"role": "user", "content": prompt}]
                try:
                    songname = client.generate(messages, options={"max_tokens": 60, "temperature": 0.7}).strip()
                except TypeError:
                    songname = client.generate(messages).strip()
            else:
                return ""

            # 无效情况
            if not songname or songname == "无" or len(songname) > 50:
                return ""

            # 清理可能的引号和书名号
            songname = songname.strip('"\'《》')
            # 如果清理后还包含明显不是歌名的字符（如逗号、句号、问号等），丢弃
            if re.search(r'[，,。！？；：]', songname):
                return ""

            self.log.info(f"[{traceid}] LLM 提取歌名成功: {songname}")
            return songname

        except Exception as e:
            self.log.warning(f"[{traceid}] LLM 提取歌名失败: {e}")
            return ""

    def _learn_song(self, songname, username, traceid="", uid=0):
        self.log.info(f"学歌: {songname} by {username}")
        search_core = SearchCore()
        results = search_core.baidu_web_search(songname)
        if not results:
            self.ttsCore.tts_say(f"抱歉，没有找到关于《{songname}》的信息")
            # 固定回复不记录
            return
        context = "\n".join([f"- {r.get('title','')}: {r.get('abstract','')}" for r in results[:3]])
        character_suffix = self._get_character_prompt_suffix(f"学一下《{songname}》")
        if character_suffix:
            prompt = f"《{songname}》相关信息：\n{context}\n{character_suffix}跟主人分享一下吧"
        else:
            prompt = f"《{songname}》相关信息：\n{context}\n跟主人分享一下吧"
        try:
            from func.llm.llm_core import LLmCore
            llm_core = LLmCore()
            if llm_core.local_llm_type == "ollama":
                from func.llm.port.ollama import Ollama
                client = Ollama()
                explanation = client.generate(prompt, system="你是一个音乐解说员，请直接输出介绍。")
            elif llm_core.local_llm_type == "aliyun":
                from func.llm.port.aliyun_stream import AliyunStreamLLM
                client = AliyunStreamLLM()
                messages = [{"role": "user", "content": prompt}]
                full = ""
                for chunk in client.generate_stream(messages, options={"max_tokens": 150}):
                    full += chunk
                explanation = full.strip()
            elif llm_core.local_llm_type == "deepseek":
                from func.llm.port.deepseek import DeepSeekLLM
                client = DeepSeekLLM()
                messages = [{"role": "user", "content": prompt}]
                try:
                    explanation = client.generate(messages, options={"max_tokens": 150}).strip()
                except TypeError:
                    explanation = client.generate(messages).strip()
            else:
                explanation = f"《{songname}》是一首很棒的歌曲。"
        except Exception as e:
            self.log.warning(f"LLM 解说失败: {e}")
            explanation = f"《{songname}》是一首很棒的歌曲。"
        self.ttsCore.tts_say(explanation)
        # 记录 LLM 生成的解说
        if explanation != f"《{songname}》是一首很棒的歌曲。":
            self._record_conversation(f"学一下《{songname}》", explanation, username, uid)

    def _get_character_prompt_suffix(self, user_query: str) -> str:
        try:
            from func.llm.llm_core import LLmCore
            llm_core = LLmCore()
            if not llm_core.character_cards:
                return ""
            card = llm_core.select_character_by_message(user_query)
            if card:
                personality = card.personality[:50] if card.personality else ""
                if personality:
                    return f"请以下角色个性：{personality}。以{card.name}的口吻说一句简短的开场白，表示即将演唱这首歌。不要超过20个字。"
                else:
                    return f"请以角色“{card.name}”的口吻说一句简短的开场白，表示即将演唱这首歌。不要超过20个字。"
        except Exception as e:
            self.log.warning(f"获取角色卡失败: {e}")
        return ""

    def exist_song_queues(self, queues, name):
        if self.singData.SongNowName and self.singData.SongNowName.get("songname") == name:
            return True
        for i in range(queues.qsize()):
            if queues.queue[i]["songname"] == name:
                return True
        return False