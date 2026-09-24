import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
DESKTOPET_DIR = os.path.join(PROJECT_DIR, '.desktopet')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
CERT_DIR = os.path.join(BASE_DIR, 'cert')
CERT_PEM = os.path.join(CERT_DIR, 'cert.pem')
KEY_PEM = os.path.join(CERT_DIR, 'key.pem')
CONFIG_YML = os.path.join(PROJECT_DIR, 'config.yml')

API_BASE = 'http://127.0.0.1:1800'
HOST = '0.0.0.0'
HTTPS_PORT = 8443
PET_HTTP_PORT = 8445

AUDIO_TARGET_RATE = 16000
AUDIO_TARGET_CHANNELS = 1
AUDIO_FRAME_BYTES = 960
AUDIO_RESAMPLE_CONVERTER = 'sinc_medium'
AUDIO_ENERGY_THRESHOLD = 300.0
AUDIO_SILENCE_SECS = 2.0
AUDIO_MAX_UTTERANCE_SECS = 30.0
AUDIO_MIN_UTTERANCE_SECS = 0.25
AUDIO_SEND_TIMEOUT = 2.0

VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 30
VIDEO_BITRATE = 2000000
VIDEO_KEYFRAME_SECS = 2.0
# viewer 不再重放 GOP 积压（改为主动 reqkey 要新关键帧），这里只保留很小的应急缓存
VIDEO_GOP_MAX = 16
# 编码器/发送队列上限：超过就丢帧（智能丢帧第一层）
VIDEO_ENC_MAX_QUEUE = 2
# 手机端音频与视频分两条 WS，音频永不被视频积压拖住
AUDIO_SEPARATE_SOCKET = True
# 麦克风 gate：AI 播放期间是否掐掉手机麦克风（1=掐，0=不掐，交给 iOS 回声消除）
AUDIO_MIC_GATE = True
# relay → 主程序：把 30ms 小帧攒成一批再 POST（秒），降低请求数并抗超时
AUDIO_SEND_BATCH_SECS = 0.15

TTS_MAX_BLOCKS = 600
TTS_PENDING_LIMIT = 60
TTS_META_HOLD_SECS = 4.0
TTS_MAX_PENDING_BYTES = 262144
TTS_MAX_BLOCK_BYTES = 16384
MODE_FILE = os.path.join(BASE_DIR, 'mode.txt')
# 默认模式：call=手机听全部语音（默认）；chat=只听手机自己发起的对话
DEFAULT_MODE = 'call'


def _read_yml():
    """读取主项目 config.yml，失败时返回空字典"""
    try:
        import yaml
        with open(CONFIG_YML, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def apply_project_config():
    """从主项目 config.yml 覆盖音视频采集参数"""
    global AUDIO_TARGET_RATE, AUDIO_RESAMPLE_CONVERTER, AUDIO_ENERGY_THRESHOLD
    global AUDIO_SILENCE_SECS, AUDIO_FRAME_BYTES
    cfg = _read_yml()
    audio = cfg.get('audio') or {}
    sense = cfg.get('sensevoice') or {}
    rate = int(audio.get('rate', AUDIO_TARGET_RATE) or AUDIO_TARGET_RATE)
    AUDIO_TARGET_RATE = max(8000, rate)
    AUDIO_RESAMPLE_CONVERTER = str(audio.get('resample_converter', AUDIO_RESAMPLE_CONVERTER) or AUDIO_RESAMPLE_CONVERTER)
    chunk_ms = int(audio.get('chunk_size_ms', 0) or 0)
    if chunk_ms <= 0:
        chunk_ms = int(sense.get('chunk_size_ms', 30) or 30)
    chunk_ms = max(20, min(100, chunk_ms))
    AUDIO_FRAME_BYTES = int(AUDIO_TARGET_RATE * chunk_ms / 1000) * 2
    AUDIO_ENERGY_THRESHOLD = float(sense.get('vad_energy_threshold', AUDIO_ENERGY_THRESHOLD) or AUDIO_ENERGY_THRESHOLD)
    AUDIO_SILENCE_SECS = float(sense.get('silence_threshold', AUDIO_SILENCE_SECS) or AUDIO_SILENCE_SECS)
    return {
        'rate': AUDIO_TARGET_RATE,
        'converter': AUDIO_RESAMPLE_CONVERTER,
        'frame_bytes': AUDIO_FRAME_BYTES,
        'energy': AUDIO_ENERGY_THRESHOLD,
        'silence': AUDIO_SILENCE_SECS,
    }
