# -*- coding: utf-8 -*-
# func/sensevoice/manager.py - 服务端消息接收处理与发送提交

import asyncio
import json
import re

import aiohttp

from func.sensevoice.optimizer import SenseVoiceTextOptimizer



class SenseVoiceManager:
    """收服务端结果 + 声纹过滤 + 断句合并；发送 audio/ctrl 为非阻塞提交"""

    def __init__(self, config, port, log, callback=None,
                 wav_name="mic", speaker_verify=True, username="主人",
                 llm_source="llm", subtitle_publish=False, subtitle=None):
        self.config = config
        self.port = port
        self.log = log
        self.callback = callback
        self.optimizer = SenseVoiceTextOptimizer(config)

        self.wav_name = wav_name
        self.speaker_verify = bool(speaker_verify)
        self.username = username
        # 手机语音链路：消息标记 source=phone；识别文本投用户字幕
        self.llm_source = llm_source
        self.subtitle_publish = bool(subtitle_publish)
        self.subtitle = subtitle

        from func.config.app_config import AppConfig
        self.api_base = f"http://127.0.0.1:{AppConfig().port}"

        self._speaking = False
        # 断句状态：累积文本 + VAD 驱动的 merge 计时
        self.pending_texts = {}        # key -> 累积文本
        self._merge_task = None        # merge_delay 计时任务
        self._merge_key = None         # 计时对应的 key
        self._expecting_final = False  # 静音后等待 final

    async def send_config(self):
        """发送 SenseVoice 启动配置"""
        cfg = {
            "wav_name": self.wav_name,
            "is_speaking": self._speaking,
            "language": self.config.language,
            "itn": self.config.itn,
            "mode": self.config.mode,
        }

        hotwords_dict = self._parse_hotwords(self.config.hotwords)
        if hotwords_dict:
            cfg["hotwords"] = json.dumps(hotwords_dict, ensure_ascii=False)

        await self.port.send_config(cfg)
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

    def send_audio(self, data: bytes):
        """非阻塞提交一帧音频到发送队列"""
        return self.port.submit_audio(data)

    def send_speaking(self, speaking: bool):
        """更新本地说话状态并非阻塞提交控制消息"""
        self._speaking = speaking
        return self.port.submit_ctrl({"is_speaking": speaking})

    def on_speech_start(self):
        """新开口：取消 merge 计时（继续累积，不发送）"""
        if self._merge_task and not self._merge_task.done():
            self._merge_task.cancel()
        self._merge_task = None
        self._merge_key = None
        self._expecting_final = False

    def on_speech_end(self):
        """静音结束说话：标记等待 final（收到 final 后启动 merge 计时）"""
        self._expecting_final = True

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

        if text and ("offline" in mode or is_final):
            # 最终结果：进入说话人验证与断句合并
            self.log.info(f"✅ 识别到最终文本: {text} (mode={mode}, is_final={is_final})")
            spk_name = data.get("spk_name", "未知")
            spk_score = data.get("spk_score", 0.0)
            self.log.info(f"   说话人: {spk_name}, 置信度: {spk_score:.3f}")
            await self._handle_result(text, spk_name, spk_score)

    @staticmethod
    def speaker_allowed(spk_name, targets):
        """白名单校验：声纹名和配置里写的一样就通过

        声纹文件名用编号（000001），配置里一般写昵称（YGZ醒脑片），
        两边随便写哪边都认——编号认昵称、昵称认编号都试一遍。
        """
        wanted = [str(t).strip() for t in (targets or []) if str(t).strip()]
        if not wanted:
            return False
        name = str(spk_name or "").strip()
        if not name:
            return False
        if name in wanted:
            return True
        try:
            from func.pipeline.id_signup import IdSignupBridge
            bridge = IdSignupBridge()
            mine = bridge.resolve_name(name) or name
            for target in wanted:
                if target == name or target == mine:
                    return True
                if bridge.resolve_name(target) == mine:
                    return True
                if bridge.nickname_of(target) == name:
                    return True
                if bridge.nickname_of(target) and bridge.nickname_of(target) == bridge.nickname_of(mine):
                    return True
        except Exception:
            pass
        return False

    async def _handle_result(self, text: str, spk_name: str, spk_score: float):
        """说话人验证并按说话人合并断句"""
        if not text.strip():
            self.log.warning("⚠️ 收到空文本，忽略")
            return

        # 手机语音：识别文本先投用户字幕（手机端"你说：xxx"泡泡回显），
        # 不依赖声纹验证——只要识别到非空内容手机就显示（方案2A）
        if self.subtitle is not None and self.subtitle_publish:
            try:
                self.subtitle.put(self.username or spk_name or '', text)
            except Exception:
                self.log.exception("写入用户字幕失败")

        if self.speaker_verify:
            if not self.speaker_allowed(spk_name, self.config.target_speakers):
                self.log.warning(f"⚠️ 说话人 '{spk_name}' 不在目标列表中 {self.config.target_speakers}，忽略")
                return
            if spk_score < self.config.speaker_threshold:
                self.log.warning(f"⚠️ 说话人 '{spk_name}' 置信度 {spk_score:.3f} < 阈值 {self.config.speaker_threshold}，忽略")
                return
            raw = spk_name
            self.log.info(f"✅ 通过说话人验证: {spk_name} (score={spk_score:.3f})")
        else:
            raw = self.username
            self.log.info(f"✅ 跳过声纹验证，使用配置身份: {raw}")

        uid = ""
        try:
            from func.pipeline.id_signup import IdSignupBridge
            uid = str(IdSignupBridge().resolve_name(raw) or "")
        except Exception:
            self.log.exception("解析说话人身份失败")
        if not uid:
            self.log.warning(f"说话人 '{raw}' 没有对应身份，已忽略本条（不兜底、不建临时身份）")
            return

        # ASR 字幕：识别内容推字幕服务器（桌面字幕顶部人名；保持原逻辑——声纹通过后显示）
        try:
            from func.pipeline.get_subtitle import GetSubtitleBridge
            GetSubtitleBridge().send_asr(text, uid)
        except Exception:
            pass

        # 记录最近一次说话人（供哼唱识别绑定用户名）
        try:
            from func.pipeline.toolbox_audio import ToolboxAudioBridge
            ToolboxAudioBridge().set_last_speaker(uid)
        except Exception:
            self.log.exception("写入最后声纹说话人失败")

        key = uid
        # 只累积文本，不因 final 到达而重置计时
        if key in self.pending_texts:
            self.pending_texts[key] = self.pending_texts[key] + " " + text
        else:
            self.pending_texts[key] = text

        # 静音后第一次 final → 启动 merge 计时
        if self._expecting_final:
            self._expecting_final = False
            self._start_merge(key)

    def _start_merge(self, key: str):
        """启动 merge 计时（静音后收到 final 时调用）"""
        if self._merge_task and not self._merge_task.done():
            self._merge_task.cancel()
        self._merge_key = key
        self._merge_task = asyncio.create_task(self._merge_wait(key))

    async def _merge_wait(self, key: str):
        """merge_delay 宽限期内无新开口则发送；被 on_speech_start 取消则不发送"""
        try:
            await asyncio.sleep(self.config.merge_delay)
            full_text = self.pending_texts.pop(key, "").strip()
            if full_text:
                full_text = self.optimizer.optimize(full_text)
                # 静默/唤醒词检测（合并+优化后的完整句；静默词优先于唤醒词）
                try:
                    from func.pipeline.silence_state import SilenceState
                    silence = SilenceState()
                    if silence.enabled:
                        if silence.hit_mute(full_text):
                            silence.mute()
                        elif silence.hit_wake(full_text):
                            silence.unmute()
                except Exception:
                    self.log.exception("静默状态检测异常")
                await self._send_to_llm(full_text, key)
        except asyncio.CancelledError:
            pass
        finally:
            # 仅当仍是当前计时任务时才清理
            if self._merge_task is asyncio.current_task():
                self._merge_task = None
                self._merge_key = None

    async def _send_to_llm(self, text: str, uid: str):
        """发送识别文本到 LLM"""
        if self.callback:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.callback, text, uid, self.llm_source)
            return

        url = f"{self.api_base}/msg"
        payload = {"msg": text, "username": uid, "source": self.llm_source}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        self.log.info(f"已送入 AI 核心: {text[:30]}... (说话人: {uid})")
                    else:
                        self.log.error(f"发送失败: {resp.status}")
        except Exception as e:
            self.log.error(f"HTTP 异常: {e}")
