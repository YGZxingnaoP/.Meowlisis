# -*- coding: utf-8 -*-
# RVC 翻唱子服务（精简版）
# 只保留「加载模型 + 人声转换」能力，去掉 gradio WebUI / 训练 / 实时变声。
# 依赖：项目根目录 runtime（Python 3.11 + torch cu128）
import os
import sys
import traceback

RVC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RVC_DIR)
# pymss 兜底依赖 pymss_core（位于 .RVC/tools/pymss_core），需要把 tools 加入 sys.path
sys.path.insert(0, os.path.join(RVC_DIR, "tools"))

# RVC 推理代码通过环境变量定位模型/索引/音高模型（统一用绝对路径，避免 cwd 依赖）
os.environ.setdefault("weight_root", os.path.join(RVC_DIR, "assets", "weights"))
os.environ.setdefault("weight_pymss_root", os.path.join(RVC_DIR, "assets", "pymss_weights"))
os.environ.setdefault("index_root", os.path.join(RVC_DIR, "logs"))
os.environ.setdefault("outside_index_root", os.path.join(RVC_DIR, "assets", "indices"))
os.environ.setdefault("rmvpe_root", os.path.join(RVC_DIR, "assets", "rmvpe"))
# 精简服务默认关闭 CUDA Graph，避免 torch nightly 下的兼容问题（如需可设 1 打开）
os.environ.setdefault("RVC_CUDA_GRAPH", "0")

import numpy as np
import soundfile as sf
from flask import Flask, request, jsonify

from configs.config import Config
from infer.vc.modules import VC

app = Flask(__name__)

_config = None
_vc = None


def _get_vc():
    global _config, _vc
    if _vc is None:
        _config = Config()
        _vc = VC(_config)
    return _vc


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


@app.route('/api/models', methods=['GET'])
def list_models():
    weight_root = os.environ["weight_root"]
    models = []
    if os.path.isdir(weight_root):
        for name in os.listdir(weight_root):
            if name.lower().endswith('.pth'):
                models.append(name)
    return jsonify({'models': sorted(models)})


def _classify_stem(filename):
    """按文件名关键词分类 stem：vocal / accomp / harmony / other"""
    name = os.path.basename(filename or "").lower()
    if "back" in name or "harmony" in name:
        return "harmony"
    if "lead" in name:
        return "vocal"
    if "instru" in name or "karaoke" in name or "accomp" in name or "other" in name:
        return "accomp"
    if "voc" in name:
        return "vocal"
    return "other"


def _save_track(audio, sr, output_dir, base, stem):
    """保存单轨为标准命名 {base}_{stem}.wav，返回路径"""
    path = os.path.join(output_dir, f"{base}_{stem}.wav")
    sf.write(path, audio, sr, format="WAV", subtype="PCM_16")
    return path


