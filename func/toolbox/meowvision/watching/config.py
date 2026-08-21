# -*- coding: utf-8 -*-
# func/toolbox/meowvision/watching/config.py
# Watching（长期观察屏幕）配置：默认值 + 运行时会话落盘到 .temp

import json
import os
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class TBWatchingConfig:
    """Watching 配置管理：集中默认值，负责把 AI 决定的会话配置落盘到 .temp。

    - 运行时配置（间隔/区域/时长/窗口等）由 start_tool 收集后 save_session 落盘；
    - vision_loop 通过 load_session 读取，clear_session 清空。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        # 会话配置文件：项目根目录 .temp 内
        self.session_path = os.path.join(".temp", "watching_session.json")
        self._lock = threading.Lock()

        # ========== 从 config.yml 读取 watching 配置 ==========
        cfg = self._load_watching_cfg()
        # watching 总开关（关闭时 vision_core 不进入长期观察流程）
        self.enabled = bool(cfg.get("enabled", True))
        # 截屏频率（秒）：20 ~ 120
        self.min_interval = int(cfg.get("min_interval", 20))
        self.max_interval = int(cfg.get("max_interval", 120))
        # 持续时间（秒）：30分钟 ~ 5小时
        self.min_duration = int(cfg.get("min_duration", 30 * 60))
        self.max_duration = int(cfg.get("max_duration", 5 * 60 * 60))
        # 变化检测相似度阈值：两帧相似度 >= 该值判定为"无变化"
        self.change_similarity_threshold = float(cfg.get("change_similarity_threshold", 0.85))
        # 窗口消失确认检测：连续多少秒未检测到窗口才判定消失
        self.window_gone_confirm_seconds = int(cfg.get("window_gone_confirm_seconds", 5))

        # 截图缓存目录（复用 meowvision 的缓存目录）
        try:
            from func.toolbox.meowvision.config import TBVisionConfig
            self.cache_dir = TBVisionConfig().cache_dir
        except Exception:
            self.cache_dir = os.path.join(".temp", "vision_cache")

    @staticmethod
    def _load_watching_cfg() -> dict:
        """从 config.yml 的 meowvision.watching 节点读取配置"""
        try:
            from func.pipeline.config_reader import ConfigReader
            meow = ConfigReader().get("meowvision", {}) or {}
            w = meow.get("watching") or {}
            return w if isinstance(w, dict) else {}
        except Exception:
            return {}

    # ==================== 会话落盘 ====================
    def save_session(self, config: dict):
        """保存当前 watching 会话配置到 .temp/watching_session.json"""
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.session_path), exist_ok=True)
                with open(self.session_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                self.log.info(f"[Watching] 会话配置已落盘: {self.session_path}")
            except Exception:
                self.log.exception("[Watching] 保存会话配置失败")

    def load_session(self) -> dict:
        """读取当前 watching 会话配置（不存在返回空 dict）"""
        with self._lock:
            try:
                if not os.path.exists(self.session_path):
                    return {}
                with open(self.session_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except Exception:
                self.log.exception("[Watching] 读取会话配置失败")
                return {}

    def clear_session(self):
        """清空会话配置（循环结束或失败时调用）"""
        with self._lock:
            try:
                if os.path.exists(self.session_path):
                    os.remove(self.session_path)
            except Exception:
                self.log.exception("[Watching] 清空会话配置失败")

    # ==================== 参数边界钳制 ====================
    def clamp_interval(self, value) -> int:
        try:
            v = int(value)
        except (TypeError, ValueError):
            v = 30
        return max(self.min_interval, min(self.max_interval, v))

    def clamp_duration(self, value) -> int:
        try:
            v = int(value)
        except (TypeError, ValueError):
            v = 30 * 60
        return max(self.min_duration, min(self.max_duration, v))
