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
from urllib.parse import urlparse
from flask import Flask, send_from_directory, jsonify, request

from gui.tools import speaker_db_tool

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

    # custom 键单独合并，其余键直接覆盖
    custom = cfg.pop('custom', {})
    data.setdefault('custom', {}).update(custom)
    for k, v in cfg.items():
        data[k] = v

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
        gpt_sovits_url = cfg.get('tts', {}).get('gpt-sovits', {}).get('gpt_sovits_url', 'http://127.0.0.1:9880')
        parsed = urlparse(gpt_sovits_url)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or 9880
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


@app.route('/api/start_sensevoice', methods=['POST'])
def start_sensevoice():
    try:
        sensevoice_dir = BASE_DIR / ".SenseVoice"
        start_bat = sensevoice_dir / "start.bat"
        if start_bat.exists():
            if sys.platform == "win32":
                subprocess.Popen([str(start_bat)], cwd=str(sensevoice_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen([str(start_bat)], cwd=str(sensevoice_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            server_path = sensevoice_dir / "server" / "sensevoice_server.py"
            if not server_path.exists():
                return jsonify({'status': 'error', 'message': 'sensevoice_server.py not found'}), 400
            runtime_python = BASE_DIR / "runtime" / "python.exe"
            python = str(runtime_python) if runtime_python.exists() else sys.executable
            if sys.platform == "win32":
                subprocess.Popen([python, str(server_path)], cwd=str(sensevoice_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen([python, str(server_path)], cwd=str(sensevoice_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/character_card', methods=['GET'])
def get_character_card():
    cfg = load_config()
    card_file = request.args.get('file') or (cfg.get('character_card', {}) or {}).get('card_file', 'prompt')
    path = _character_card_path(card_file)
    if not path.exists():
        return jsonify({})
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/character_card', methods=['POST'])
def post_character_card():
    data = request.get_json()
    card_file = data.get('file', 'prompt')
    content = data.get('data', {})
    path = _character_card_path(card_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


def _character_card_path(card_file):
    card_file = card_file or 'prompt'
    if not card_file.endswith('.json'):
        card_file += '.json'
    return BASE_DIR / "character" / "info" / "character_prompt" / card_file


@app.route('/api/character_cards', methods=['GET'])
def list_character_cards():
    d = BASE_DIR / "character" / "info" / "character_prompt"
    if not d.exists():
        return jsonify([])
    files = [f.name for f in d.glob('*.json')]
    return jsonify(sorted(files))


# ============ 声纹管理 ============
@app.route('/api/speakers', methods=['GET'])
def get_speakers():
    return jsonify(speaker_db_tool.list_speakers())


@app.route('/api/speakers/toggle', methods=['POST'])
def toggle_speaker():
    data = request.get_json()
    name = data.get('name', '')
    enabled = data.get('enabled', True)
    return jsonify(speaker_db_tool.toggle_speaker(name, enabled))


@app.route('/api/speakers/build_all', methods=['POST'])
def build_all_speakers():
    try:
        speaker_db_tool.start_build()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/speakers/build_status', methods=['GET'])
def build_status_speakers():
    return jsonify(speaker_db_tool.get_build_status())


@app.route('/api/speakers/create', methods=['POST'])
def create_speaker():
    name = request.form.get('name', '')
    file = request.files.get('wav')
    if not name:
        return jsonify({'status': 'error', 'message': '用户名不能为空'}), 400
    if not file:
        return jsonify({'status': 'error', 'message': '未上传 wav 文件'}), 400
    try:
        result = speaker_db_tool.create_speaker(name, file.read())
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============ 参考音频配置（TTS 用） ============
def _ref_audio_path():
    return BASE_DIR / "character" / "ref_audio" / "config.json"


@app.route('/api/ref_audio', methods=['GET'])
def get_ref_audio():
    path = _ref_audio_path()
    if not path.exists():
        return jsonify({})
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/ref_audio', methods=['POST'])
def post_ref_audio():
    data = request.get_json()
    content = data if isinstance(data, dict) else {}
    path = _ref_audio_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/sovits_models', methods=['GET'])
def get_sovits_models():
    """扫描 .Sovits 下可用的 ckpt 与 pth 权重文件"""
    sovits_dir = BASE_DIR / ".Sovits"
    search_dirs = [
        sovits_dir / "GPT_weights_v2Pro",
        sovits_dir / "SoVITS_weights_v2Pro",
        sovits_dir / "GPT_SoVITS" / "pretrained_models",
    ]
    ckpts = []
    pths = []
    for d in search_dirs:
        if not d.exists():
            continue
        for p in d.rglob('*.ckpt'):
            ckpts.append(str(p.relative_to(sovits_dir)).replace('\\', '/'))
        for p in d.rglob('*.pth'):
            pths.append(str(p.relative_to(sovits_dir)).replace('\\', '/'))
    return jsonify({'ckpt': sorted(set(ckpts)), 'pth': sorted(set(pths))})


@app.route('/api/front_prompt', methods=['GET'])
def get_front_prompt():
    p = BASE_DIR / "character" / "front" / "prompt.json"
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return jsonify(data)
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500
    return jsonify({})


@app.route('/api/front_prompt', methods=['POST'])
def post_front_prompt():
    data = request.get_json()
    content = data if isinstance(data, dict) else {}
    p = BASE_DIR / "character" / "front" / "prompt.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=1801, debug=False)
