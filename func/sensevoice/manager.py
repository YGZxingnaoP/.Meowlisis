# -*- coding: utf-8 -*-
# func/sensevoice/manager.py
# 统一负责接收服务端消息与发送音频/控制信号/识别结果

import asyncio
import json
import re
import time

import aiohttp


class SenseVoiceManager:
    """统一收发：发音频帧、发控制信号、收识别结果并送 LLM"""

    def __init__(self, config, port, log, callback=None):
        self.config = config
        self.port = port
        self.log = log
        self.callback = callback

        from func.config.app_config import AppConfig
        self.api_base = f"http://127.0.0.1:{AppConfig().port}"

        self._speaking = False
        self.streaming_text = ""
        self.stream_last_update = 0
        self.pending_tasks = {}
        self.pending_texts = {}

    async def send_config(self):
        """发送 SenseVoice 启动配置"""
        cfg = {
            "wav_name": "mic",
            "is_speaking": self._speaking,
            "language": self.config.language,
            "itn": self.config.itn,
            "mode": self.config.mode,
        }

        hotwords_dict = self._parse_hotwords(self.config.hotwords)
        if hotwords_dict:
            cfg["hotwords"] = json.dumps(hotwords_dict, ensure_ascii=False)

        await self.port.send_json(cfg)
        self.log.info(f"✅ 发送启动配置: language={self.config.language}, mode={self.config.mode}, itn={self.config.itn}")
        self.log.info(f"   热词: {list(hotwords_dict.keys())}")
        self.log.info(f"   目标说话人: {self.config.target_speakers}")

    def _parse_hotwords(self, hotwords) -> dict:
        """解析热词列表为字典形式"""
        hotwords_dict = {}
        for hw in hotwords:
            parts = hw.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                hotwords_dict[' '.join(parts[:-1])] = int(parts[-1])
        return hotwords_dict

    async def send_audio(self, data: bytes):
        """发送一帧音频数据到服务端"""
        await self.port.send_bytes(data)

    async def send_speaking(self, speaking: bool):
        """发送说话状态控制信号"""
        self._speaking = speaking
        await self.port.send_json({"is_speaking": speaking})

    async def receive_loop(self):
        """接收并处理服务端消息"""
        msg_count = 0
        async for message in self.port:
            msg_count += 1
            if msg_count % 50 == 0:
                self.log.debug(f"已接收 {msg_count} 条消息")
            await self._handle_message(message, msg_count)

    async def _handle_message(self, message, msg_count: int):
        """解析单条服务端消息并分流处理"""
        if isinstance(message, bytes):
            # 二进制数据（通常是音频反馈），忽略
            return

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            self.log.warning(f"收到非 JSON 消息: {message[:100]}")
            return

        if msg_count <= 3 or data.get("is_final") or "offline" in data.get("mode", ""):
            self.log.info(f"📨 收到服务器消息 [{msg_count}]: {data}")
        else:
            self.log.debug(f"收到服务器消息 [{msg_count}]: {data}")

        text = data.get("text", "")
        is_final = data.get("is_final", False)
        mode = data.get("mode", "")

        # 清理 SenseVoice 输出的特殊标签
        if text:
            text = re.sub(r'<\|.*?\|>', '', text).strip()

        if text and "online" in mode and not is_final:
            # 流式中间结果：仅记录，不发送给 LLM
            self.log.info(f"🔄 流式识别: {text}")
            self.streaming_text = text
            self.stream_last_update = time.time()
        elif text and ("offline" in mode or is_final):
            # 最终结果：进入说话人验证与断句合并
            self.log.info(f"✅ 识别到最终文本: {text} (mode={mode}, is_final={is_final})")
            spk_name = data.get("spk_name", "未知")
            spk_score = data.get("spk_score", 0.0)
            self.log.info(f"   说话人: {spk_name}, 置信度: {spk_score:.3f}")
            await self._handle_result(text, spk_name, spk_score)

    async def _handle_result(self, text: str, spk_name: str, spk_score: float):
        """说话人验证并按说话人合并断句"""
        if not text.strip():
            self.log.warning("⚠️ 收到空文本，忽略")
            return

        if spk_name not in self.config.target_speakers:
            self.log.warning(f"⚠️ 说话人 '{spk_name}' 不在目标列表中 {self.config.target_speakers}，忽略")
            return

        if spk_score < self.config.speaker_threshold:
            self.log.warning(f"⚠️ 说话人 '{spk_name}' 置信度 {spk_score:.3f} < 阈值 {self.config.speaker_threshold}，忽略")
            return

        self.log.info(f"✅ 通过说话人验证: {spk_name} (score={spk_score:.3f})")

        key = spk_name
        # 取消旧任务并立即移除，防止旧 finally 误删新任务
        old_task = self.pending_tasks.pop(key, None)
        if old_task and not old_task.done():
            old_task.cancel()

        if key in self.pending_texts:
            self.pending_texts[key] = self.pending_texts[key] + " " + text
        else:
            self.pending_texts[key] = text

        task = asyncio.create_task(self._delayed_send(key))
        self.pending_tasks[key] = task

    async def _delayed_send(self, key: str):
        """延迟合并断句后发送到 LLM"""
        try:
            await asyncio.sleep(self.config.merge_delay)
            full_text = self.pending_texts.pop(key, "").strip()
            if full_text:
                await self._send_to_llm(full_text, key)
        except asyncio.CancelledError:
            pass
        finally:
            # 仅当当前任务仍是该 key 的最新任务时才移除
            if self.pending_tasks.get(key) is asyncio.current_task():
                self.pending_tasks.pop(key, None)

    async def _send_to_llm(self, text: str, username: str):
        """发送识别文本到 LLM"""
        if self.callback:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.callback, text, username)
            return

        url = f"{self.api_base}/msg"
        payload = {"msg": text, "username": username}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        self.log.info(f"已送入 AI 核心: {text[:30]}... (说话人: {username})")
                    else:
                        self.log.error(f"发送失败: {resp.status}")
        except Exception as e:
            self.log.error(f"HTTP 异常: {e}")
