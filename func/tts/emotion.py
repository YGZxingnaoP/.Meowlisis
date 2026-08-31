# -*- coding: utf-8 -*-
# func/tts/emotion.py
# 情绪 → 参考音频 / 采样参数 的集中映射（供 tts_core / gpt_sovits 共用，保持主文件精简）


def resolve_emotion():
    """从 LLM 情绪桥接读取当前 (emotion, intensity)，失败回退 ('neutral', 3.0)。"""
    try:
        from func.pipeline.llm_emotion import LLMEmotionBridge

        bridge = LLMEmotionBridge()
        emotion = bridge.get_emotion() or "neutral"
        intensity = bridge.get_intensity()
        return emotion, float(intensity) if intensity is not None else 3.0
    except Exception:
        return "neutral", 3.0


def resolve_ref_audio(emotion: str, ref_audio_config: dict, emotion_audio_map: dict = None) -> dict:
    """按情绪从多情绪参考音频字典中选一条。

    ref_audio_config 支持两种格式：
    - 多情绪：{"happy": {...}, "sad": {...}, "neutral": {...}}
    - 旧单条：{"audio":..., "text":..., "lang":...}

    emotion_audio_map：情绪归并映射（如 call→love、approve→happy、blood→angry）。
    """
    emotion = str(emotion or "neutral").lower()
    ref = ref_audio_config or {}
    if not ref:
        return {}

    # 多情绪格式：任意 value 是含 audio 字段的 dict
    if isinstance(ref, dict) and any(isinstance(v, dict) and "audio" in v for v in ref.values()):
        emo_map = emotion_audio_map or {}
        audio_key = emo_map.get(emotion, emotion)
        return ref.get(audio_key) or ref.get("neutral") or next(iter(ref.values()), {})

    # 旧单条格式
    return ref


def build_sampling_params(emotion: str, intensity: float, base: dict, emotion_params_map: dict = None) -> dict:
    """在基础采样参数上叠加情绪覆盖，并按强度回拉（weak 时向 base 靠拢 50%）。

    base 键名（内部键）：top_k / top_p / temperature / repetition_penalty / noise_scale / speed。
    （speed 在 API payload 中映射为 speed_factor。）
    """
    emotion = str(emotion or "neutral").lower()
    params = dict(base or {})

    emo = dict((emotion_params_map or {}).get(emotion, {}) or {})
    if not emo:
        return params

    try:
        intensity = float(intensity)
    except Exception:
        intensity = 3.0
    intensity = max(0.0, min(5.0, intensity))

    # 强度系数：intensity=3 → 1.0（用配置的完整情绪值）
    #   <3 → 向基础值(neutral)回拉（0 时完全基础）
    #   >3 → 进一步放大情绪（5 时放大 50%）
    if intensity < 3.0:
        factor = intensity / 3.0
    else:
        factor = 1.0 + (intensity - 3.0) * 0.25

    for k, v in emo.items():
        if isinstance(v, (int, float)) and k in params:
            new_val = params[k] + (v - params[k]) * factor
            params[k] = round(new_val) if isinstance(params[k], int) else new_val

    return params
