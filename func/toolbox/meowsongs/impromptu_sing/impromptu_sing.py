# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/impromptu_sing/impromptu_sing.py
# 即兴哼唱：根据歌词匹配播放翻唱片段（不带伴奏），随机/模糊匹配/精确匹配
import os
import re
import random
import difflib

import soundfile as sf

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig

MEOW_DIR = os.path.join("character", "songs", "meow_list")

TIME_RE = re.compile(r"\[(\d{2}):(\d{2})\.(\d{3})\](.*)")


@singleton
class TBImpromptuSing:
    """即兴哼唱执行：歌词解析、模糊匹配、片段截取播放"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self.last_slice_path = ""

    def build_tool(self):
        return {
            "type": "function",
            "function": {
                "name": "impromptu_sing",
                "description": (
                    "即兴哼唱一首已学歌曲的片段。根据用户消息判断想听哪首歌的哪段歌词，"
                    "不确定就填 random。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "song_title": {"type": "string", "description": "歌名，不确定填 random"},
                        "start_lrc": {"type": "string", "description": "开始的歌词句子，不确定填 random"},
                        "end_lrc": {"type": "string", "description": "结束的歌词句子，不确定填 random"},
                    },
                    "required": ["song_title", "start_lrc", "end_lrc"],
                },
            },
        }

    def run(self, text, username="", with_lyric=True):
        """入口：LLM function_calling 提取歌名与歌词后播放"""
        song_title, start_lrc, end_lrc = self.decide(text, username)
        return self.sing(song_title, start_lrc, end_lrc, username=username, with_lyric=with_lyric)

    def decide(self, text, username=""):
        """用 toolbox LLM 决定唱哪首歌哪段，不确定返回 random"""
        song_title = start_lrc = end_lrc = "random"
        try:
            from func.toolbox.config import TBoxConfig
            from func.toolbox.get_prompt import TBoxGetPrompt
            cfg = TBoxConfig()
            if cfg.llm_type == "aliyun":
                from func.toolbox.port.aliyun import TBoxAliyunLLM
                llm = TBoxAliyunLLM(cfg)
            else:
                from func.toolbox.port.deepseek import TBoxDeepSeekLLM
                llm = TBoxDeepSeekLLM(cfg)
            if llm is None or not llm.client:
                return song_title, start_lrc, end_lrc
            system_prompt = TBoxGetPrompt().get_system_prompt(username, text) or ""
            resp = llm.chat(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": text}],
                tools=[self.build_tool()],
            )
            if resp and getattr(resp, "choices", None):
                import json
                msg = resp.choices[0].message
                for tc in (msg.tool_calls or []):
                    if tc.function.name != "impromptu_sing":
                        continue
                    args = json.loads(tc.function.arguments or "{}")
                    song_title = str(args.get("song_title") or "random").strip() or "random"
                    start_lrc = str(args.get("start_lrc") or "random").strip() or "random"
                    end_lrc = str(args.get("end_lrc") or "random").strip() or "random"
        except Exception:
            self.log.exception("[MeowSongs] 参数决策异常")
        return song_title, start_lrc, end_lrc

    def sing(self, song_title, start_lrc, end_lrc, username="", with_lyric=True):
        """按歌名/歌词确定片段并播放，返回播放结果文本"""
        if not self.config.enabled:
            return "即兴哼唱未启用"
        titles = self._list_titles()
        if not titles:
            return "还没有学过的歌曲"

        title = song_title
        if not title or title.strip().lower() == "random":
            title = self._resolve_title_by_lyric(start_lrc, titles) if start_lrc and start_lrc.strip().lower() != "random" else None
            if not title:
                title = random.choice(titles)

        lrc = self._load_lrc(title)
        if not lrc:
            return f"没有找到《{title}》的歌词"

        start_idx, end_idx = self._resolve_range(lrc, start_lrc, end_lrc)
        self._play_slice(title, lrc, start_idx, end_idx, with_lyric=with_lyric)
        self._record_hum_song(username, lrc, start_idx, end_idx)
        return f"哼唱《{title}》"

    def _resolve_title_by_lyric(self, lyric, titles):
        best_title, best_score = None, 0.0
        for t in titles:
            lines = [x["text"] for x in self._load_lrc(t)]
            for line in lines:
                score = difflib.SequenceMatcher(None, lyric, line).ratio()
                if score > best_score:
                    best_score, best_title = score, t
        return best_title if best_score >= 0.5 else None

    def _resolve_range(self, lrc, start_lrc, end_lrc):
        total = len(lrc)
        start_idx = None
        if start_lrc and start_lrc.strip().lower() != "random":
            start_idx = self._match_line(lrc, start_lrc)
        if start_idx is None:
            start_idx = random.randint(0, max(0, total - 1))

        end_idx = None
        if end_lrc and end_lrc.strip().lower() != "random":
            end_idx = self._match_line(lrc, end_lrc)

        if end_idx is None:
            end_idx = min(start_idx + 2, total - 1)

        if start_idx > end_idx:
            start_idx = max(0, end_idx - 2)

        span = lrc[end_idx]["time"] - lrc[start_idx]["time"]
        while span < 3.0 and end_idx < total - 1:
            end_idx += 1
            span = lrc[end_idx]["time"] - lrc[start_idx]["time"]
        return start_idx, end_idx

    def _play_slice(self, title, lrc, start_idx, end_idx, with_lyric=True):
        try:
            vocal_path = os.path.join(MEOW_DIR, title, f"{title}_vocal.wav")
            if not os.path.exists(vocal_path):
                return
            data, sr = sf.read(vocal_path, dtype="float32")
            start_sec = lrc[start_idx]["time"]
            end_sec = lrc[end_idx]["time"] + max(2.0, self._line_duration(lrc, end_idx))
            end_sec = min(end_sec, len(data) / sr)
            start_sample = int(start_sec * sr)
            end_sample = int(end_sec * sr)
            if end_sample <= start_sample:
                end_sample = min(start_sample + int(3 * sr), len(data))
            audio = data[start_sample:end_sample]
            tmp_path = os.path.join(".temp", "meowsongs_latest.wav")
            os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
            sf.write(tmp_path, audio, sr)
            self.last_slice_path = tmp_path
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().play_audio(
                audio, sr, source="meowsongs",
                lyric_lines=lrc if with_lyric else None,
                lyric_start_idx=start_idx,
                lyric_end_idx=end_idx,
            )
        except Exception:
            self.log.exception("[MeowSongs] 片段播放异常")

    def _record_hum_song(self, username, lrc, start_idx, end_idx):
        """把即兴哼唱片段对应歌词以 hum_song 形式写入短期/长期/摘要/用户记忆"""
        lyrics = " ".join(
            (lrc[i].get("text") or "").strip()
            for i in range(start_idx, end_idx + 1)
            if (lrc[i].get("text") or "").strip()
        )
        if not lyrics:
            return
        username = username or "用户"
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save(
                {"role": "assistant", "content": lyrics, "type": "hum_song"},
                50, trim_mode="items",
            )
        except Exception:
            self.log.exception("[MeowSongs] 短期记忆保存异常")
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            from func.config.app_config import AppConfig
            MeowLLMLtMemBridge().record_ai_message(username, AppConfig().ai_name, lyrics)
        except Exception:
            self.log.exception("[MeowSongs] 长期/用户记忆保存异常")

    def _match_line(self, lrc, lyric):
        best_idx, best_score = 0, 0.0
        for i, item in enumerate(lrc):
            score = difflib.SequenceMatcher(None, lyric, item["text"]).ratio()
            if score > best_score:
                best_score, best_idx = score, i
        return best_idx if best_score >= 0.4 else 0

    def _line_duration(self, lrc, idx):
        if idx + 1 < len(lrc):
            return max(1.0, lrc[idx + 1]["time"] - lrc[idx]["time"])
        return 3.0

    def _list_titles(self):
        if not os.path.isdir(MEOW_DIR):
            return []
        return [d for d in os.listdir(MEOW_DIR)
                if os.path.isdir(os.path.join(MEOW_DIR, d))
                and os.path.exists(os.path.join(MEOW_DIR, d, f"{d}_vocal.wav"))]

    def _load_lrc(self, title):
        lrc_path = os.path.join(MEOW_DIR, title, f"{title}.lrc")
        if not os.path.exists(lrc_path):
            return []
        result = []
        try:
            with open(lrc_path, "r", encoding="utf-8") as f:
                for line in f.read().splitlines():
                    m = TIME_RE.match(line.strip())
                    if not m:
                        continue
                    mm, ss, ms = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    result.append({"time": mm * 60 + ss + ms / 1000.0, "text": m.group(4).strip()})
        except Exception:
            self.log.exception("[MeowSongs] 读取歌词异常")
        return result
