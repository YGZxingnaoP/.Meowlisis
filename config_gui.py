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
from threading import Thread
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


@app.after_request
def _no_cache(response):
    """开发用配置管理器：禁用静态资源缓存，避免前端改动后浏览器仍用旧 JS/CSS"""
    if request.path.endswith(('.js', '.css', '.html')) or request.path == '/':
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


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


@app.route('/api/rewards', methods=['GET'])
def get_rewards():
    from func.rewards.fishcake_store import FishCakeStore
    return jsonify(FishCakeStore().summary(history_limit=6))


@app.route('/api/rewards', methods=['POST'])
def post_rewards():
    try:
        from func.rewards.fishcake_store import FishCakeStore
        store = FishCakeStore()
        body = request.get_json(force=True) or {}
        action = body.get('action', '')
        if action == 'add_kind':
            ok = store.add_kind(body.get('name', ''), body.get('unit', ''),
                                body.get('battery_per_unit', 10),
                                body.get('startup_cost', 1))
            if not ok:
                return jsonify({'status': 'error', 'message': '名称重复或非法'}), 400
        elif action == 'set':
            store.set_fields(body.get('name', ''), unit=body.get('unit'),
                             battery_per_unit=body.get('battery_per_unit'),
                             startup_cost=body.get('startup_cost'))
        elif action == 'adjust':
            try:
                delta = float(body.get('delta', 0))
            except Exception:
                delta = 0
            store.adjust(body.get('name', ''), delta, note=body.get('note', ''))
        elif action == 'remove':
            store.remove_kind(body.get('name', ''))
        else:
            return jsonify({'status': 'error', 'message': '未知动作'}), 400
        return jsonify({'status': 'ok', 'data': store.summary(history_limit=6)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


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


@app.route('/api/mic', methods=['POST'])
def mic_toggle():
    """闭麦开关：转发到主程序 api.py（1800）的 /mic 接口"""
    import requests
    data = request.get_json() or {}
    try:
        r = requests.post('http://127.0.0.1:1800/mic', json=data, timeout=5)
        try:
            return jsonify(r.json())
        except Exception:
            return jsonify({'status': 'error', 'message': f'主程序返回异常: HTTP {r.status_code}'})
    except Exception:
        return jsonify({'status': 'error', 'message': '主程序未启动，请先启动主程序'})


@app.route('/api/audio', methods=['GET'])
def audio_config():
    """音频采集配置 + 可用设备列表"""
    audio = load_config().get('audio', {}) or {}
    devices = []
    try:
        from func.audio import AudioHub
        devices = AudioHub.list_devices()
    except Exception:
        pass
    return jsonify({'config': audio, 'devices': devices})


@app.route('/api/audio', methods=['POST'])
def save_audio_config():
    """保存音频采集配置，并尝试通知主程序运行时切换各源开关"""
    import requests
    data = request.get_json() or {}
    cfg = load_config()
    audio = dict(cfg.get('audio', {}) or {})

    for k in ('rate', 'channels', 'chunk_size_ms'):
        if k in data:
            audio[k] = data[k]

    if 'sources' in data and isinstance(data['sources'], dict):
        audio['sources'] = data['sources']

    cfg['audio'] = audio
    save_config(cfg)

    # 运行时切换各源开关（主程序未启动则忽略，配置下次启动生效）
    try:
        requests.post('http://127.0.0.1:1800/audio/apply',
                      json={'sources': audio.get('sources', {})},
                      timeout=5)
    except Exception:
        pass
    return jsonify({'status': 'ok'})


@app.route('/api/start_napcat', methods=['POST'])
def start_napcat():
    try:
        napcat_dir = BASE_DIR / ".NapCat" / "NapCat.Shell"
        start_bat = napcat_dir / "napcat.quick.bat"
        if start_bat.exists():
            if sys.platform == "win32":
                subprocess.Popen([str(start_bat)], cwd=str(napcat_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen([str(start_bat)], cwd=str(napcat_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return jsonify({'status': 'error', 'message': 'napcat.quick.bat not found'}), 400
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/start_netease', methods=['POST'])
def start_netease():
    """启动网易云搜歌子服务（.NeteaseMusic/server/server.py）"""
    try:
        netease_dir = BASE_DIR / ".NeteaseMusic"
        server_path = netease_dir / "server" / "server.py"
        if not server_path.exists():
            return jsonify({'status': 'error', 'message': 'server.py not found'}), 400
        runtime_python = BASE_DIR / "runtime" / "python.exe"
        python = str(runtime_python) if runtime_python.exists() else sys.executable
        if sys.platform == "win32":
            subprocess.Popen([python, str(server_path)], cwd=str(netease_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([python, str(server_path)], cwd=str(netease_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/start_rvc', methods=['POST'])
def start_rvc():
    """启动 RVC 翻唱子服务（.RVC/cover_server.py）"""
    try:
        rvc_dir = BASE_DIR / ".RVC"
        server_path = rvc_dir / "cover_server.py"
        if not server_path.exists():
            return jsonify({'status': 'error', 'message': 'cover_server.py not found'}), 400
        runtime_python = BASE_DIR / "runtime" / "python.exe"
        python = str(runtime_python) if runtime_python.exists() else sys.executable
        if sys.platform == "win32":
            subprocess.Popen([python, str(server_path)], cwd=str(rvc_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([python, str(server_path)], cwd=str(rvc_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/start_desktopet', methods=['POST'])
def start_desktopet():
    """启动桌宠（.desktopet/start.bat）"""
    try:
        desktopet_dir = BASE_DIR / ".desktopet"
        start_bat = desktopet_dir / "start.bat"
        if not start_bat.exists():
            return jsonify({'status': 'error', 'message': 'start.bat not found'}), 400
        if sys.platform == "win32":
            subprocess.Popen([str(start_bat)], cwd=str(desktopet_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([str(start_bat)], cwd=str(desktopet_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/start_phone', methods=['POST'])
def start_phone():
    """启动手机接口服务（.phone/serve.py）"""
    try:
        phone_dir = BASE_DIR / ".phone"
        serve_path = phone_dir / "serve.py"
        if not serve_path.exists():
            return jsonify({'status': 'error', 'message': 'serve.py not found'}), 400
        runtime_python = BASE_DIR / "runtime" / "python.exe"
        python = str(runtime_python) if runtime_python.exists() else sys.executable
        if sys.platform == "win32":
            subprocess.Popen([python, str(serve_path)], cwd=str(phone_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([python, str(serve_path)], cwd=str(phone_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    """扫描 .Sovits 下可用的 ckpt 与 pth 权重文件（仅用户模型，不含底模）"""
    sovits_dir = BASE_DIR / ".Sovits"
    search_dirs = [
        sovits_dir / "GPT_weights_v2Pro",
        sovits_dir / "SoVITS_weights_v2Pro",
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


@app.route('/api/rvc_models', methods=['GET'])
def get_rvc_models():
    """扫描 .RVC 下可用的翻唱模型（weights）与特征索引（indices）"""
    rvc_dir = BASE_DIR / ".RVC"
    weight_dir = rvc_dir / "assets" / "weights"
    index_dir = rvc_dir / "assets" / "indices"
    models = []
    indices = []
    if weight_dir.exists():
        for p in sorted(weight_dir.rglob('*.pth')):
            models.append(p.name)
    if index_dir.exists():
        for p in sorted(index_dir.rglob('*.index')):
            indices.append(p.name)
    return jsonify({'models': sorted(set(models)), 'indices': sorted(set(indices))})


@app.route('/api/verify_site', methods=['POST'])
def verify_site():
    """验证数据库来源站点是否可爬取（供「来源」配置界面验证按钮调用）"""
    data = request.get_json() or {}
    site = data.get('site', '')
    query = data.get('query', '测试')
    if not site:
        return jsonify({'ok': False, 'message': '缺少站点标识', 'sample': []}), 400
    try:
        from func.database.search.crawler import CatLearnCrawler
        result = CatLearnCrawler().verify_site(site, query)
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e), 'sample': []}), 500


# ============ 知识库预填充 ============
_db_prefill_state = {"running": False, "done": False, "result": 0, "error": ""}


@app.route('/api/db_prefill/start', methods=['POST'])
def db_prefill_start():
    """启动知识库预填充（后台线程爬取真实网页内容入库，供「预填」子球一键调用）"""
    global _db_prefill_state
    if _db_prefill_state.get("running"):
        return jsonify({'ok': False, 'message': '已有预填充任务在运行'}), 409
    data = request.get_json() or {}
    sites = data.get('sites') or []
    keywords = data.get('keywords') or {}
    reset = bool(data.get('reset', True))

    _db_prefill_state = {"running": True, "done": False, "result": 0, "error": ""}

    def _run():
        global _db_prefill_state
        try:
            from func.database.seed import run_seed
            n = run_seed(
                reset=reset,
                sites=list(sites) if sites else None,
                site_keywords=keywords if isinstance(keywords, dict) and keywords else None,
            )
            _db_prefill_state = {"running": False, "done": True, "result": n, "error": ""}
        except Exception as e:
            _db_prefill_state = {"running": False, "done": True, "result": 0, "error": str(e)}

    Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True})


@app.route('/api/db_prefill/status', methods=['GET'])
def db_prefill_status():
    """查询预填充进度（供前端轮询）"""
    return jsonify(_db_prefill_state)


@app.route('/api/db_prefill_config', methods=['GET'])
def db_prefill_config_get():
    """读取预填充配置（独立文件 gui/tools/prefill_seed.json，不混入 config.yml）"""
    path = BASE_DIR / "gui" / "tools" / "prefill_seed.json"
    if not path.exists():
        return jsonify({})
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return jsonify(data if isinstance(data, dict) else {})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/db_prefill_config', methods=['POST'])
def db_prefill_config_post():
    """保存预填充配置到独立文件 gui/tools/prefill_seed.json"""
    data = request.get_json()
    path = BASE_DIR / "gui" / "tools" / "prefill_seed.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data if isinstance(data, dict) else {}, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bili_login/start', methods=['POST'])
def bili_login_start():
    """生成 B站扫码登录二维码（供弹幕/主动回复浏览界面「扫码登录」按钮调用）"""
    data = request.get_json() or {}
    target = data.get('target', 'danmaku')
    try:
        from gui.tools import bili_login
        return jsonify(bili_login.start_login(target))
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500


@app.route('/api/bili_login/check', methods=['POST'])
def bili_login_check():
    """轮询扫码登录状态（供弹幕/主动回复浏览界面轮询调用）"""
    data = request.get_json() or {}
    qrcode_key = data.get('qrcode_key', '')
    target = data.get('target', None)
    try:
        from gui.tools import bili_login
        return jsonify(bili_login.check_login(qrcode_key or None, target))
    except Exception as e:
        return jsonify({'ok': False, 'status': 'error', 'message': str(e)}), 500


@app.route('/api/vts/parameters', methods=['GET'])
def vts_parameters():
    """查询 VTS 当前模型输入参数（供前端「参数」子球调用）"""
    try:
        from gui.tools import vts_query
        emote_cfg = load_config().get('emote', {}) or {}
        ok, payload = vts_query.query_vts_parameters(emote_cfg)
        return jsonify({'ok': ok, 'data': payload})
    except Exception as e:
        return jsonify({'ok': False, 'data': str(e)}), 500


@app.route('/api/verify_sessdata', methods=['POST'])
def verify_sessdata():
    """验证 SESSDATA 是否有效（调用 B站 nav 接口检查登录态，供弹幕配置界面验证按钮调用）"""
    data = request.get_json() or {}
    sessdata = (data.get('sessdata') or '').strip()
    if not sessdata:
        return jsonify({'ok': False, 'message': '请输入 SESSDATA'}), 400
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
            'Referer': 'https://www.bilibili.com/',
        }
        r = requests.get('https://api.bilibili.com/x/web-interface/nav',
                         cookies={'SESSDATA': sessdata}, headers=headers, timeout=10)
        j = r.json()
        code = j.get('code')
        if code == 0 and (j.get('data') or {}).get('isLogin'):
            uname = (j.get('data') or {}).get('uname', '')
            return jsonify({'ok': True, 'message': f'验证成功，已登录：{uname}'})
        if code == -101:
            return jsonify({'ok': False, 'message': 'SESSDATA 无效或已过期（未登录）'})
        return jsonify({'ok': False, 'message': f"验证失败：{j.get('message') or code}"})
    except Exception as e:
        return jsonify({'ok': False, 'message': f'验证异常：{e}'}), 500


# ============ 待办提醒（backlog） ============
def _backlog_dir():
    return BASE_DIR / "character" / "backlog"


def _safe_backlog_name(username):
    import re
    name = str(username or "").strip()
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', name)
    return name or "unnamed"


@app.route('/api/backlog/users', methods=['GET'])
def list_backlog_users():
    d = _backlog_dir()
    if not d.exists():
        return jsonify([])
    names = [f.name[:-5] for f in d.glob('*.json')]
    return jsonify(sorted(names))


@app.route('/api/backlog', methods=['GET'])
def get_backlog():
    user = request.args.get('user', '')
    path = _backlog_dir() / (_safe_backlog_name(user) + '.json')
    if not path.exists():
        return jsonify({'username': user, 'to_do_list': []})
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {'username': user, 'to_do_list': []}
        data.setdefault('username', user)
        data.setdefault('to_do_list', [])
        return jsonify(data)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/backlog', methods=['POST'])
def post_backlog():
    data = request.get_json() or {}
    username = str(data.get('username') or '').strip()
    if not username:
        return jsonify({'status': 'error', 'message': '用户名不能为空'}), 400
    todos = data.get('to_do_list', [])
    if not isinstance(todos, list):
        todos = []
    content = {'username': username, 'to_do_list': todos}
    d = _backlog_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / (_safe_backlog_name(username) + '.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


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


@app.route('/api/armor_prompt', methods=['GET'])
def get_armor_prompt():
    p = BASE_DIR / "character" / "front" / "armor-piercing-prompt.json"
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return jsonify(data)
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500
    return jsonify({})


@app.route('/api/armor_prompt', methods=['POST'])
def post_armor_prompt():
    data = request.get_json()
    content = data if isinstance(data, dict) else {}
    p = BASE_DIR / "character" / "front" / "armor-piercing-prompt.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============ 主动回复 B站浏览（web_browse） ============
def _web_browse_cfg():
    """读取 llm_active.web_browse 节点（带默认值，与后端 AutoWebBrowseConfig 一致）"""
    cfg = load_config() or {}
    la = cfg.get('llm_active', {}) or {}
    return la.get('web_browse', {}) or {}


def _web_browse_dir(key, default):
    """解析 web_browse 目录配置为绝对路径"""
    wb = _web_browse_cfg()
    rel = wb.get(key, default)
    p = (BASE_DIR / rel).resolve() if not os.path.isabs(str(rel)) else Path(rel).resolve()
    return p


@app.route('/api/web_browse/status', methods=['GET'])
def web_browse_status():
    """采集状态：配置 + 缓存数量 + 是否已满"""
    wb = _web_browse_cfg()
    cache_dir = _web_browse_dir('cache_dir', '.temp/web_browse_cache')
    try:
        cache_count = len([
            f for f in os.listdir(cache_dir)
            if f.endswith('.json')
        ]) if cache_dir.is_dir() else 0
    except Exception:
        cache_count = 0
    max_cache = int(wb.get('max_cache', 5) or 5)
    return jsonify({
        'enabled': bool(wb.get('enabled', True)),
        'interval': int(wb.get('interval', 600) or 600),
        'max_cache': max_cache,
        'cache_count': cache_count,
        'is_full': cache_count >= max_cache,
        'frames': int(wb.get('frames', 5) or 5),
        'allow_topics': wb.get('allow_topics', ['二次元', '科普', '游戏']) or [],
        'strictness': wb.get('strictness', 'strict'),
        'forbid_abstract': bool(wb.get('forbid_abstract', True)),
        'mid': int(wb.get('mid', 0) or 0),
    })


@app.route('/api/web_browse/cache', methods=['GET'])
def web_browse_cache():
    """列出缓存目录下的视频摘要 json"""
    cache_dir = _web_browse_dir('cache_dir', '.temp/web_browse_cache')
    items = []
    if cache_dir.is_dir():
        try:
            for f in sorted(os.listdir(cache_dir)):
                if not f.endswith('.json'):
                    continue
                p = cache_dir / f
                try:
                    with open(p, 'r', encoding='utf-8') as fp:
                        data = json.load(fp)
                except Exception:
                    data = {}
                items.append({
                    'file': f,
                    'title': (data or {}).get('title', ''),
                    'uploader': (data or {}).get('uploader', ''),
                    'len': (data or {}).get('len', ''),
                    'topic': (data or {}).get('topic', ''),
                    'tags': (data or {}).get('tags', []) or [],
                    'content': (data or {}).get('content', ''),
                })
        except Exception:
            pass
    return jsonify(items)


@app.route('/api/web_browse/collected', methods=['GET'])
def web_browse_collected():
    """列出已收藏目录（character/shared_videos）下的视频摘要 json"""
    collect_dir = _web_browse_dir('collect_dir', 'character/shared_videos')
    items = []
    if collect_dir.is_dir():
        try:
            for f in sorted(os.listdir(collect_dir)):
                if not f.endswith('.json'):
                    continue
                p = collect_dir / f
                try:
                    with open(p, 'r', encoding='utf-8') as fp:
                        data = json.load(fp)
                except Exception:
                    data = {}
                items.append({
                    'file': f,
                    'title': (data or {}).get('title', ''),
                    'uploader': (data or {}).get('uploader', ''),
                    'len': (data or {}).get('len', ''),
                    'topic': (data or {}).get('topic', ''),
                    'tags': (data or {}).get('tags', []) or [],
                    'content': (data or {}).get('content', ''),
                    'url': (data or {}).get('url', ''),
                })
        except Exception:
            pass
    return jsonify(items)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=1801, debug=False)