def _separate_uvr(input_path, output_dir):
    """用 audio_separator 两步 MDX 分离：伴奏 + 主唱 + 和声，返回三轨路径 dict"""
    from audio_separator.separator import Separator
    model_dir = os.path.join(RVC_DIR, "assets", "uvr5_weights", "UVR_onnx")
    base = os.path.splitext(os.path.basename(input_path))[0]

    # audio_separator 返回的是相对文件名（相对 output_dir），转成绝对路径，避免第二步在 cwd 下找不到
    def _abs(p):
        if not p:
            return ""
        if os.path.isabs(p):
            return p
        return os.path.join(output_dir, os.path.basename(p))

    # 第一步：伴奏 / 人声（含和声）
    sep1 = Separator(model_file_dir=model_dir, output_dir=output_dir, output_format="WAV")
    sep1.load_model("UVR-MDX-NET-Inst_HQ_3.onnx")
    files1 = sep1.separate(input_path)

    accomp_path = vocal_mix_path = ""
    for f in files1:
        kind = _classify_stem(f)
        if kind == "accomp":
            accomp_path = _abs(f)
        elif kind == "vocal":
            vocal_mix_path = _abs(f)

    if not accomp_path or not vocal_mix_path:
        raise RuntimeError("Inst_HQ_3 分离结果缺少伴奏或人声轨")

    # 第二步：主唱 / 和声（对人声再分离）
    sep2 = Separator(model_file_dir=model_dir, output_dir=output_dir, output_format="WAV")
    sep2.load_model("UVR_MDXNET_KARA_2.onnx")
    # 用 custom_output_names 让 KARA_2 输出固定无歧义的名字，
    # 避免第一步 "(Vocals)" 前缀残留在第二步文件名里干扰 stem 分类（人声/混音搞反）
    files2 = sep2.separate(
        vocal_mix_path,
        custom_output_names={"vocals": f"{base}_lead", "instrumental": f"{base}_harmony"},
    )

    lead_path = harmony_path = ""
    for f in files2:
        name = os.path.basename(f or "").lower()
        if "lead" in name:
            lead_path = _abs(f)
        elif "harmony" in name:
            harmony_path = _abs(f)

    if not lead_path:
        raise RuntimeError("KARA_2 分离结果缺少主唱轨")

    # 统一重命名为标准三轨
    result = {}
    if lead_path:
        data, sr = sf.read(lead_path, dtype="float32")
        result["vocal_path"] = _save_track(data, sr, output_dir, base, "vocal")
    if accomp_path:
        data, sr = sf.read(accomp_path, dtype="float32")
        result["accomp_path"] = _save_track(data, sr, output_dir, base, "accomp")
    if harmony_path:
        data, sr = sf.read(harmony_path, dtype="float32")
        result["harmony_path"] = _save_track(data, sr, output_dir, base, "harmony")
    else:
        result["harmony_path"] = ""
    return result


def _separate_pymss(input_path, output_dir):
    """pymss karaoke 兜底分离：伴奏 + 人声（无和声），返回三轨路径 dict"""
    from tools.pymss.separator import MSSeparator
    model_path = os.path.join(RVC_DIR, "assets", "pymss_weights",
                              "model_mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt")
    config_path = os.path.join(RVC_DIR, "assets", "pymss_weights",
                               "config_mel_band_roformer_karaoke.yaml")
    separator = MSSeparator(
        model_type="mel_band_roformer",
        model_path=model_path,
        config_path=config_path,
        device="auto",
        output_format="wav",
    )
    try:
        audio, sr = sf.read(input_path, dtype="float32")
        # soundfile 返回 [samples, channels]，pymss 期望 [channels, samples]，需转置
        if audio.ndim == 2:
            audio = audio.T
        results = separator.separate(audio, pbar=False)
        base = os.path.splitext(os.path.basename(input_path))[0]
        vocal_path = os.path.join(output_dir, f"{base}_vocal.wav")
        accomp_path = os.path.join(output_dir, f"{base}_accomp.wav")
        for stem, arr in results.items():
            stem_l = stem.lower()
            if "karaoke" in stem_l or "instru" in stem_l:
                sf.write(accomp_path, arr.T if arr.ndim > 1 else arr, sr,
                         format="WAV", subtype="PCM_16")
            elif "voc" in stem_l or "other" in stem_l:
                sf.write(vocal_path, arr.T if arr.ndim > 1 else arr, sr,
                         format="WAV", subtype="PCM_16")
        if not os.path.exists(vocal_path) or not os.path.exists(accomp_path):
            raise RuntimeError("pymss 分离结果不完整")
        return {
            "vocal_path": vocal_path,
            "accomp_path": accomp_path,
            "harmony_path": "",
        }
    finally:
        separator.close()


