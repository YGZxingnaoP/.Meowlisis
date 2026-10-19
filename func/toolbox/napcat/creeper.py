# -*- coding: utf-8 -*-
# func/toolbox/napcat/creeper.py
# Creeper 歌词接龙彩蛋（QQ 私聊/群聊共用）

import threading
import time
import unicodedata
from typing import List, Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

SEGMENTS = [
    "Creeper",
    "Aw man",
    "So we back in the mine",
    "Got our pickaxe swinging from",
    "Side to side",
    "Side-side to side",
    "This task a grueling one",
    "Hope to find some diamonds to",
    "Night, night, night",
    "Diamonds tonight",
    "Heads up",
    "You hear a sound",
    "Turn around and look up",
    "Total shock fills your body",
    "Oh no, it's you again",
    "I can never forget those eyes",
    "Eyes, eyes, eyes",
    "Cause baby tonight",
    "The creeper's trying to steal all our stuff again",
    "Cause baby tonight",
    "You grab your pick, shovel and bolt again",
    "And run, run until it's done",
    "Until the sun comes up",
    "In the morn'",
]

_NORM = [("".join(c for c in unicodedata.normalize("NFKC", s).lower()
                  if "a" <= c <= "z")) for s in SEGMENTS]

STATE_TTL = 600
PARTIAL_RATIO = 0.5
TRIGGER_PUNCT = "!?！？"


def _norm(text) -> str:
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    return "".join(c for c in s if "a" <= c <= "z")


@singleton
class TBCreeper:
    """Creeper 接龙：触发后逐段接歌词，接不上即结束"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._states = {}
        self._lock = threading.Lock()

    def _clear(self, key: str):
        with self._lock:
            self._states.pop(key, None)

    @staticmethod
    def _deco(text: str) -> str:
        return f"{text} 🎵"

    @staticmethod
    def _is_trigger(text: str) -> bool:
        """首句必须是 Creeper! 或 Creeper?，中文不触发"""
        if _norm(text) != "creeper":
            return False
        return any(c in str(text or "") for c in TRIGGER_PUNCT)

    @staticmethod
    def _consume(norm_text: str, idx: int) -> int:
        """从 idx 起消费用户已唱的段，返回消费段数"""
        rest = norm_text
        if not rest:
            return 0
        # 整句等于某一段时先精确定位，避免被更短的段包含（如 Side to side 之于 Side-side to side）
        for j in range(idx, len(_NORM)):
            if _NORM[j] and rest == _NORM[j]:
                return j - idx + 1
        consumed = 0
        while idx + consumed < len(_NORM):
            seg = _NORM[idx + consumed]
            pos = rest.find(seg)
            if pos < 0:
                break
            rest = rest[pos + len(seg):]
            consumed += 1
        if consumed:
            return consumed
        # 只唱了半段
        seg = _NORM[idx]
        if seg and seg.startswith(norm_text) and len(norm_text) >= len(seg) * PARTIAL_RATIO:
            return 1
        # 跳到后面的段
        for j in range(idx + 1, len(_NORM)):
            if _NORM[j] and _NORM[j] in norm_text:
                return j - idx + 1
        return 0

    def _quip(self, speaker: str, qq_id: str) -> str:
        """收官吐槽：把接龙信息交给 AI，附带'完成了默契配合'的系统提示"""
        name = str(speaker or "对方")
        note = (
            f"\n\n## 刚刚发生的事\n"
            f"你刚刚和{name}完成了默契配合：一起把《Revenge》的歌词一句一句接完了，"
            f"最后收在 \"{SEGMENTS[-1]}\"。现在说一句收官的话，短一点，别解释这是彩蛋。"
        )
        try:
            from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM
            llm = TBNapCatLLM()
            system = llm._system_prompt(name, "刚刚接完了歌词", qq_id) + note
            text = llm.reply_stream(system, [{"role": "user", "content": "（接完了）"}])
            text = str(text or "").strip()
            if text:
                return text
        except Exception:
            self.log.exception("Creeper 收官吐槽生成失败")
        return f"配合得挺齐，{name}。"

    def route(self, text: str, key: str, speaker: str = "",
              qq_id: str = "", allow_trigger: bool = True) -> Optional[List[str]]:
        """返回要发送的文本列表；None 表示不接管"""
        body = str(text or "").strip()
        if not body:
            return None

        norm_text = _norm(body)
        replies: List[str] = []
        finished = False
        with self._lock:
            now = time.time()
            if len(self._states) > 200:
                for k in [k for k, v in self._states.items()
                          if now - v.get("ts", 0) > STATE_TTL]:
                    self._states.pop(k, None)
            st = self._states.get(key)
            if st and now - st.get("ts", 0) > STATE_TTL:
                self._states.pop(key, None)
                st = None
            if self._is_trigger(body):
                # 未 @ 时不起头，也不动已有状态
                if not allow_trigger:
                    return None
                self._states[key] = {"idx": 2, "ts": now}
                replies.append(self._deco(SEGMENTS[1]))
            elif not st:
                return None
            else:
                idx = max(0, min(int(st.get("idx") or 0), len(SEGMENTS)))
                consumed = self._consume(norm_text, idx)
                if consumed <= 0:
                    self._states.pop(key, None)
                    self.log.info(f"[Creeper] 接龙中断: {body[:30]}")
                    return None
                bot_idx = idx + consumed
                nxt = bot_idx
                if bot_idx < len(SEGMENTS):
                    replies.append(self._deco(SEGMENTS[bot_idx]))
                    nxt = bot_idx + 1
                if nxt >= len(SEGMENTS):
                    self._states.pop(key, None)
                    finished = True
                    self.log.info("[Creeper] 接龙完成")
                else:
                    self._states[key] = {"idx": nxt, "ts": now}
        if finished:
            replies.append(self._deco(self._quip(speaker, qq_id)))
        return replies or None
