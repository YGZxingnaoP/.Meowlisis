# -*- coding: utf-8 -*-
# func/funasr/sensevoice.py
# SenseVoice WebSocket 客户端（高精度流式识别 + 声纹 + 打断）

import asyncio
import threading
import json
import pyaudio
import websockets
import numpy as np
import time
import re
from typing import Optional, Callable

from func.log.default_log import DefaultLog
from func.config.default_config import defaultConfig


class SenseVoiceCore:
    """SenseVoice WebSocket 客户端核心类，接口与 FunASRCore 保持一致"""

    def __init__(self, callback: Optional[Callable[[str, str, str], None]] = None):
        self.log = DefaultLog().getLogger()
        full_config = defaultConfig().get_config()
        self.sv_config = full_config.get('sensevoice', {})
        self.enabled = self.sv_config.get('enabled', False)
        if not self.enabled:
            return

        self.server_url = self.sv_config.get('server_url', 'ws://127.0.0.1:10095/')
        self.mode = self.sv_config.get('mode', '2pass')
        self.hotwords = self.sv_config.get('hotwords', [])
        self.username = self.sv_config.get('username', '访客')
        self.uid = self.sv_config.get('uid', 'sensevoice_user')
        self.energy_threshold = self.sv_config.get('energy_threshold', 500)
        self.power_save_enabled = self.sv_config.get('power_save_enabled', False)
        self.power_save_silence_seconds = self.sv_config.get('power_save_silence_seconds', 2)
        self.power_save_check_interval = self.sv_config.get('power_save_check_interval', 0.5)
        self.vad_energy_threshold = self.sv_config.get('vad_energy_threshold', 220)
        self.merge_delay = self.sv_config.get('merge_delay', 1.5)
        self.target_speakers = self.sv_config.get('target_speakers', ['YGZ醒脑片'])
        self.speaker_threshold = self.sv_config.get('speaker_threshold', 0.2)
        self.silence_threshold = self.sv_config.get('silence_threshold', 2.0)

        # 打断功能配置
        self.interrupt_enabled = self.sv_config.get('interrupt_enabled', True)
        self.interrupt_energy_threshold = self.sv_config.get('interrupt_energy_threshold', 1200)
        self.interrupt_cooldown = self.sv_config.get('interrupt_cooldown', 1.0)
        self._last_interrupt_time = 0
        self.tts_core = None

        # 音频参数（SenseVoice 推荐使用 200ms 分块保证高精度）
        chunk_ms = self.sv_config.get('chunk_size_ms', 200)
        self.CHUNK = int(16000 * chunk_ms / 1000)   # 200ms = 3200 samples
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 16000

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.callback = callback

        # AI 核心接口
        from func.gobal.data import CommonData
        self.commonData = CommonData()
        self.api_base = f"http://127.0.0.1:{self.commonData.port}"

        # 句子合并延迟发送
        self.merge_timeout = self.sv_config.get('merge_timeout', 0.5)
        self.pending_tasks = {}
        self.pending_texts = {}

        # 空闲模式状态
        self.idle_mode = False
        self.consecutive_silent = 0
        self.frame_counter = 0
        self.total_frames = 0
        self.speech_frames = 0
        self.last_log_time = time.time()
        self.idle_silence_frames = float('inf')
        self.idle_send_interval = 0

        # 说话状态控制
        self.speaking = True
        self.silence_start_time = None

        # 语言及标点配置
        self.language = self.sv_config.get('language', 'auto')
        self.itn = self.sv_config.get('itn', True)

        self.streaming_text = ""
        self.stream_last_update = 0
        self.stream_final_timeout = 1.0

    def set_tts_core(self, tts_core):
        self.tts_core = tts_core
        self.log.info("SenseVoice 已设置 TTS 核心引用，打断功能就绪")

    def _do_interrupt(self):
        if self.tts_core:
            try:
                self.tts_core.stop_all()
                self.log.info("TTS 已彻底清除（播放+合成+队列+文件）")
            except Exception as e:
                self.log.error(f"打断TTS时出错: {e}")

    def start(self):
        if not self.enabled:
            self.log.info("SenseVoice 未启用")
            return
        if self.thread and self.thread.is_alive():
            self.log.warning("SenseVoice 已在运行")
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        self.log.info("SenseVoice 识别线程已启动")

    def stop(self):
        self.running = False
        for task in self.pending_tasks.values():
            task.cancel()
        self.pending_tasks.clear()
        self.pending_texts.clear()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=5)
        self.log.info("SenseVoice 识别线程已停止")

    def _run_async_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:
            self.log.error(f"SenseVoice 主协程异常: {e}")
        finally:
            self.loop.close()

    async def _main(self):
        while self.running:
            try:
                async with websockets.connect(
                    self.server_url,
                    subprotocols=["binary"],
                    ping_interval=60,
                    ping_timeout=30
                ) as ws:
                    self.log.info(f"已连接到 SenseVoice 服务器 {self.server_url}")
                    await self._send_config(ws)
                    capture_task = asyncio.create_task(self._audio_capture(ws))
                    recv_task = asyncio.create_task(self._message_receiver(ws))
                    done, pending = await asyncio.wait(
                        [capture_task, recv_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()
                    if self.running:
                        await asyncio.sleep(1)
            except Exception as e:
                if self.running:
                    self.log.error(f"SenseVoice 连接异常: {e}，1秒后重连")
                    await asyncio.sleep(1)
                else:
                    break

    async def _send_config(self, ws):
        """发送 SenseVoice 所需配置"""
        config = {
            "wav_name": "mic",
            "is_speaking": self.speaking,
            "language": self.language,
            "itn": self.itn,
            "mode": self.mode,
        }
        if self.hotwords:
            hotwords_dict = {}
            for hw in self.hotwords:
                parts = hw.split()
                if len(parts) >= 2 and parts[-1].isdigit():
                    hotwords_dict[' '.join(parts[:-1])] = int(parts[-1])
            if hotwords_dict:
                config["hotwords"] = json.dumps(hotwords_dict, ensure_ascii=False)
        
        await ws.send(json.dumps(config))
        self.log.info(f"✅ 发送启动配置: language={self.language}, mode={self.mode}, itn={self.itn}")
        self.log.info(f"   热词: {list(hotwords_dict.keys()) if hotwords_dict else '无'}")
        self.log.info(f"   目标说话人: {self.target_speakers}")

    async def _audio_capture(self, ws):
        """音频采集与发送"""
        p = pyaudio.PyAudio()
        stream = None
        resampler = None
        resample_buffer = bytearray()
        MAX_RESAMPLE_BUFFER = 512 * 1024

        try:
            device_info = p.get_default_input_device_info()
            device_rate = int(device_info['defaultSampleRate'])
            # 计算分块时长（毫秒）
            chunk_duration_ms = int(self.CHUNK / self.RATE * 1000)
            self.log.info(f"🎤 使用设备: {device_info['name']}, 设备采样率: {device_rate}Hz")
            self.log.info(f"   目标分块大小: {self.CHUNK} samples ({chunk_duration_ms}ms)")

            need_resample = (device_rate != self.RATE)
            if need_resample:
                try:
                    import samplerate
                    self.log.info(f"设备采样率 {device_rate}Hz != 目标 {self.RATE}Hz，启用重采样")
                    resampler = samplerate
                except ImportError:
                    self.log.error("需要重采样但未安装 samplerate 库，请运行: pip install samplerate")
                    self.log.error("将尝试以目标采样率直接打开设备，若设备不支持可能导致错误")
                    need_resample = False

            if need_resample:
                read_chunk = int(self.CHUNK * device_rate / self.RATE)
            else:
                read_chunk = self.CHUNK

            stream = p.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=device_rate if need_resample else self.RATE,
                input=True,
                frames_per_buffer=read_chunk
            )

            frame_duration = read_chunk / device_rate

            if self.power_save_enabled:
                self.idle_silence_frames = int(self.power_save_silence_seconds / frame_duration)
                self.idle_send_interval = int(1.0 / frame_duration)
            else:
                self.idle_silence_frames = float('inf')
                self.idle_send_interval = 0

            self.idle_mode = False
            self.consecutive_silent = 0
            self.frame_counter = 0
            self.total_frames = 0
            self.speech_frames = 0
            self.last_log_time = time.time()
            self.speaking = True
            self.silence_start_time = None

            while self.running:
                try:
                    data = stream.read(read_chunk, exception_on_overflow=False)
                except Exception as e:
                    self.log.error(f"音频读取错误: {e}")
                    await asyncio.sleep(frame_duration * 0.95)
                    continue

                if need_resample and resampler:
                    try:
                        resample_buffer.extend(data)
                        if len(resample_buffer) > MAX_RESAMPLE_BUFFER:
                            discard = len(resample_buffer) // 2
                            resample_buffer = resample_buffer[discard:]
                
                        needed_source_samples = int(self.CHUNK * device_rate / self.RATE) + 5
                        needed_bytes = needed_source_samples * 2
                
                        while len(resample_buffer) >= needed_bytes:
                            source_data = resample_buffer[:needed_bytes]
                            resample_buffer = resample_buffer[needed_bytes:]
                
                            audio_int16 = np.frombuffer(source_data, dtype=np.int16)
                            audio_float = audio_int16.astype(np.float32) / 32768.0
                            resampled_float = resampler.resample(audio_float, self.RATE / device_rate, converter_type='sinc_fastest')
                
                            if len(resampled_float) > self.CHUNK:
                                resampled_float = resampled_float[:self.CHUNK]
                            elif len(resampled_float) < self.CHUNK:
                                resampled_float = np.pad(resampled_float, (0, self.CHUNK - len(resampled_float)))
                
                            resampled_int16 = np.clip(resampled_float * 32768, -32768, 32767).astype(np.int16)
                            processed_data = resampled_int16.tobytes()
                
                            try:
                                await self._process_and_send_frame(processed_data, ws, frame_duration)
                            except websockets.exceptions.ConnectionClosed:
                                self.log.info("WebSocket 连接已关闭，退出音频捕获")
                                raise
                            except Exception as e:
                                self.log.error(f"处理帧失败: {e}", exc_info=True)
                    except websockets.exceptions.ConnectionClosed:
                        raise
                    except Exception as e:
                        self.log.error(f"重采样处理失败: {e}", exc_info=True)
                        continue
                else:
                    try:
                        await self._process_and_send_frame(data, ws, frame_duration)
                    except websockets.exceptions.ConnectionClosed:
                        raise
                    except Exception as e:
                        self.log.error(f"处理帧失败: {e}", exc_info=True)
                
                # 每 100 帧打印一次进度（约 2-5 秒）
                if self.total_frames % 100 == 0:
                    self.log.debug(f"已处理 {self.total_frames} 帧音频")

                await asyncio.sleep(frame_duration)

        except Exception as e:
            self.log.error(f"音频捕获异常: {e}", exc_info=True)
            raise
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            p.terminate()
            self.log.info("音频捕获已停止")

    async def _process_and_send_frame(self, data, ws, frame_duration):
        """处理单帧音频：能量检测、说话状态控制、打断检测，并决定是否发送"""
        self.total_frames += 1

        audio_array = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        energy = np.sqrt(np.mean(audio_array ** 2))
        is_speech = (energy >= self.vad_energy_threshold)

        # 打断检测：语音输入能量超过阈值时打断TTS
        if self.interrupt_enabled and self.tts_core:
            now = time.time()
            if energy > self.interrupt_energy_threshold and (now - self._last_interrupt_time) > self.interrupt_cooldown:
                self.log.info(f"检测到高能量语音输入 (能量: {energy:.1f} > 阈值: {self.interrupt_energy_threshold})，执行打断")
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._do_interrupt)
                    self._last_interrupt_time = now
                except Exception as e:
                    self.log.error(f"执行打断失败: {e}")

        now = time.time()

        if is_speech:
            self.speech_frames += 1
            self.consecutive_silent = 0

            if self.idle_mode and self.power_save_enabled:
                self.idle_mode = False
                self.log.debug("退出空闲模式")

            if not self.speaking:
                self.speaking = True
                await ws.send(json.dumps({"is_speaking": True}))
                self.log.debug("发送开始说话标志")

            self.silence_start_time = None
        else:
            self.consecutive_silent += 1

            if self.power_save_enabled and not self.idle_mode and self.consecutive_silent >= self.idle_silence_frames:
                self.idle_mode = True
                self.log.debug("进入空闲模式")
                self.frame_counter = 0

            if self.speaking:
                if self.silence_start_time is None:
                    self.silence_start_time = now
                elif (now - self.silence_start_time) >= self.silence_threshold:
                    self.speaking = False
                    await ws.send(json.dumps({"is_speaking": False}))
                    self.log.debug("发送结束说话标志")
                    self.silence_start_time = None

        # 决定是否发送此帧
        send_this_frame = False
        if not self.idle_mode:
            send_this_frame = True
        elif self.power_save_enabled:
            self.frame_counter += 1
            if self.frame_counter >= self.idle_send_interval:
                send_this_frame = True
                self.frame_counter = 0

        if send_this_frame:
            try:
                await ws.send(data)
            except websockets.exceptions.ConnectionClosed:
                self.log.warning("发送时连接关闭，退出捕获循环")
                raise
            except Exception as e:
                self.log.error(f"发送帧异常: {e}")
        else:
            # 空闲模式下跳过发送，减少日志噪音
            if self.total_frames % 500 == 0:
                self.log.debug(f"空闲模式: 跳过发送 (frame={self.total_frames})")

        # 定期打印统计（每5秒）
        if now - self.last_log_time >= 5.0:
            if self.total_frames > 0:
                speech_ratio = (self.speech_frames / self.total_frames) * 100
                self.log.info(f"📊 音频统计: 语音占比 {speech_ratio:.1f}% ({self.speech_frames}/{self.total_frames} 帧), 空闲模式={self.idle_mode}")
            self.last_log_time = now
            self.total_frames = 0
            self.speech_frames = 0

    async def _message_receiver(self, ws):
        """接收服务器消息"""
        msg_count = 0
        async for message in ws:
            msg_count += 1
            # 每 50 条消息打印一次统计，减少日志噪音
            if msg_count % 50 == 0:
                self.log.debug(f"已接收 {msg_count} 条消息")
            
            if isinstance(message, bytes):
                # 二进制数据（通常是音频反馈），忽略
                continue
            try:
                data = json.loads(message)
                # 只在首次或关键消息时打印完整内容
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

                # 流式中间结果：可选择性使用（如用于实时打断），但不发送给 LLM
                if text and "online" in mode and not is_final:
                    self.log.info(f"🔄 流式识别: {text}")
                    self.streaming_text = text
                    self.stream_last_update = time.time()
                    # 仍可触发打断
                    if self.interrupt_enabled and self.tts_core and text:
                        self._do_interrupt()
                # 最终结果：经过说话人验证后发送给 LLM
                elif text and ("offline" in mode or is_final):
                    self.log.info(f"✅ 识别到最终文本: {text} (mode={mode}, is_final={is_final})")
                    spk_name = data.get("spk_name", "未知")
                    spk_score = data.get("spk_score", 0.0)
                    self.log.info(f"   说话人: {spk_name}, 置信度: {spk_score:.3f}")
                    await self._handle_result(text, spk_name, self.uid, spk_score)

            except json.JSONDecodeError:
                self.log.warning(f"收到非 JSON 消息: {message[:100]}")

    async def _handle_result(self, text: str, speaker_name: str, speaker_uid: str, score: float):
        """处理识别结果，进行说话人验证"""
        if not text.strip():
            self.log.warning("⚠️ 收到空文本，忽略")
            return
        
        # 检查说话人是否在目标列表中
        if speaker_name not in self.target_speakers:
            self.log.warning(f"⚠️ 说话人 '{speaker_name}' 不在目标列表中 {self.target_speakers}，忽略")
            return
        
        # 检查置信度
        if score < self.speaker_threshold:
            self.log.warning(f"⚠️ 说话人 '{speaker_name}' 置信度 {score:.3f} < 阈值 {self.speaker_threshold}，忽略")
            return
        
        self.log.info(f"✅ 通过说话人验证: {speaker_name} (score={score:.3f})")

        key = speaker_name
        # 取消旧任务并立即从字典移除，防止旧 finally 误删新任务
        old_task = self.pending_tasks.pop(key, None)
        if old_task and not old_task.done():
            old_task.cancel()

        # 合并或新建文本
        if key in self.pending_texts:
            self.pending_texts[key] = self.pending_texts[key] + " " + text
        else:
            self.pending_texts[key] = text

        # 创建新任务
        task = asyncio.create_task(self._delayed_send(key, self.uid, speaker_name))
        self.pending_tasks[key] = task

    async def _delayed_send(self, speaker_name: str, speaker_uid: str, username: str):
        try:
            await asyncio.sleep(self.merge_delay)
            full_text = self.pending_texts.pop(speaker_name, "").strip()
            if full_text:
                await self._send_to_llm(full_text, username, speaker_uid)
        except asyncio.CancelledError:
            pass
        finally:
            # 只有当前任务仍在 pending_tasks 中且与自身相同时才移除
            if self.pending_tasks.get(speaker_name) is asyncio.current_task():
                self.pending_tasks.pop(speaker_name, None)

    async def _send_to_llm(self, text: str, username: str, uid: str):
        """发送文本到 LLM"""
        if self.callback:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.callback, text, uid, username)
        else:
            url = f"{self.api_base}/msg"
            payload = {"msg": text, "uid": uid, "username": username}
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            self.log.info(f"已送入 AI 核心: {text[:30]}... (说话人: {username})")
                        else:
                            self.log.error(f"发送失败: {resp.status}")
            except Exception as e:
                self.log.error(f"HTTP 异常: {e}")