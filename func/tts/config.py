# -*- coding: utf-8 -*-
# func/tts/config.py
# TTS 模块集中配置

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton
from func.log.default_log import DefaultLog


@singleton
class TTSConfig:
    """TTS 所有配置的集中入口"""

    def __init__(self):
        tts_cfg = ConfigReader().get("tts", {})

        self.select = tts_cfg.get("select", "gpt-sovits")
        self.synth_workers = int(tts_cfg.get("synth_workers", 2))

        gpt = tts_cfg.get("gpt-sovits", {})
        self.gpt_sovits_url = gpt.get("gpt_sovits_url", "http://127.0.0.1:9880")

        # ===== 流式合成配置 =====
        # streaming_mode: 2=按静音点智能切分(听感最连贯) 3=定长切分(响应更快)
        self.streaming_mode = int(gpt.get("streaming_mode", 2))
        # media_type: raw=裸 PCM(推荐, 无 wav 头) wav=带 wav 头
        self.media_type = gpt.get("media_type", "raw")
        # fragment_interval: 段尾静音(秒), 流式下必须为 0 避免间隔
        self.fragment_interval = float(gpt.get("fragment_interval", 0.0))
        # min_chunk_length: 语义 token 块长度, 越小首包越快, 越大越流畅(16 token≈0.64s)
        self.min_chunk_length = int(gpt.get("min_chunk_length", 12))
        # overlap_length: 块间重叠 token 数, 越大衔接越自然
        self.overlap_length = int(gpt.get("overlap_length", 2))
        # v2Pro 流式输出采样率
        self.sample_rate = int(gpt.get("sample_rate", 32000))
        # 合成文本语言：zh 最稳（中文 g2p 可读短英文词），auto 中英混合但可能误判成日文
        self.text_lang = gpt.get("text_lang", "zh")
        # 是否启用「整段语言自动切换」：整段英文/日文时覆盖 text_lang，其余落回 text_lang
        self.lang_judge_enabled = bool(gpt.get("lang_judge_enabled", True))

        # ===== 采样参数（透传给 .Sovits API）=====
        self.top_k = int(gpt.get("top_k", 15))
        self.top_p = float(gpt.get("top_p", 1.0))
        self.temperature = float(gpt.get("temperature", 1.0))
        self.repetition_penalty = float(gpt.get("repetition_penalty", 1.35))
        self.noise_scale = float(gpt.get("noise_scale", 0.5))
        self.speed = float(gpt.get("speed", 1.0))

        # ===== 情绪映射 =====
        # 情绪 → 采样参数覆盖（如 happy 语速略快、sad 语速慢且 noise 更低）
        self.emotion_params = gpt.get("emotion_params", {}) or {}
        # 情绪 → 参考音频 key 映射（call→love、approve→happy 等归并）
        self.emotion_audio = gpt.get("emotion_audio", {}) or {}

        self.output_dir = tts_cfg.get("output_dir", "./output")
        self.volume = float(tts_cfg.get("volume", 1.0))

        interrupt = tts_cfg.get("interrupt", {})
        self.interrupt_mode = interrupt.get("mode", "pipeline")
        self.interrupt_key = interrupt.get("key", "f8")
        self.interrupt_poll_interval = float(interrupt.get("poll_interval", 0.1))

        # pipeline 打断依赖 SenseVoice，未启用时自动降级为 off
        sensevoice_enabled = ConfigReader().get("sensevoice", {}).get("enabled", False)
        if self.interrupt_mode == "pipeline" and not sensevoice_enabled:
            DefaultLog().getLogger().warning("sensevoice 未启用，pipeline 打断自动降级为 off")
            self.interrupt_mode = "off"
