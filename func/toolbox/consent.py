# -*- coding: utf-8 -*-
# func/toolbox/consent.py
# 硬触发裁决：关键字命中后先进入工具触发态，角色按此刻情绪决定办不办，拒绝则掐断本次工具

import json
import re
import threading
import time

from func.log.default_log import DefaultLog
from func.pipeline.id_signup import display_name
from func.tools.singleton_mode import singleton
from func.toolbox.character_voice import clean_line
from func.toolbox.config import TBoxConfig

TOOL_LABELS = {
    "flux_paint": "画一张图",
    "use_vision": "看的屏幕",
    "napcat_send": "用QQ发消息",
}

# 给角色看的中文情绪名（未列出的直接用情绪代码）
EMOTION_LABELS = {
    "happy": "开心", "sad": "难过", "call": "被叫住", "angry": "生气",
    "blush": "害羞", "approve": "认可", "sweat": "尴尬", "blood": "来劲",
    "love": "喜欢", "wordless": "无语",
}
MAX_REFUSE_CHARS = 24
MEM_TYPE = "toolbox_excuse"
_RECENT_LINES = []


@singleton
class TBoxConsent:
    """硬触发前的角色裁决器
    - 命中关键字：先登记「工具触发态」（工具已就位、尚未执行）；
    - 情绪强度不超过阈值（toolbox.consent_intensity）：直接放行（零额外延迟）；
    - 超过阈值：只问角色要不要拒绝（任何情绪都算，不只是生气）；
    - 拒绝：以角色口吻 TTS 播报（绝不静默）并掐断本次工具，工具不启动；
    - 允许（默认）：不开口，交回原链路执行（工具自己会说明）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._armed = {}
        self._lock = threading.Lock()

    # ==================== 主入口 ====================
    def ask(self, tool_name: str, text: str, meowid: str) -> str:
        """进入触发态并请角色裁决；返回拒绝台词（已播报，工具应掐断），空串表示放行"""
        state = self._arm(tool_name, text, meowid)
        if state is None:
            return ""
        try:
            emotion, intensity = self._mood()
            if not self._may_refuse(intensity):
                return ""
            refuse, line = self._judge(tool_name, text, meowid, emotion, intensity)
            if not refuse:
                return ""
            line = clean_line(line, MAX_REFUSE_CHARS)
            if not line:
                self.log.warning("[触发裁决] 角色想拒绝但没说出话，按放行处理（拒绝不许静默）")
                return ""
            return self._refuse(line, text, meowid)
        except Exception:
            self.log.exception("[触发裁决] 裁决异常，按放行处理")
            return ""
        finally:
            self._disarm(state)

    # ==================== 触发态 ====================
    def _arm(self, tool_name: str, text: str, meowid: str):
        """登记工具触发态；这个人已有一次裁决在进行时返回 None（本次直接放行，不重复裁决）"""
        key = meowid or "default"
        state = {"tool": str(tool_name or ""), "text": str(text or ""),
                 "ts": time.time(), "key": key}
        with self._lock:
            if key not in self._armed:
                self._armed[key] = state
                self.log.info(f"[触发裁决] 进入工具触发态 {state['tool']}（{key}）")
                return state
        self.log.info(f"[触发裁决] {key} 已有触发态在裁决，本次不再重复裁决")
        return None

    def _disarm(self, state):
        """清掉触发态（放行/拒绝/异常都要清，否则后续硬触发会被跳过）"""
        if not state:
            return
        with self._lock:
            if self._armed.get(state["key"]) is state:
                self._armed.pop(state["key"], None)

    # ==================== 心情 ====================
    @staticmethod
    def _mood():
        """当前情绪与强度（读取失败按「没事」处理，不因读不到状态而拒绝）"""
        try:
            from func.pipeline.llm_emotion import LLMEmotionBridge
            emotion, intensity = LLMEmotionBridge().get_emotion_with_intensity()
            return str(emotion or "happy"), float(intensity)
        except Exception:
            return "happy", 3.0

    @staticmethod
    def _may_refuse(intensity: float) -> bool:
        """情绪强度超过配置阈值才需要想一下（不看是哪种情绪，生气/开心/难过都可能不肯办）"""
        return float(intensity) > TBoxConfig().consent_intensity

    def _psyche_text(self) -> str:
        """心里正在想的事（供角色判断要不要给这个人办事）"""
        try:
            from func.pipeline.llm_psyche import LLMPsycheBridge
            data = LLMPsycheBridge().get_psyche("main") or {}
            theme = str(data.get("theme") or "").strip()
            content = [str(c).strip() for c in (data.get("content") or []) if str(c).strip()]
            return "；".join(([theme] if theme else []) + content[:4])
        except Exception:
            return ""

    # ==================== 裁决 ====================
    def _judge(self, tool_name, text, meowid, emotion, intensity):
        """只判断要不要拒绝（默认允许），返回 (refuse, 台词)"""
        from func.toolbox.character_voice import TBoxCharacterVoice
        voice = TBoxCharacterVoice()
        system_prompt = voice.system_prompt(meowid, text)
        if not system_prompt:
            return False, ""
        who = display_name(meowid) or "主人"
        label = TOOL_LABELS.get(str(tool_name or ""), f"用「{tool_name}」这个工具")
        mood = EMOTION_LABELS.get(str(emotion or "").lower(), str(emotion or ""))
        psyche = self._psyche_text()
        parts = [
            f"（这是你自己的内部提示，不是{who}说的话）",
            f"{who}刚对你说：「{text}」，想让你{label}。工具已经准备好，就等你点头。",
            f"你此刻的心情：{mood}，强度 {intensity:g}（满分 5）。",
        ]
        if psyche:
            parts.append(f"你心里现在装着的（只当背景，不要说出来）：{psyche}")
        if _RECENT_LINES:
            parts.append("你最近拒绝过：" + " / ".join(_RECENT_LINES[-4:])
                         + "。这次换个口气、换个说法，别一模一样。")
        parts.append(
            "拒绝就像真人闹小情绪：一句短话，不解释、不讲道理、不给替代方案。"
            "可以嫌弃、撒娇、敷衍、懒得理、反问，也可以只说半句；"
            "别复述你心里的事，别汇报，不说系统流程、不说教、不套模板。"
        )
        parts.append(
            "只判断要不要拒绝，生气了或者有想法可以拒绝。默认是允许（allow 占位）；"
            "只输出一行 JSON，不要解释：\n"
            '{"allow": true, "refuse": false, "say": ""}'
        )
        parts.append(
            f"要拒绝时，say 就是你脱口而出的那一句（不超过 {MAX_REFUSE_CHARS} 字），不用交代理由；"
            f"允许时 say 留空。"
        )
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n".join(parts)}]
        return self._parse(voice.chat(messages))

    @staticmethod
    def _parse(raw) -> tuple:
        """只认拒绝：allow 占位为 true 或解析失败一律放行（拒绝不许静默）"""
        body = str(raw or "").strip()
        match = re.search(r"\{[\s\S]*\}", body)
        if not match:
            return False, ""
        try:
            data = json.loads(match.group(0), strict=False)
        except Exception:
            return False, ""
        if not isinstance(data, dict):
            return False, ""
        if data.get("allow") is True:
            return False, ""
        return data.get("refuse") is True, str(data.get("say") or "").strip()

    # ==================== 拒绝 ====================
    def _refuse(self, line: str, text: str, meowid: str) -> str:
        """拒绝：TTS 播报 + 记入短期记忆 + 掐断本次工具"""
        self.log.info(f"[触发裁决] 角色拒绝执行：{line}")
        self._speak(line)
        self._save_memory(text, line)
        _RECENT_LINES.append(line)
        del _RECENT_LINES[:-6]
        return line

    @staticmethod
    def _speak(text: str):
        """以角色声音说出来（toolbox 分段流式，绝不静默）"""
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(text, source="toolbox_consent")
        except Exception:
            DefaultLog().getLogger().exception("[触发裁决] 拒绝台词播报失败")

    def _save_memory(self, text: str, line: str):
        """把这次「请求 + 拒绝」写进短期记忆，下一轮角色自己记得刚才没答应"""
        try:
            from func.pipeline.short_memory import ShortMemory
            sm = ShortMemory()
            sm.save({"role": "user", "content": str(text or ""), "type": MEM_TYPE}, 0)
            sm.save({"role": "assistant", "content": str(line or ""), "type": MEM_TYPE}, 0)
        except Exception:
            self.log.exception("[触发裁决] 记录拒绝台词失败")
