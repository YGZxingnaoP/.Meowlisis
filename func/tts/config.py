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
