# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/pass_the_baton/pass_the_baton.py
# 听歌识曲接龙工具入口：哼唱匹配 → 往后接唱 → 感想引导（不走 song_review）
import os
from typing import Dict, List

import soundfile as sf

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig
from func.toolbox.meowsongs.pass_the_baton.hum_match import TBHumMatch
from func.toolbox.meowsongs.pass_the_baton.next_line import TBNextLine
from func.config.app_config import AppConfig

MEOW_DIR = os.path.join("character", "songs", "meow_list")


@singleton
class TBPassTheBaton:
    """听歌识曲接龙工具入口：analysis 决定调用，本模块负责匹配、接唱、感想与记忆"""

    TOOL_NAME = "pass_the_baton"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self.match = TBHumMatch()
        self.next_line = TBNextLine()
        self._username = ""
        self._last_slice_path = ""

    def set_username(self, username):
        self._username = username or ""

    def build_tools(self) -> List[Dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "用户哼唱了一首已学歌曲的片段，角色需要识别歌曲并接着往下唱几句时调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }]

    def dispatch(self, name, arguments):
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        if not self.config.pbt_enabled:
            return "听歌识曲接龙未启用"
        return self.run()

    def dispatch_qq(self, name, arguments, qq_context):
        if name != self.TOOL_NAME or not self.config.pbt_enabled:
            return None
        result = self.run()
        if qq_context and getattr(self, "_last_slice_path", ""):
            self._send_qq_voice(qq_context, self._last_slice_path)
        return result

    def run(self):
        """主流程：取哼唱音频 → 匹配 → 接唱 + 记忆 / 匹配失败询问"""
        from func.pipeline.toolbox_audio import ToolboxAudioBridge
        bridge = ToolboxAudioBridge()
        hum_wav = bridge.consume_hum_audio()
        username = bridge.get_last_speaker() or self._username or "用户"

        if not hum_wav or not os.path.exists(hum_wav):
            return "没有检测到哼唱音频"

        hum_duration = self._audio_duration(hum_wav)
        title, offset, score = self.match.match(hum_wav)

        try:
            os.remove(hum_wav)
        except Exception:
            pass

        if not title:
            self._ask_hum(username)
            return "没有识别出这首歌"

        user_lyric, start_sec, end_sec, next_lines = self.next_line.locate(title, offset, hum_duration)
        if start_sec is None:
            self._ask_hum(username)
            return f"识别到《{title}》，但没有可接的歌词"

        # 匹配成功 → 进入唱歌状态（利用唱歌中拦截，屏蔽后续 ASR 乱码）
        from func.pipeline.singing_state import SingingStateBridge
        SingingStateBridge().start_singing("cover", title)
        try:
            # 记忆：用户哼唱歌词
            if user_lyric:
                self._record_hum_song(username, "user", user_lyric)

            # 接唱
            self._play_from(title, start_sec, end_sec)

            # 记忆：AI 接唱歌词
            ai_lyric = " ".join(next_lines) if next_lines else ""
            if ai_lyric:
                self._record_hum_song(username, "assistant", ai_lyric)

            # 感想（LLM 回复单独保存）
            self._send_feeling(title, next_lines, username)

            # 等待接唱与感想播报完成
            self._wait_tts_idle()
        finally:
            SingingStateBridge().end_singing()
        return f"识别到《{title}》，接着唱"

    def _play_from(self, title, start_sec, end_sec=None):
        """从 vocal 轨指定秒数开始播放到结束秒数（走 TTS 播放队列），同时落盘供 QQ 发送"""
        try:
            safe = self._safe_name(title)
            vocal = os.path.join(MEOW_DIR, safe, f"{safe}_vocal.wav")
            data, sr = sf.read(vocal, dtype="float32")
            start_sample = int(start_sec * sr)
            end_sample = int(end_sec * sr) if end_sec else len(data)
            if end_sample <= start_sample:
                end_sample = len(data)
            audio = data[start_sample:end_sample]

            # 落盘临时文件供 NapCat 语音发送
            tmp_path = os.path.join(".temp", "meowsongs_baton.wav")
            os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
            sf.write(tmp_path, audio, sr)
            self._last_slice_path = tmp_path

            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().play_audio(audio, sr, source="meowsongs")
        except Exception:
            self.log.exception("[PassTheBaton] 接唱播放异常")

    def _ask_hum(self, username):
        """匹配失败：LLM 以角色身份询问用户是否在唱歌"""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            from func.toolbox.config import TBoxConfig
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            llm = self._llm()
            if not llm or not llm.client:
                return
            system_prompt = TBoxGetPrompt().get_system_prompt(username, "") or ""
            guide = self.config.ask_prompt
            if not guide:
                return
            resp = llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": guide},
            ])
            content = ""
            if resp and getattr(resp, "choices", None):
                content = (resp.choices[0].message.content or "").strip()
            if content:
                ToolboxTtsBridge().send_stream(content, source="meowsongs")
                self._record_llm_reply(username, content)
        except Exception:
            self.log.exception("[PassTheBaton] 匹配失败询问异常")

    def _send_feeling(self, title, lines, username):
        """通过 toolbox LLM 生成感想并播报（LLM 回复单独保存）"""
        lyric = " ".join(lines) if lines else ""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            llm = self._llm()
            if not llm or not llm.client:
                return
            system_prompt = TBoxGetPrompt().get_system_prompt(username, "") or ""
            template = self.config.feeling_prompt
            if not template:
                return
            guide = template.replace("{title}", title).replace("{lyric}", lyric)
            resp = llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": guide},
            ])
            content = ""
            if resp and getattr(resp, "choices", None):
                content = (resp.choices[0].message.content or "").strip()
            if content:
                ToolboxTtsBridge().send_stream(content, source="meowsongs")
                self._record_llm_reply(username, content)
        except Exception:
            self.log.exception("[PassTheBaton] 感想生成异常")

    def _llm(self):
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)

    def _record_hum_song(self, username, role, content):
        """保存哼唱歌词到短期/长期/用户记忆（type=hum_song，插播挂靠）"""
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({"role": role, "content": content, "type": "hum_song"},
                               50, trim_mode="items")
        except Exception:
            self.log.exception("[PassTheBaton] 短期记忆保存异常")
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            if role == "user":
                MeowLLMLtMemBridge().record_user_message(username, content)
            else:
                MeowLLMLtMemBridge().record_ai_message(username, AppConfig().ai_name, content)
        except Exception:
            self.log.exception("[PassTheBaton] 长期/用户记忆保存异常")

    def _record_llm_reply(self, username, content):
        """LLM 回复单独保存到短期/长期/用户记忆（type=llm_fast_response）"""
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({"role": "assistant", "content": content, "type": "llm_fast_response"},
                               40, trim_mode="rounds")
        except Exception:
            self.log.exception("[PassTheBaton] 短期记忆保存异常")
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            MeowLLMLtMemBridge().record_ai_message(username, AppConfig().ai_name, content)
        except Exception:
            self.log.exception("[PassTheBaton] 长期/用户记忆保存异常")

    def _wait_tts_idle(self):
        """等待接唱与感想播报完成（阻塞，不额外延迟 ASR）"""
        import time
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            bridge = ToolboxTtsBridge()
            for _ in range(600):
                if not bridge.is_busy():
                    return
                time.sleep(0.1)
        except Exception:
            pass

    def _send_qq_voice(self, qq_context, slice_path):
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            core = TBNapCatCore()
            if str(qq_context.get("message_type", "")) == "group":
                core.send_group_voice(str(qq_context.get("target_id", "")), slice_path)
            else:
                core.send_private_voice(
                    str(qq_context.get("target_id", "") or qq_context.get("user_id", "")),
                    slice_path,
                )
        except Exception:
            pass

    @staticmethod
    def _audio_duration(path):
        try:
            data, sr = sf.read(path, dtype="float32")
            return len(data) / sr
        except Exception:
            return 0.0

    @staticmethod
    def _safe_name(name):
        import re
        return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip() or "未命名"