@app.route('/api/separate', methods=['POST'])
def separate():
    """人声/伴奏/和声分离：优先 audio_separator 两步 MDX，失败回退 pymss

    body: {
        "input_path": "D:/xx/song.mp3",
        "output_dir": "D:/xx/out"
    }
    返回: {code, vocal_path, accomp_path, harmony_path}
    """
    data = request.get_json(force=True, silent=True) or {}
    input_path = (data.get('input_path') or '').strip()
    output_dir = (data.get('output_dir') or '').strip()

    if not input_path or not os.path.exists(input_path):
        return jsonify({'code': 404, 'msg': '输入音频不存在'}), 404
    if not output_dir:
        return jsonify({'code': 400, 'msg': '缺少 output_dir'}), 400
    os.makedirs(output_dir, exist_ok=True)

    # 优先 audio_separator 两步分离
    try:
        result = _separate_uvr(input_path, output_dir)
        result['code'] = 200
        result['msg'] = 'ok'
        result['backend'] = 'uvr'
        return jsonify(result)
    except Exception as e:
        print("UVR 分离失败，回退 pymss:", str(e))

    # 回退 pymss
    try:
        result = _separate_pymss(input_path, output_dir)
        result['code'] = 200
        result['msg'] = 'ok'
        result['backend'] = 'pymss'
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'code': 500, 'msg': str(e)}), 500


@app.route('/api/convert', methods=['POST'])
def convert():
    """人声转换：输入人声干音，输出翻唱音频（wav）。

    body: {
        "model": "kikiV1.pth",           # assets/weights 下的模型名
        "input_path": "D:/xx/vocal.wav", # 输入人声文件绝对路径
        "output_path": "",               # 可选，默认在输入同目录生成 *_cover.wav
        "index": "",                     # 可选，显式指定索引（绝对路径或 assets/indices 下的文件名），空则自动匹配
        "f0_up_key": 0,                  # 变调（半音，升八度 12）
        "f0_method": "rmvpe",            # rmvpe / pm / fcpe
        "index_rate": 0.75,              # 检索特征占比
        "resample_sr": 0,                # 后处理重采样，0 不重采样
        "rms_mix_rate": 1,               # 音量包络融合比例
        "protect": 0.33                  # 清辅音保护（0.5 不开启）
    }
    """
    data = request.get_json(force=True, silent=True) or {}
    model = (data.get('model') or '').strip()
    input_path = (data.get('input_path') or '').strip()
    output_path = (data.get('output_path') or '').strip()
    index = (data.get('index') or '').strip()
    f0_up_key = int(data.get('f0_up_key', 0) or 0)
    f0_method = data.get('f0_method', 'rmvpe')
    index_rate = float(data.get('index_rate', 0.75) or 0.75)
    resample_sr = int(data.get('resample_sr', 0) or 0)
    rms_mix_rate = float(data.get('rms_mix_rate', 1) or 1)
    protect = float(data.get('protect', 0.33) or 0.33)

    if not model or not input_path:
        return jsonify({'code': 400, 'msg': '缺少 model 或 input_path'}), 400
    if not os.path.exists(input_path):
        return jsonify({'code': 404, 'msg': '输入音频不存在'}), 404

    try:
        vc = _get_vc()
        # 加载模型（sid 传模型文件名），result[3] 为自动匹配到的索引路径
        result = vc.get_vc(model, 0.33, 0.33)
        index_path = ""
        if len(result) > 3 and isinstance(result[3], dict):
            index_path = (result[3].get('value') or '').strip()

        # 显式指定索引：优先使用传入的索引（绝对路径或 assets/indices 下的文件名）
        if index:
            if not os.path.isabs(index):
                base = os.environ.get("outside_index_root", "")
                index = os.path.join(base, index) if base else index
            if os.path.exists(index):
                index_path = index
            else:
                print(f"显式索引不存在，回退自动匹配: {index}")

        info, opt = vc.vc_single(
            0, input_path, f0_up_key, f0_method, index_path,
            index_rate, resample_sr, rms_mix_rate, protect,
        )
        if not opt or opt[0] is None or opt[1] is None:
            return jsonify({'code': 500, 'msg': info or '转换失败'}), 500

        tgt_sr, audio_opt = opt
        if not output_path:
            output_path = os.path.splitext(input_path)[0] + '_cover.wav'
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        sf.write(output_path, audio_opt, tgt_sr, format="WAV", subtype="PCM_16")
        return jsonify({
            'code': 200,
            'msg': 'ok',
            'output_path': output_path,
            'sample_rate': int(tgt_sr),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'code': 500, 'msg': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('RVC_PORT', 7865))
    app.run(host='127.0.0.1', port=port, debug=False)
