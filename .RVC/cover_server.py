# -*- coding: utf-8 -*-
# RVC 翻唱子服务（精简版）
# 只保留「加载模型 + 人声转换」能力，去掉 gradio WebUI / 训练 / 实时变声。
# 依赖：项目根目录 runtime（Python 3.11 + torch cu128）
import os
import sys
import traceback

RVC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RVC_DIR)

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


@app.route('/api/convert', methods=['POST'])
def convert():
    """人声转换：输入人声干音，输出翻唱音频（wav）。

    body: {
        "model": "kikiV1.pth",           # assets/weights 下的模型名
        "input_path": "D:/xx/vocal.wav", # 输入人声文件绝对路径
        "output_path": "",               # 可选，默认在输入同目录生成 *_cover.wav
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
        sf.write(output_path, audio_opt, tgt_sr)
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
