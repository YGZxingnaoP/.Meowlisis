# -*- coding: utf-8 -*-
# func/toolbox/meowvision/watching/vision_loop.py
# Watching 循环：长期观察屏幕 → 按间隔截屏 → 变化检测 → 视觉评价 → 记忆 → TTS → 结束通知

import os
import time
import uuid
import threading
from typing import Dict, Optional

from PIL import ImageGrab

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.pipeline.short_memory import ShortMemory
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.toolbox.meowvision.watching.config import TBWatchingConfig
from func.toolbox.meowvision.watching.window import TBWindowList
from func.toolbox.meowvision.image_handle.diff import TBImageDiff
from func.toolbox.meowvision.sender import TBVisionSender
from func.toolbox.meowvision.get_response import TBVisionGetResponse


@singleton
class TBWatchingLoop:
    """Watching 循环：后台线程按 AI 决定的配置周期截屏并交视觉模型评价。

    - 与游戏窗口强绑定，窗口消失（5秒确认）立即强制结束；
    - 时间到自然结束；
    - 变化检测开启时，画面无变化则本轮不传视觉模型、不回复；
    - 仅 assistant 回复写短期记忆（type=toolbox_watching）与长期记忆；
    - 回复经正则清理（去 think / 去括号）后送 TTS（source=toolbox_watching）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBWatchingConfig()
        self.window_list = TBWindowList()
        self.diff = TBImageDiff()
        self.sender = TBVisionSender()
        self.short_memory = ShortMemory()
        self.ltmem = MeowLLMLtMemBridge()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ==================== 生命周期 ====================
    def is_running(self) -> bool:
        return self._running

    def start(self, config: dict) -> bool:
        """启动循环（后台线程）。返回是否成功启动。"""
        hwnd = config.get("hwnd")
        if not hwnd or not self.window_list.is_window_alive(hwnd):
            self.log.warning("[Watching] 窗口不存在，无法启动循环")
            return False
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._thread = threading.Thread(target=self._run, args=(config,), daemon=True)
            self._thread.start()
        return True

    def stop(self):
        """外部停止（供新循环替换旧循环）"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    # ==================== 主循环 ====================
    def _run(self, config: dict):
        try:
            self._loop(config)
        except Exception:
            self.log.exception("[Watching] 循环异常")
        finally:
            self._running = False
            self.config.clear_session()

    def _loop(self, config: dict):
        hwnd = int(config.get("hwnd"))
        interval = int(config.get("interval", 30))
        duration = int(config.get("duration", 1800))
        need_change_check = bool(config.get("need_change_check"))

        start_time = time.time()
        prev_path: Optional[str] = None

        self.log.info(f"[Watching] 循环开始：窗口={config.get('window_title')}，"
                      f"间隔={interval}s，时长={duration}s，变化检测={need_change_check}")

        while self._running:
            # 1. 窗口存活检测（消失则5秒确认后强制结束）
            if not self._check_window_alive(hwnd):
                self._finish(config, reason="window_gone")
                return

            # 2. 时间到 → 自然结束
            if time.time() - start_time >= duration:
                self._finish(config, reason="timeout")
                return

            # 3. 截屏
            img_path = self._capture(config)
            if not img_path:
                time.sleep(interval)
                continue

            # 4. 变化检测（开启时，无变化则跳过本轮）
            if need_change_check and prev_path:
                if not self.diff.has_change(prev_path, img_path):
                    self.log.info("[Watching] 画面无变化，本轮跳过视觉分析")
                    prev_path = img_path
                    self._wait(interval)
                    continue
            prev_path = img_path

            # 5. 视觉评价
            reply = self._analyze(config, img_path)
            if reply:
                # 6. 写记忆 + TTS
                self._save_memory(config, reply)
                self._speak(reply)

            # 7. 等待下个间隔
            self._wait(interval)

    # ==================== 窗口检测 ====================
    def _check_window_alive(self, hwnd: int) -> bool:
        """窗口存活检测：立即查一次，失败则连续 5 秒确认后才判定消失"""
        if self.window_list.is_window_alive(hwnd):
            return True
        confirm = max(1, int(self.config.window_gone_confirm_seconds))
        deadline = time.time() + confirm
        while time.time() < deadline:
            if not self._running:
                return False
            if self.window_list.is_window_alive(hwnd):
                return True
            time.sleep(1)
        return False

    def _wait(self, seconds: int):
        """分片等待，便于 stop 及时生效"""
        seconds = max(1, int(seconds))
        end = time.time() + seconds
        while self._running and time.time() < end:
            time.sleep(min(1, max(0.1, end - time.time())))

    # ==================== 截屏 ====================
    def _capture(self, config: dict) -> Optional[str]:
        try:
            region_type = str(config.get("region_type") or "fullscreen")
            bbox = config.get("bbox")
            if region_type == "bbox" and bbox:
                img = ImageGrab.grab(bbox=tuple(int(v) for v in bbox[:4]))
            else:
                img = ImageGrab.grab()
            os.makedirs(self.config.cache_dir, exist_ok=True)
            name = f"watching_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
            path = os.path.join(self.config.cache_dir, name)
            img.save(path, "PNG")
            return os.path.abspath(path)
        except Exception:
            self.log.exception("[Watching] 截屏失败")
            return None

    # ==================== 视觉评价 ====================
    def _analyze(self, config: dict, img_path: str) -> str:
        username = config.get("username", "")
        instruction = config.get("user_instruction", "")
        front_note = config.get("front_note", "")

        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            system_prompt = SystemPromptBridge().get_watching_prompt(
                username, instruction, front_note
            )
        except Exception:
            self.log.exception("[Watching] 获取 watching 提示词失败")
            system_prompt = ""

        history = self.short_memory.load()
        user_msg = "看看现在屏幕上的画面，以你的角色身份自然评价、吐槽或赞扬一下"
        resp = self.sender.send([img_path], user_msg, system_prompt, history)
        if not resp:
            return ""
        # 非流式：从响应对象取 content（watching 场景不带 tools，模型直接输出文字）
        content = ""
        try:
            if getattr(resp, "choices", None):
                content = resp.choices[0].message.content or ""
        except Exception:
            self.log.exception("[Watching] 解析视觉响应失败")
            return ""
        reply = TBVisionGetResponse.clean(content)
        return (reply or "").strip()

    # ==================== 记忆 / TTS / 结束 ====================
    def _save_memory(self, config: dict, reply: str):
        """仅 assistant 回复写短期记忆与长期记忆"""
        try:
            from func.toolbox.meowvision.vision_core import TBVisionCore
            max_rounds = TBVisionCore()._max_rounds()
        except Exception:
            max_rounds = 30
        try:
            self.short_memory.save(
                {"role": "assistant", "content": reply, "type": "toolbox_watching"},
                max_rounds,
            )
        except Exception:
            self.log.exception("[Watching] 写短期记忆失败")
        try:
            from func.config.app_config import AppConfig
            self.ltmem.record_ai_message(
                config.get("username", ""), AppConfig().ai_name, reply
            )
        except Exception:
            self.log.exception("[Watching] 写长期记忆失败")

    def _speak(self, reply: str):
        """回复送 TTS，标注来源 toolbox_watching（分段流式）"""
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(reply, source="toolbox_watching")
        except Exception:
            self.log.exception("[Watching] TTS 发送失败")

    def _finish(self, config: dict, reason: str):
        """结束循环：用 LLM 自然生成结束语并送 TTS（不写任何记忆）"""
        self.log.info(f"[Watching] 循环结束，原因: {reason}")
        username = config.get("username", "")
        # 触发提示：交给 LLM 以角色身份自然回应（非硬编码）
        if reason == "window_gone":
            prompt = "游戏窗口关掉了，游戏结束了"
        else:
            prompt = "你已经陪我看屏幕看了好久了，是不是看腻了不想看了"
        reply = self._generate_finish_reply(prompt, username)
        if reply:
            self._speak(reply)

    def _generate_finish_reply(self, prompt: str, username: str) -> str:
        """用 toolbox LLM + 角色提示词生成自然结束语（不写记忆，仅 TTS）"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            system_prompt = SystemPromptBridge().get_system_prompt(username, prompt)
        except Exception:
            self.log.exception("[Watching] 获取结束提示词失败")
            system_prompt = ""
        llm = self._llm()
        if llm is None or not llm.client:
            self.log.warning("[Watching] LLM 不可用，结束语回退原文")
            return prompt
        try:
            resp = llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ])
            if not resp or not resp.choices:
                return prompt
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                return prompt
            return TBVisionGetResponse.clean(content)
        except Exception:
            self.log.exception("[Watching] 生成结束语失败")
            return prompt

    @staticmethod
    def _llm():
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(cfg)
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
