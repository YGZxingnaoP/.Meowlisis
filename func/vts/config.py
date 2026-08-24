# -*- coding: utf-8 -*-
# func/vts/config.py
# VTS（VTube Studio）配置项统一管理
# 注意：为兼容历史配置，仍读取 config.yml 的 emote 节点，字段名保持原名不变。

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class VtsConfig:
    """集中管理 emote 节点下 VTube Studio 连接参数与默认值"""

    # 情绪强度分档阈值：intensity < 3 为 weak，>= 3 为 strong（固定）
    EMOTION_INTENSITY_SPLIT = 3

    # 情绪种类（与 LLM 模块 EmotionController.EMOTIONS 保持一致）
    EMOTIONS = ["happy", "sad", "call", "angry", "blush", "approve", "sweat", "blood", "love", "wordless"]

    def __init__(self):
        cfg = ConfigReader().get('emote', {})

        # ========== 连接与开关（字段名保留历史） ==========
        # 是否启用 VTube Studio 控制
        self.switch = cfg.get('switch', False)

        # VTube Studio WebSocket 地址
        self.vtuber_websocket = cfg.get('vtuber_websocket', '127.0.0.1:8001')

        # 插件名（与 VTS 授权信息保持一致）
        self.vtuber_pluginName = cfg.get('vtuber_pluginName', '')

        # 插件开发者
        self.vtuber_pluginDeveloper = cfg.get('vtuber_pluginDeveloper', '')

        # VTS 认证 token
        self.vtuber_authenticationToken = cfg.get('vtuber_authenticationToken', '')

        # ========== 情绪表情槽位映射 ==========
        # 槽位 id（{emotion}_{weak|strong}）→ VTS hotkeyID
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

        # ========== 置顶透明窗口 ==========
        win = cfg.get('window', {}) or {}
        self.window_enabled = win.get('enabled', False)
        self.window_always_on_top = win.get('always_on_top', True)
        self.window_width = int(win.get('width', 400))
        self.window_height = int(win.get('height', 600))
        self.window_x = int(win.get('x', 0))
        self.window_y = int(win.get('y', 0))
        self.window_green = win.get('green', '#00FF00')
        self.window_tolerance = int(win.get('tolerance', 40))
        self.window_fps = int(win.get('fps', 30))
        # 屏幕采集的显示器编号（mss.monitors 索引：1=主显示器，0=整个虚拟屏）
        self.window_monitor = int(win.get('monitor', 1) or 1)

    # ==================== 情绪槽位解析 ====================
    def resolve_hotkey(self, emotion: str, intensity: float) -> str:
        """根据情绪与强度解析出 VTS hotkeyID。

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
