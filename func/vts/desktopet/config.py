# -*- coding: utf-8 -*-
# func/vts/desktopet/config.py
# 桌宠控制配置项统一管理
# 读取 config.yml 的 desktopet_emote 节点，字段结构与 emote（VTS）一致，端口默认 8002。

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class DesktopetConfig:
    """集中管理 desktopet_emote 节点下桌宠连接参数与默认值"""

    # 情绪强度分档阈值：intensity < 3 为 weak，>= 3 为 strong（固定）
    EMOTION_INTENSITY_SPLIT = 3

    # 情绪种类（与 LLM 模块 EmotionController.EMOTIONS 保持一致）
    EMOTIONS = ["happy", "sad", "call", "angry", "blush", "approve", "sweat", "blood", "love", "wordless"]

    def __init__(self):
        cfg = ConfigReader().get('desktopet_emote', {})

        # ========== 连接与开关（字段名与 VTS 保持一致） ==========
        self.switch = cfg.get('switch', False)

        # 桌宠 WebSocket 地址（桌宠默认 8002，与真 VTS 8001 区分）
        self.vtuber_websocket = cfg.get('vtuber_websocket', '127.0.0.1:8002')

        self.vtuber_pluginName = cfg.get('vtuber_pluginName', '')

        self.vtuber_pluginDeveloper = cfg.get('vtuber_pluginDeveloper', '')

        self.vtuber_authenticationToken = cfg.get('vtuber_authenticationToken', '')

        # ========== 情绪表情槽位映射 ==========
        self.emotion_slots = cfg.get('emotion_slots', {}) or {}

        # ========== 身体摆动 ==========
        sway = cfg.get('body_sway', {}) or {}
        self.body_sway_enabled = sway.get('enabled', True)
        self.body_sway_parameter = sway.get('parameter', 'FaceAngleX')
        self.body_sway_base = float(sway.get('base', 0.0))
        self.body_sway_amplitude = float(sway.get('amplitude', 0.18))
        self.body_sway_jump_amplitude = float(sway.get('jump_amplitude', 0.6))
        self.body_sway_jump_probability = float(sway.get('jump_probability', 0.2))
        self.body_sway_interval_ms = int(sway.get('interval_ms', 100))

        # ========== 嘴部同步 ==========
        mouth = cfg.get('mouth_sync', {}) or {}
        self.mouth_sync_enabled = mouth.get('enabled', True)
        self.mouth_sync_parameter = mouth.get('parameter', 'MouthOpen')
        self.mouth_sync_min = float(mouth.get('min', 0.25))
        self.mouth_sync_max = float(mouth.get('max', 1.0))
        self.mouth_sync_close = float(mouth.get('close', 0.0))
        self.mouth_sync_interval_ms = int(mouth.get('interval_ms', 90))

    # ==================== 情绪槽位解析 ====================
    def resolve_hotkey(self, emotion: str, intensity: float) -> str:
        """根据情绪与强度解析出桌宠热键ID。

        - 强度分档固定：< 3 → weak，>= 3 → strong；
        - 缺省依次回退：同情绪 strong → 同情绪 weak → happy_weak；
        - 所有映射均为空时返回空字符串（由调用方跳过发送）。
        """
        emotion = str(emotion or "happy").lower()
        if emotion not in self.EMOTIONS:
            emotion = "happy"
        try:
            intensity = float(intensity)
        except Exception:
            intensity = 3.0
        tier = "strong" if intensity >= self.EMOTION_INTENSITY_SPLIT else "weak"

        slots = self.emotion_slots
        if not slots:
            return ""
        key = f"{emotion}_{tier}"
        fallback_weak = f"{emotion}_weak"
        fallback_strong = f"{emotion}_strong"
        for candidate in (key, fallback_strong, fallback_weak, "happy_weak"):
            val = slots.get(candidate)
            if val:
                return str(val)
        return ""
