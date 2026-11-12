# -*- coding: utf-8 -*-
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
        try:
            download(G2P_ZIP, zp)
            unzip(zp, MODELS)
        except Exception as e:
            log(f"g2p 下载失败: {e}")
            log(f"请手动下载并解压到 {MODELS / 'g2p'}：{G2P_ZIP}")
            return
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
