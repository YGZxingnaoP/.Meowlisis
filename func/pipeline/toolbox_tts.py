# -*- coding: utf-8 -*-
# func/pipeline/toolbox_tts.py
# Toolbox 传递 TTS 桥接

import re
import uuid

from func.log.default_log import DefaultLog


class ToolboxTtsBridge:
    """Toolbox → TTS 传递桥接

    本桥接在 pipeline 层内部持有 LLmState（AnswerList），
    toolbox 层只传递文本数据，不再直接 import/操作 llm 层状态对象。
    """

    # 分段标点（与主 LLM 一致，按这些标点切分成多个 TTS 片段）
    SPLIT_CHARS = [",", "，", "。", "!", "！", "?", "？", "；", ";"]

    # 分段最小长度（字）：不足该长度即使遇到标点也不切，继续累积到下一句
    # 可在 config.yml 的 tts.seg_min_len 修改；0 = 遇标点就切（旧行为）
    DEFAULT_SEG_MIN_LEN = 24

    def __init__(self):
        self.log = DefaultLog().getLogger()
        # pipeline 层自己持有 TTS 回答队列所属状态，封装 llm 层运行时对象
        from func.llm.state import LLmState
        self.llm_data = LLmState()

    def send_to_answer_queue(self, text: str, traceid: str = "",
                             seg_index: int = 0, chat_status: str = "end",
                             source: str = "toolbox", emotion: str = ""):
        """将 toolbox 输出文本片段推送到 TTS 回答队列（空文本 + end 作为结束标记仍发送）

        - source 仅作来源标注（如 toolbox / toolbox_watching），不作为 TTS 分组键。
        """
        # 静默状态：不出声
        from func.pipeline.silence_state import SilenceState
        if SilenceState().muted:
            return
        if not text and chat_status != "end":
            return
        json_msg = {
            "voiceType": "chat",
            "source": source or "toolbox",
            "traceid": traceid or str(uuid.uuid4()),
            "chatStatus": chat_status,
            "text": text,
            "language": "AutoChange",
            "seg_index": seg_index,
        }
        if emotion:
            json_msg["emotion"] = emotion
        self.llm_data.AnswerList.put(json_msg)

    def send_stream(self, text: str, source: str = "toolbox", emotion: str = ""):
        """把整段文本按标点切分后逐段送入 TTS（seg_index 递增，最后 end）。

        实现「边合成边播放」的流式效果：与主 LLM 分段逻辑一致，
        weather/news/vision 等工具箱整段回复也走分段，不再整段合成完才播放。
        """
        if not text or not text.strip():
            return
        traceid = str(uuid.uuid4())
        segments = self._split(text.strip(), self._seg_min_len())
        if not segments:
            self.send_to_answer_queue(text.strip(), traceid=traceid,
                                      seg_index=0, chat_status="end", source=source,
                                      emotion=emotion)
            return
        for i, seg in enumerate(segments):
            chat_status = "end" if i == len(segments) - 1 else ""
            self.send_to_answer_queue(seg, traceid=traceid,
                                      seg_index=i, chat_status=chat_status, source=source,
                                      emotion=emotion)

    def is_busy(self) -> bool:
        """检测当前是否有 TTS 说话任务（供弹幕消费调度轮询）。

        - True 表示正在说话/有排队任务，弹幕只进队列不传递；
        - False 表示空闲，可立即消费弹幕队列。
        """
        try:
            from func.tts.tts_core import TTsCore
            return TTsCore().is_busy()
        except Exception:
            self.log.exception("检测 TTS 忙状态失败")
            return False

    def interrupt(self):
        """立即打断当前 TTS 说话并清空排队任务（翻唱等场景立即接管音频输出）。

        打断后立即恢复 TTS 打断标志：这里属于「程序主动打断」而非「用户说话打断」，
        不应让 TTS 停留在打断状态，否则后续报歌名/感想会因 _interrupt_flag 卡死而无法合成。
        """
        try:
            from func.tts.tts_core import TTsCore
            core = TTsCore()
            core._interrupt_playback()
            core._resume_after_interrupt()
        except Exception:
            self.log.exception("打断 TTS 异常")

    def play_audio(self, audio, sr, source="meowsongs",
                   lyric_lines=None, lyric_start_idx=0, lyric_end_idx=None):
        """把预合成音频送入 TTS 播放队列（可打断、后续回复排队），可选携带歌词字幕同步"""
        try:
            from func.tts.tts_core import TTsCore
            TTsCore().play_audio(audio, sr, source=source,
                                 lyric_lines=lyric_lines,
                                 lyric_start_idx=lyric_start_idx,
                                 lyric_end_idx=lyric_end_idx)
        except Exception:
            self.log.exception("toolbox → TTS 播放预合成音频异常")

    def _seg_min_len(self) -> int:
        """读取分段最小长度（config.yml → tts.seg_min_len，缺省 24）"""
        try:
            from func.pipeline.config_reader import ConfigReader
            raw = (ConfigReader().get("tts", {}) or {}).get("seg_min_len", self.DEFAULT_SEG_MIN_LEN)
            return max(0, int(raw))
        except Exception:
            return self.DEFAULT_SEG_MIN_LEN

    @classmethod
    def _split(cls, text: str, min_len: int = None) -> list:
        """按标点切分文本为多个片段（保留标点，过滤空段）

        min_len：片段最小长度（字）。累积长度不足 min_len 时即使遇到标点也不切，
        继续拼到下一句，避免出现「此外。」这类极短片段；末尾不足 min_len 的残留
        并入前一个片段。
        """
        if min_len is None:
            min_len = cls.DEFAULT_SEG_MIN_LEN
        min_len = max(0, int(min_len))
        result = []
        buf = ""
        for ch in text:
            buf += ch
            if ch in cls.SPLIT_CHARS and len(buf.strip()) >= min_len:
                seg = buf.strip()
                if seg:
                    result.append(seg)
                buf = ""
        tail = buf.strip()
        if tail:
            if result and len(tail) < min_len:
                result[-1] = result[-1] + tail
            else:
                result.append(tail)
        return result
