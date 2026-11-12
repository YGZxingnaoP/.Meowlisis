# -*- coding: utf-8 -*-
"""安装/更新 .vendor/.gsvlite（复制 GSV-TTS-Lite 内核 + 精简补丁 + 精简服务端）

用法：
    python scripts/gsvlite_setup.py                 # 默认从 D:\\Git\\projects\\GSV-TTS-Lite 复制
    python scripts/gsvlite_setup.py --src <目录>

说明：
    - 只复制 gsv_tts 包与 LICENSE，不带 WebUI / examples / API 示例；
    - 对复制过来的源码做三处精简补丁（pysbd / py3langid 降级、启动不联网下载）；
    - 写入 server.py / config.yaml / download_models.py / start.bat。
"""

import argparse
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DST = BASE / ".vendor" / ".gsvlite"
DEFAULT_SRC = Path(r"D:\Git\projects\GSV-TTS-Lite")


SERVER_PY = r'''# -*- coding: utf-8 -*-
"""GSV-TTS-Lite 精简服务端（兼容 GPT-SoVITS api_v2 的 /tts）

只保留本项目需要的部分：流式/非流式 /tts、权重热切换、健康检查。
不做 prompt 音频的 ASR 自动识别、批量推理、URL 下载与字幕输出。
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
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
'''

CONFIG_YAML = r'''# GSV-TTS-Lite 运行配置（精简版）
# 角色权重留空时自动读 ../.Sovits/tts_infer.yaml（前端「TTS 模型」卡片改的就是它）
models_dir: models
device: cuda
dtype: float16
use_bert: true
gpt_weights: ""
sovits_weights: ""
# CUDA Graph bucket：按实际片段长度配置，超出会回退普通路径
gpt_cache:
  - [1, 512]
  - [1, 768]
  - [1, 1024]
sovits_cache: [50, 100, 150, 200, 300]
'''

DOWNLOAD_PY = r'''# -*- coding: utf-8 -*-
"""GSV-Lite 预训练底座准备（不下载角色权重）

用法：
    python download_models.py            # 复用 .vendor/.Sovits 的底座 + 补 g2p
    python download_models.py --full     # 直链下载完整底座包（约 1~2GB）

直链：
    ModelScope : https://modelscope.cn/models/chinokiki/GPTSoVITS-RT/resolve/master/pretrained_models5.zip
    HuggingFace: https://huggingface.co/cnmds/GPTSoVITS-RT/resolve/main/pretrained_models6.zip?download=true
    g2p        : https://github.com/chinokikiss/GSV-TTS-Lite/releases/download/g2p/g2p.zip
"""
import argparse
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
VENDOR = ROOT.parent / ".Sovits" / "GPT_SoVITS" / "pretrained_models"
MS_FULL = "https://modelscope.cn/models/chinokiki/GPTSoVITS-RT/resolve/master/pretrained_models5.zip"
HF_FULL = "https://huggingface.co/cnmds/GPTSoVITS-RT/resolve/main/pretrained_models6.zip?download=true"
G2P_ZIP = "https://github.com/chinokikiss/GSV-TTS-Lite/releases/download/g2p/g2p.zip"


def log(msg):
    print(f"[gsvlite] {msg}", flush=True)


def make_junction(src: Path, dst: Path) -> bool:
    """优先建目录联接（不占空间），失败再复制"""
    if dst.exists():
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                           capture_output=True, text=True)
        if r.returncode == 0 and dst.exists():
            log(f"联接 {dst.name} -> {src}")
            return True
        log(f"联接失败（{r.stderr.strip() or r.stdout.strip()}），改为复制")
    try:
        shutil.copytree(src, dst)
        log(f"复制 {dst.name}")
        return True
    except Exception as e:
        log(f"复制失败 {dst}: {e}")
        return False


def download(url: str, dst: Path):
    log(f"下载 {url}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dst)


def unzip(zip_path: Path, out: Path):
    log(f"解压 {zip_path.name}")
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out)


def ensure_g2p():
    if (MODELS / "g2p").exists():
        log("g2p 已存在")
        return
    with tempfile.TemporaryDirectory() as td:
        zp = Path(td) / "g2p.zip"
        download(G2P_ZIP, zp)
        unzip(zp, MODELS)
    if not (MODELS / "g2p").exists():
        for p in MODELS.rglob("g2p"):
            if p.is_dir():
                if p.parent != MODELS:
                    shutil.move(str(p), str(MODELS / "g2p"))
                break
    log("g2p 就绪" if (MODELS / "g2p").exists() else "g2p 解压后仍未找到，请检查压缩包结构")


def link_vendor():
    ok = True
    for name in ("chinese-hubert-base", "chinese-roberta-wwm-ext-large", "sv"):
        src = VENDOR / name
        if not src.exists():
            log(f"vendor 缺少 {name}（可改用 --full）")
            ok = False
            continue
        ok = make_junction(src, MODELS / name) and ok
    return ok


def full_download(url: str):
    MODELS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        zp = Path(td) / "pretrained_models.zip"
        download(url, zp)
        unzip(zp, MODELS)
    ensure_g2p()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="直链下载完整底座包")
    ap.add_argument("--url", default=MS_FULL, help="--full 使用的下载地址")
    args = ap.parse_args()
    MODELS.mkdir(parents=True, exist_ok=True)
    if args.full:
        full_download(args.url)
    else:
        link_vendor()
        ensure_g2p()
    log("最终目录：")
    for p in sorted(MODELS.iterdir()):
        log(f"  {p.name}")
    log("直链（备用）：")
    for u in (MS_FULL, HF_FULL, G2P_ZIP):
        log(f"  {u}")


if __name__ == "__main__":
    main()
'''

