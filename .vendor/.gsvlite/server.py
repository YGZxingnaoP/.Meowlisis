# -*- coding: utf-8 -*-
"""GSV-TTS-Lite 精简服务端（兼容 GPT-SoVITS api_v2 的 /tts）

只保留本项目需要的部分：流式/非流式 /tts、权重热切换、健康检查。
不做 prompt 音频的 ASR 自动识别、批量推理、URL 下载与字幕输出。
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np
import soundfile as sf
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _boot_config():
    try:
        with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


_BOOT = _boot_config()
if _BOOT.get("sdpa"):
    os.environ.setdefault("GSVLITE_SDPA", str(_BOOT["sdpa"]))

from gsv_tts import TTS  # noqa: E402

log = logging.getLogger("gsvlite")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CFG_PATH = ROOT / "config.yaml"
STATE = {"tts": None, "gpt": "", "sovits": ""}
CUT_MINLEN = {"cut0": 999, "cut1": 50, "cut2": 50, "cut3": 20, "cut4": 20, "cut5": 10}
LANGS = ("auto", "ja", "zh", "en")


def _resolve(p) -> str:
    p = str(p or "").strip()
    if not p:
        return ""
    return p if os.path.isabs(p) else str((ROOT / p).resolve())


def _load_cfg() -> dict:
    if not CFG_PATH.exists():
        return {}
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _legacy_weights():
    """lite 配置没写权重时，回落到 .vendor/.Sovits/tts_infer.yaml（模型卡片改的就是它）"""
    p = ROOT.parent / ".Sovits" / "tts_infer.yaml"
    if not p.exists():
        return "", ""
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return "", ""
    custom = data.get("custom") or {}
    gpt = custom.get("t2s_weights_path") or data.get("t2s_weights_path") or ""
    sov = custom.get("vits_weights_path") or data.get("vits_weights_path") or ""
    base = p.parent
    return (
        str((base / gpt).resolve()) if gpt else "",
        str((base / sov).resolve()) if sov else "",
    )


def _pack_raw(data) -> bytes:
    a = np.asarray(data)
    if a.dtype != np.int16:
        a = np.clip(a, -1.0, 1.0)
        a = (a * 32767.0).astype(np.int16)
    return a.tobytes()


def _pack_wav(data, rate: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.asarray(data), int(rate), format="wav")
    return buf.getvalue()


def _wav_header(rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(b"")
    return buf.getvalue()


def _pick(req: dict, key: str, default=None):
    v = req.get(key, default)
    return default if v is None or v == "" else v


def _pick_ref_audio():
    """挑一条项目里的参考音频做启动预热（没有就跳过）"""
    cfg_path = ROOT.parent.parent / "character" / "ref_audio" / "config.json"
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return "", ""
    for item in data.values():
        if not isinstance(item, dict):
            continue
        ordered = [item.get(k) for k in ("neutral", "happy", "love")] + list(item.values())
        for e in ordered:
            if not isinstance(e, dict) or not e.get("audio") or not e.get("text"):
                continue
            p = ROOT.parent.parent / str(e["audio"])
            if p.exists():
                return str(p), str(e["text"])
    return "", ""


def _warmup(tts):
    """启动预热：把 hubert/声纹/BERT/首句 CUDA Graph 全部走一遍，避免首句 15s"""
    ref, text = _pick_ref_audio()
    if not ref:
        log.warning("未找到参考音频，跳过 GSV-Lite 预热（首句会慢）")
        return
    t0 = time.time()
    try:
        for _ in tts.infer_stream(
            spk_audio_path=ref,
            prompt_audio_path=ref,
            prompt_audio_text=text,
            text="喵呜。",
            text_language="zh",
            prompt_language="zh",
            is_cut_text=True,
            cut_minlen=10,
            cut_mute=0.0,
            stream_mode="token",
            stream_chunk=12,
            overlap_len=2,
            boost_first_chunk=True,
            debug=False,
        ):
            break
        log.info("GSV-Lite 预热完成 %.1fs", time.time() - t0)
    except Exception:
        log.exception("GSV-Lite 预热失败（不影响服务，但首句会慢）")


async def _read_req(request: Request) -> dict:
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        return body if isinstance(body, dict) else {}
    return dict(request.query_params)


app = FastAPI(title="GSV-TTS-Lite (Meowlisis)")


@app.on_event("startup")
def _startup():
    cfg = _load_cfg()
    kwargs = {}
    if cfg.get("device"):
        kwargs["device"] = cfg["device"]
    if cfg.get("dtype"):
        kwargs["dtype"] = cfg["dtype"]
    if cfg.get("gpt_cache"):
        kwargs["gpt_cache"] = [tuple(x) for x in cfg["gpt_cache"]]
    if cfg.get("sovits_cache"):
        kwargs["sovits_cache"] = list(cfg["sovits_cache"])
    if "use_bert" in cfg:
        kwargs["use_bert"] = bool(cfg["use_bert"])
    models_dir = _resolve(cfg.get("models_dir") or "models")
    need = ["chinese-hubert-base", "g2p", "sv"]
    if kwargs.get("use_bert"):
        need.append("chinese-roberta-wwm-ext-large")
    missing = [n for n in need if not (Path(models_dir) / n).exists()]
    if missing:
        raise RuntimeError(f"预训练底座缺失: {missing}；先运行 python download_models.py")
    log.info("加载 GSV-Lite: models_dir=%s kwargs=%s", models_dir, kwargs)
    tts = TTS(models_dir=models_dir, **kwargs)
    gpt = _resolve(cfg.get("gpt_weights"))
    sov = _resolve(cfg.get("sovits_weights"))
    if not (gpt and sov):
        gpt2, sov2 = _legacy_weights()
        gpt = gpt or gpt2
        sov = sov or sov2
    if not gpt or not sov:
        raise RuntimeError("未找到权重：请在 config.yaml 或 .vendor/.Sovits/tts_infer.yaml 里配置")
    tts.load_gpt_model(gpt)
    tts.load_sovits_model(sov)
    STATE.update(tts=tts, gpt=gpt, sovits=sov)
    if bool(cfg.get("warmup", True)):
        _warmup(tts)
    log.info("权重就绪: gpt=%s sovits=%s", gpt, sov)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "ready": STATE.get("tts") is not None,
        "gpt": STATE.get("gpt", ""),
        "sovits": STATE.get("sovits", ""),
    }


@app.get("/set_gpt_weights")
def set_gpt_weights(weights_path: str = ""):
    tts = STATE.get("tts")
    if tts is None:
        raise HTTPException(503, "TTS 未就绪")
    p = _resolve(weights_path)
    if not p or not os.path.exists(p):
        raise HTTPException(400, "weights_path 不存在")
    for old in list(tts.gpt_models):
        tts.unload_gpt_model(old)
    tts.load_gpt_model(p)
    STATE["gpt"] = p
    return {"status": "ok", "gpt": p}


@app.get("/set_sovits_weights")
def set_sovits_weights(weights_path: str = ""):
    tts = STATE.get("tts")
    if tts is None:
        raise HTTPException(503, "TTS 未就绪")
    p = _resolve(weights_path)
    if not p or not os.path.exists(p):
        raise HTTPException(400, "weights_path 不存在")
    for old in list(tts.sovits_models):
        tts.unload_sovits_model(old)
    tts.load_sovits_model(p)
    STATE["sovits"] = p
    return {"status": "ok", "sovits": p}


@app.api_route("/tts", methods=["GET", "POST"])
async def tts_api(request: Request):
    tts = STATE.get("tts")
    if tts is None:
        raise HTTPException(503, "TTS 未就绪")
    req = await _read_req(request)

    text = str(_pick(req, "text", "")).strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    ref = _resolve(_pick(req, "ref_audio_path", ""))
    if not ref or not os.path.exists(ref):
        raise HTTPException(400, "ref_audio_path 不存在")
    prompt_text = str(_pick(req, "prompt_text", "")).strip()
    if not prompt_text:
        raise HTTPException(400, "prompt_text 不能为空（精简版不做 ASR 自动识别）")

    media_type = str(_pick(req, "media_type", "raw")).lower()
    if media_type not in ("raw", "wav"):
        raise HTTPException(400, "media_type 只支持 raw/wav")

    try:
        mode = int(float(_pick(req, "streaming_mode", 0)))
    except Exception:
        mode = 0

    cut_method = str(_pick(req, "text_split_method", "cut5"))
    is_cut = cut_method not in ("", "cut0", "none")
    cut_minlen = CUT_MINLEN.get(cut_method, 10)
    cut_mute = float(_pick(req, "fragment_interval", 0.0))
    top_k = int(_pick(req, "top_k", 15))
    top_p = float(_pick(req, "top_p", 1.0))
    temperature = float(_pick(req, "temperature", 1.0))
    repetition_penalty = float(_pick(req, "repetition_penalty", 1.35))
    noise_scale = float(_pick(req, "noise_scale", 0.5))
    speed = float(_pick(req, "speed_factor", 1.0))
    stream_chunk = max(1, int(_pick(req, "min_chunk_length", 25)))
    overlap_len = max(1, int(_pick(req, "overlap_length", 5)))
    text_lang = str(_pick(req, "text_lang", "auto") or "auto").lower()
    prompt_lang = str(_pick(req, "prompt_lang", "auto") or "auto").lower()
    if text_lang not in LANGS:
        text_lang = "auto"
    if prompt_lang not in LANGS:
        prompt_lang = "auto"

    boost = _pick(req, "boost_first_chunk", None)
    boost = (mode == 1) if boost is None else bool(boost)

    common = dict(
        spk_audio_path=ref,
        prompt_audio_path=ref,
        prompt_audio_text=prompt_text,
        text=text,
        text_language=text_lang,
        prompt_language=prompt_lang,
        top_k=top_k,
        top_p=top_p,
        temperature=temperature,
        repetition_penalty=repetition_penalty,
        noise_scale=noise_scale,
        speed=speed,
    )

    if mode <= 0:
        clip = await tts.infer_async(**common)
        body = _pack_wav(clip.audio_data, clip.samplerate) if media_type == "wav" else _pack_raw(clip.audio_data)
        return Response(body, media_type=f"audio/{media_type}")

    stream_kwargs = dict(
        **common,
        is_cut_text=is_cut,
        cut_minlen=cut_minlen,
        cut_mute=cut_mute,
        stream_mode="token",
        stream_chunk=stream_chunk,
        overlap_len=overlap_len,
        boost_first_chunk=bool(boost),
        debug=False,
    )

    async def gen():
        first = True
        async for clip in tts.infer_stream_async(**stream_kwargs):
            if first:
                first = False
                if media_type == "wav":
                    yield _wav_header(clip.samplerate)
            yield _pack_raw(clip.audio_data)

    return StreamingResponse(gen(), media_type=f"audio/{media_type}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("-p", "--port", type=int, default=9881)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
