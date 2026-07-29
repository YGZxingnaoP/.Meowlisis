"""
喵呜配置管理器 - Web GUI
依赖: pip install flask pyyaml
运行: python config_gui.py
访问: http://127.0.0.1:1801
"""
import os
import sys
import json
import yaml
import subprocess
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, request

app = Flask(__name__)
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yml"
GUI_DIR = BASE_DIR / "gui"


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)


def load_tts_config():
    tts_yaml = BASE_DIR / ".Sovits" / "tts_infer.yaml"
    if not tts_yaml.exists():
        return {}
    with open(tts_yaml, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    custom = data.get('custom', {})
    keys = ['device', 'is_half', 't2s_weights_path', 'vits_weights_path',
            'version', 'speed_factor', 'temperature', 'top_k', 'top_p', 'text_split_method']
    return {k: custom.get(k, data.get(k)) for k in keys}


def save_tts_config(cfg):
    tts_yaml = BASE_DIR / ".Sovits" / "tts_infer.yaml"
    if tts_yaml.exists():
        with open(tts_yaml, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    data.setdefault('custom', {}).update(cfg)
    for k in cfg:
        data[k] = cfg[k]
    with open(tts_yaml, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True)


@app.route('/')
def index():
    return send_from_directory(GUI_DIR, 'index.html')


@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(GUI_DIR, path)


@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(load_config())


@app.route('/api/config', methods=['POST'])
def post_config():
    cfg = request.get_json()
    save_config(cfg)
    return jsonify({'status': 'ok'})


@app.route('/api/tts_config', methods=['GET'])
def get_tts_config():
    return jsonify(load_tts_config())


@app.route('/api/tts_config', methods=['POST'])
def post_tts_config():
    cfg = request.get_json()
    save_tts_config(cfg)
    return jsonify({'status': 'ok'})


@app.route('/api/start_main', methods=['POST'])
def start_main():
    try:
        if sys.platform == "win32":
            subprocess.Popen([sys.executable, "api.py"], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([sys.executable, "api.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/start_sovits', methods=['POST'])
def start_sovits():
    try:
        sovits_dir = BASE_DIR / ".Sovits"
        api_path = sovits_dir / "api_v2.py"
        if not api_path.exists():
            return jsonify({'status': 'error', 'message': 'api_v2.py not found'}), 400
        cfg = load_config()
        tts_api = cfg.get('tts', {}).get('api', {})
        host = tts_api.get('host', '127.0.0.1')
        port = tts_api.get('port', 9880)
        infer_path = sovits_dir / "tts_infer.yaml"
        runtime_python = BASE_DIR / "runtime" / "python.exe"
        python = str(runtime_python) if runtime_python.exists() else sys.executable
        args = [python, str(api_path), "-c", str(infer_path), "-a", host, "-p", str(port)]
        env = os.environ.copy()
        ffmpeg_bin = sovits_dir / "FFmpeg" / "bin"
        if ffmpeg_bin.exists():
            env["PATH"] = str(ffmpeg_bin) + os.pathsep + env.get("PATH", "")
        if sys.platform == "win32":
            subprocess.Popen(args, cwd=str(sovits_dir), creationflags=subprocess.CREATE_NEW_CONSOLE, env=env)
        else:
            subprocess.Popen(args, cwd=str(sovits_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/prompt', methods=['GET'])
def get_prompt():
    p = BASE_DIR / "func" / "agent" / "prompt.txt"
    if p.exists():
        return p.read_text(encoding='utf-8')
    return ''


@app.route('/api/prompt', methods=['POST'])
def post_prompt():
    data = request.get_json()
    p = BASE_DIR / "func" / "agent" / "prompt.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data.get('text', ''), encoding='utf-8')
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=1801, debug=False)