START_BAT = r'''@echo off
chcp 65001 >nul
cd /d "%~dp0"
..\..\runtime\311\python.exe server.py --host 127.0.0.1 --port 9881 %*
pause
'''


def patch_text(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"补丁定位失败: {path}\n--- 期望片段 ---\n{old}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"[gsvlite] patched {path.relative_to(DST)}")


def patch_all():
    # 1) 启动时不要联网下载（由 download_models.py 显式准备）
    p = DST / "gsv_tts" / "Download.py"
    start = p.read_text(encoding="utf-8").index("def check_pretrained_models(models_dir):")
    end = p.read_text(encoding="utf-8").index("cnroberta_int8_modelscope_base_url", start)
    new_fn = (
        "def check_pretrained_models(models_dir):\n"
        '    """精简版：启动时不联网下载；缺失由 download_models.py 负责补齐。"""\n'
        '    missing = [n for n in ("chinese-hubert-base", "g2p", "sv")\n'
        '               if not os.path.exists(os.path.join(str(models_dir), n))]\n'
        '    if missing:\n'
        '        logging.warning("GSV-Lite 预训练底座缺失: %s（请先运行 download_models.py）",\n'
        '                        ", ".join(missing))\n\n\n'
    )
    text = p.read_text(encoding="utf-8")
    p.write_text(text[:start] + new_fn + text[end:], encoding="utf-8")
    print("[gsvlite] patched gsv_tts/Download.py")

    # 2) pysbd 缺失时用正则分句
    p = DST / "gsv_tts" / "TextProcessor.py"
    patch_text(
        p,
        "import pysbd\n",
        "try:\n    import pysbd\nexcept ImportError:  # 精简运行时：没有 pysbd 时用正则近似分句\n    pysbd = None\n",
    )
    patch_text(
        p,
        "seg = pysbd.Segmenter()\n",
        "class _RegexSegmenter:\n"
        "    _re = re.compile(r'(?<=[。！？!?…])\\s*')\n\n"
        "    def segment(self, text):\n"
        "        return [s for s in self._re.split(text) if s]\n\n\n"
        "seg = pysbd.Segmenter() if pysbd is not None else _RegexSegmenter()\n",
    )

    # 3) py3langid 缺失时按字符集粗判
    p = DST / "gsv_tts" / "LangSegment.py"
    patch_text(
        p,
        "import py3langid as langid\n",
        "try:\n"
        "    import py3langid as langid\n"
        "except ImportError:  # 精简运行时：按字符集做粗粒度语种识别\n"
        "    class _FallbackLangid:\n"
        "        @staticmethod\n"
        "        def classify(text):\n"
        "            if re.search(r'[\\u3040-\\u30ff]', text):\n"
        "                return ('ja', 1.0)\n"
        "            if re.search(r'[\\u4e00-\\u9fff]', text):\n"
        "                return ('zh', 1.0)\n"
        "            return ('en', 1.0)\n\n"
        "    langid = _FallbackLangid()\n",
    )


def write_new():
    (DST / "server.py").write_text(SERVER_PY, encoding="utf-8")
    (DST / "config.yaml").write_text(CONFIG_YAML, encoding="utf-8")
    (DST / "download_models.py").write_text(DOWNLOAD_PY, encoding="utf-8")
    (DST / "start.bat").write_text(START_BAT, encoding="utf-8")
    print("[gsvlite] wrote server.py / config.yaml / download_models.py / start.bat")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    args = ap.parse_args()
    src = Path(args.src)
    if not (src / "gsv_tts").is_dir():
        raise SystemExit(f"找不到源码包: {src / 'gsv_tts'}")
    DST.mkdir(parents=True, exist_ok=True)

    dst_pkg = DST / "gsv_tts"
    if dst_pkg.exists():
        shutil.rmtree(dst_pkg)
    shutil.copytree(src / "gsv_tts", dst_pkg, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    lic = src / "LICENSE"
    if lic.exists():
        shutil.copy2(lic, DST / "LICENSE")
    print(f"[gsvlite] copied gsv_tts -> {dst_pkg}")

    patch_all()
    write_new()
    print("[gsvlite] done. 下一步：python .vendor/.gsvlite/download_models.py")


if __name__ == "__main__":
    main()
