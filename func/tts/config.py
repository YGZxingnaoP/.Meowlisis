# func/tts/config.py
# TTS 模块集中配置：读取 config.yml 的 speech 段并补齐默认值
from func.config.default_config import defaultConfig
from func.tools.singleton_mode import singleton


@singleton
class TTSConfig:
    """TTS 所有配置的集中入口，供各子模块复用"""

    def __init__(self):
        raw = defaultConfig().get_config()
        speech = raw.get("speech", {})

        # ===== 引擎 =====
        self.select = speech.get("select", "gpt-sovits")
        self.synth_workers = int(speech.get("synth_workers", 2))

        # ===== GPT-SoVITS =====
        gpt = speech.get("gpt-sovits", {})
        self.gpt_sovits_url = gpt.get("gpt_sovits_url", "http://127.0.0.1:9880")

        # ===== 输出与播放 =====
        self.output_dir = speech.get("output_dir", "./output")
        self.volume = float(speech.get("volume", 1.0))

        # ===== 打断 =====
        interrupt = speech.get("interrupt", {})
        self.interrupt_mode = interrupt.get("mode", "pipeline")  # pipeline / keyboard / off
        self.interrupt_key = interrupt.get("key", "f8")
        self.interrupt_poll_interval = float(interrupt.get("poll_interval", 0.1))
