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
from threading import Thread, Lock
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, send_from_directory, jsonify, request

from gui.tools import speaker_db_tool

app = Flask(__name__)
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yml"
GUI_DIR = BASE_DIR / "gui"

# 保存互斥：Flask 是多线程的，两个保存请求同时写同一个临时文件会写出半截内容
_save_lock = Lock()


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base, patch):
    """把 patch 合并进 base：**base 里 patch 没有的键原样保留**。

    为什么需要：配置页只认识它 schema 里渲染出来的字段，保存时 post 回来的
    对象里没有"手工加进 config.yml 的键"（例如 `llm.meowllm`、或新增的平台段）。
    以前这里是整体覆盖写 —— 一次保存就把手工加的段**静默删掉**，
    还会把页面加载后又被改过的值回滚（例如 `local_llm_type`）。
    现在改成深合并：只覆盖 patch 里真正出现的键。
    """
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    out = dict(base)
    for key, value in patch.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def save_config(cfg):
    """保存配置。**深合并**到现有文件，避免把页面不认识的键冲掉。

    原子写（临时文件 + os.replace）：主程序有文件监听线程，读到半截 YAML 会解析失败。
    """
    with _save_lock:
        merged = _deep_merge(load_config(), cfg or {})
        _atomic_write(CONFIG_PATH, yaml.dump(merged, allow_unicode=True, sort_keys=False))
        return merged


def _atomic_write(path, text):
    """原子写文本文件：先写同目录临时文件再替换，避免读到写了一半的内容"""
    tmp = Path(str(path) + ".tmp")
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def _notify_reload():
    """通知主程序热重载（主程序没起就忽略；另有文件监听兜底，这里主要为拿回执）"""
    try:
        import requests
        port = (load_config().get('app') or {}).get('port', 1800)
        r = requests.post(f'http://127.0.0.1:{port}/api/config/reload', timeout=3)
        return r.ok
    except Exception:
        return False


def _notify_reload_async():
    """后台通知热重载：reload_all 可能跑几秒，不能挡住保存响应"""
    Thread(target=_notify_reload, daemon=True).start()


def load_tts_config():
    tts_yaml = BASE_DIR / ".vendor/.Sovits" / "tts_infer.yaml"
    if not tts_yaml.exists():
        return {}
    with open(tts_yaml, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    custom = data.get('custom', {})
    keys = ['device', 'is_half', 't2s_weights_path', 'vits_weights_path',
            'version', 'speed_factor', 'temperature', 'top_k', 'top_p', 'text_split_method']
    return {k: custom.get(k, data.get(k)) for k in keys}


def save_tts_config(cfg):
    tts_yaml = BASE_DIR / ".vendor/.Sovits" / "tts_infer.yaml"
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
    _notify_reload_async()
    return jsonify({'status': 'ok', 'hot_reload': 'queued'})


def _apply_updates(root, updates):
    """把 [{path: 'a.b.c', value: x}] 还原成嵌套 dict，供深合并使用"""
    for it in updates or []:
        path = (it or {}).get('path')
        if not path:
            continue
        cur = root
        keys = path.split('.')
        for k in keys[:-1]:
            nxt = cur.get(k)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[k] = nxt
            cur = nxt
        cur[keys[-1]] = (it or {}).get('value')
    return root


@app.route('/api/config/patch', methods=['POST'])
def post_config_patch():
    """增量保存：前端只提交真正改过的路径，服务端深合并后一次性写盘。

    热重载通知放到后台线程，保存响应不等主程序跑完 reload_all（那一步可能几秒）。
    """
    data = request.get_json(silent=True) or {}
    updates = data.get('updates') or []
    patch = _apply_updates({}, updates)
    if patch:
        save_config(patch)
    _notify_reload_async()
    return jsonify({'status': 'ok', 'hot_reload': 'queued', 'changed': len(updates)})


class _MeowLLMConfigIO:
    """配置页对 `.vendor/.MeowLLM/config.yml` 的读写。

    这个文件是**服务端自己的配置**（paths / context / engine / memory / gen / thinking），
    由 MeowLLM 读取，配置页只是给它做一个编辑界面。所以这里直接读写该文件，
    不再经过项目侧的 `func/meowllm/`（该目录已删除：meowllm 是与 deepseek/aliyun
    并列的平台，`func/` 下不允许有平台级目录）。
    """

    MEOWLLM_CFG = BASE_DIR / ".vendor" / ".MeowLLM" / "config.yml"

    def __init__(self):
        self._cache = None

    def config_path(self) -> str:
        return str(self.MEOWLLM_CFG)

    def data(self, force: bool = False) -> dict:
        if self._cache is None or force:
            raw = {}
            if self.MEOWLLM_CFG.exists():
                with open(self.MEOWLLM_CFG, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            self._cache = raw.get("meowllm", raw) or {}
        return self._cache

    def base_url(self) -> str:
        """服务端当前地址。优先运行期写的 port.json，其次项目 config.yml 的 llm.meowllm。"""
        node = self.data()
        state_dir = ((node.get("paths") or {}).get("state_dir") or ".test/state/meowllm")
        state_path = (BASE_DIR / ".vendor" / ".MeowLLM" / str(state_dir) / "port.json")
        try:
            if state_path.is_file():
                with open(state_path, "r", encoding="utf-8") as f:
                    info = json.load(f) or {}
                if info.get("base_url"):
                    return str(info["base_url"])
        except Exception:
            pass
        meow = (load_config().get("llm") or {}).get("meowllm") or {}
        return str(meow.get("base_url") or "http://127.0.0.1:18100/meowllm/v1")

    def save(self, node: dict) -> dict:
        raw = {}
        if self.MEOWLLM_CFG.exists():
            try:
                with open(self.MEOWLLM_CFG, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            except Exception:
                raw = {}
        # 改之前留一份 .bak（config.yml.bak 已在 .gitignore 里）
        try:
            bak = self.MEOWLLM_CFG.with_suffix(".yml.bak")
            bak.write_bytes(self.MEOWLLM_CFG.read_bytes())
        except Exception:
            pass
        raw["meowllm"] = node
        self.MEOWLLM_CFG.parent.mkdir(parents=True, exist_ok=True)
        with open(self.MEOWLLM_CFG, "w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
        self._cache = node
        return {"status": "ok", "path": str(self.MEOWLLM_CFG)}


_MEOWLLM_IO = _MeowLLMConfigIO()


def _meowllm_io():
    return _MEOWLLM_IO


@app.route('/api/meowllm/config', methods=['GET'])
def get_meowllm_config():
    io = _meowllm_io()
    return jsonify({'path': io.config_path(), 'data': io.data(force=True)})


# ==================== MeowLLM 子服务控制面（代理） ====================
# 配置页跑在 1801，MeowLLM 在 18100（或被占用后的回退端口）。
# 浏览器直连子服务是跨域，所以「状态探测 / 重载」都从这里代理一次。
# 只放行下面白名单里的路径 —— 这是配置页真正用到的全部，别的一律 404。
# 注意：dmem/write、dmem/forget 刻意**不**放行 —— 记忆的写入属于主项目运行时行为
# （func/catbrain/.../dmem_bridge.py），不该能从配置页手工灌进去。
_MEOWLLM_CONTROL = {
    'health', 'stats', 'version', 'reload', 'session/reset',
    'dmem/status',
}


def _meowllm_control_base():
    """从 meowllm 的 OpenAI 兼容地址（.../meowllm/v1）推出控制面根地址。"""
    io = _meowllm_io()
    url = str(io.base_url() or '').rstrip('/')
    root = url[:-3] if url.endswith('/v1') else url
    return root + '/control'


@app.route('/api/meowllm/control/<path:sub>', methods=['GET', 'POST'])
def proxy_meowllm_control(sub):
    """把 /api/meowllm/control/x 转给子服务的 /meowllm/control/x。"""
    import urllib.error
    import urllib.request

    sub = (sub or '').strip().strip('/')
    if sub not in _MEOWLLM_CONTROL:
        return jsonify({'error': f'不支持的控制面路径: {sub}'}), 404

    payload = None
    if request.method == 'POST':
        payload = json.dumps(request.get_json(silent=True) or {}).encode('utf-8')
    req = urllib.request.Request(
        f'{_meowllm_control_base()}/{sub}', data=payload, method=request.method,
        headers={'Content-Type': 'application/json; charset=utf-8',
                 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read().decode('utf-8', 'replace')
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')
        status = exc.code
    except Exception as exc:  # noqa: BLE001 - 子服务没起、端口没开、DNS 之类
        return jsonify({'error': f'子服务不可达（{type(exc).__name__}: {exc}）'}), 502
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        data = {'raw': body}
    return jsonify(data), status


@app.route('/api/meowllm/config', methods=['POST'])
def post_meowllm_config():
    io = _meowllm_io()
    payload = request.get_json() or {}
    node = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(node, dict):
        node = payload
    data = io.save(node)
    return jsonify({'status': 'ok', 'data': data})


# ==================== 插件（独立配置文件） ====================
PLUGINS_DIR = BASE_DIR / "plugins"


def _plugin_schema_io():
    """延迟导入插件 schema 工具（避免未安装依赖时影响主配置）"""
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from func.toolbox.plugins import schema_io
    return schema_io


def _plugin_dir(plugin_id):
    """解析插件目录并防止路径穿越"""
    if not plugin_id or plugin_id in (".", "..") or "/" in plugin_id or "\\" in plugin_id:
        return None
    try:
        path = (PLUGINS_DIR / plugin_id).resolve()
        root = PLUGINS_DIR.resolve()
    except Exception:
        return None
    if root != path and root not in path.parents:
        return None
    return path if path.is_dir() else None


@app.route('/api/plugins', methods=['GET'])
def get_plugins():
    """返回全部插件元信息与配置字段（含独立配置）"""
    schema_io = _plugin_schema_io()
    items = []
    for pid, pdir, meta, cards, fields in schema_io.list_plugins(str(PLUGINS_DIR)):
        cfg = schema_io.ensure_config(pdir, meta, fields)
        items.append({
            "id": pid,
            "title": meta.get("title") or pid,
            "version": meta.get("version") or "",
            "group": meta.get("group") or "core",
            "emoji": meta.get("emoji") or "\U0001F9E9",
            "enabled": bool(cfg.get("enabled", meta.get("default_enabled", True))),
            "cards": cards,
            "fields": fields,
        })
    return jsonify(items)


@app.route('/api/plugins/card', methods=['GET'])
def get_plugins_card():
    """插件父卡卡面（plugins/card.png，缺失返回 404，前端回落 emoji）"""
    return send_from_directory(str(PLUGINS_DIR), 'card.png')


@app.route('/api/plugins/<plugin_id>/card', methods=['GET'])
def get_plugin_card(plugin_id):
    """插件卡面（plugins/<id>/card.png）"""
    pdir = _plugin_dir(plugin_id)
    if not pdir:
        return jsonify({'status': 'error', 'message': 'invalid plugin id'}), 400
    return send_from_directory(str(pdir), 'card.png')


@app.route('/api/plugins/<plugin_id>/config', methods=['GET'])
def get_plugin_config(plugin_id):
    """读取插件独立配置文件"""
    schema_io = _plugin_schema_io()
    pdir = _plugin_dir(plugin_id)
    if not pdir:
        return jsonify({'status': 'error', 'message': 'invalid plugin id'}), 400
    meta, _cards, fields = schema_io.load_schema(str(pdir))
    return jsonify(schema_io.ensure_config(str(pdir), meta, fields))


@app.route('/api/plugins/<plugin_id>/config', methods=['POST'])
def post_plugin_config(plugin_id):
    """保存插件独立配置文件"""
    schema_io = _plugin_schema_io()
    pdir = _plugin_dir(plugin_id)
    if not pdir:
        return jsonify({'status': 'error', 'message': 'invalid plugin id'}), 400
    data = request.get_json() or {}
    schema_io.write_config(str(pdir), data)
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
        sovits_dir = BASE_DIR / ".vendor/.Sovits"
        api_path = sovits_dir / "api_v2.py"
        if not api_path.exists():
            return jsonify({'status': 'error', 'message': 'api_v2.py not found'}), 400
        cfg = load_config()
        gpt_sovits_url = cfg.get('tts', {}).get('gpt-sovits', {}).get('gpt_sovits_url', 'http://127.0.0.1:9880')
        parsed = urlparse(gpt_sovits_url)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or 9880
        infer_path = sovits_dir / "tts_infer.yaml"
        runtime_python = BASE_DIR / "runtime" / "311" / "python.exe"
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
        sensevoice_dir = BASE_DIR / ".vendor/.SenseVoice"
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
            runtime_python = BASE_DIR / "runtime" / "311" / "python.exe"
            python = str(runtime_python) if runtime_python.exists() else sys.executable
            if sys.platform == "win32":
                subprocess.Popen([python, str(server_path)], cwd=str(sensevoice_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen([python, str(server_path)], cwd=str(sensevoice_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/start_painting_comfy', methods=['POST'])
def start_painting_comfy():
    """启动内置 ComfyUI 绘画引擎（后台执行，不阻塞）"""
    try:
        import threading
        from func.toolbox.flux_painter.config import TBFluxPainterConfig
        from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter

        def _boot():
            try:
                get_managed_painter(TBFluxPainterConfig()).start()
            except Exception:
                pass

        threading.Thread(target=_boot, daemon=True).start()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/stop_painting_comfy', methods=['POST'])
def stop_painting_comfy():
    """停止由本面板启动的内置引擎（外部自建服务不受影响）"""
    try:
        from func.toolbox.flux_painter.config import TBFluxPainterConfig
        from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter
        get_managed_painter(TBFluxPainterConfig()).stop()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/painting_comfy_status', methods=['GET'])
def painting_comfy_status():
    """查询内置引擎是否在线（常驻服务：返回 pid/启动时间）"""
    try:
        from func.toolbox.flux_painter.config import TBFluxPainterConfig
        from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter
        cfg = TBFluxPainterConfig()
        mgr = get_managed_painter(cfg)
        running = mgr.health()
        pid, started = mgr._load_pid()
        own = bool(pid) and mgr._pid_alive(pid)
        return jsonify({'running': running,
                        'pid': pid if (running and own) else None,
                        'started_at': started if (running and own) else '',
                        'resident': bool(running and own),
                        'url': f"http://127.0.0.1:{cfg.comfy_port}"})
    except Exception as e:
        return jsonify({'running': False, 'message': str(e)})


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
        napcat_dir = BASE_DIR / ".vendor/.NapCat" / "NapCat.Shell"
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
    """启动网易云搜歌子服务（.vendor/.NeteaseMusic/server/server.py）"""
    try:
        netease_dir = BASE_DIR / ".vendor/.NeteaseMusic"
        server_path = netease_dir / "server" / "server.py"
        if not server_path.exists():
            return jsonify({'status': 'error', 'message': 'server.py not found'}), 400
        runtime_python = BASE_DIR / "runtime" / "311" / "python.exe"
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
    """启动 RVC 翻唱子服务（.vendor/.RVC/cover_server.py）"""
    try:
        rvc_dir = BASE_DIR / ".vendor/.RVC"
        server_path = rvc_dir / "cover_server.py"
        if not server_path.exists():
            return jsonify({'status': 'error', 'message': 'cover_server.py not found'}), 400
        runtime_python = BASE_DIR / "runtime" / "311" / "python.exe"
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
    """启动桌宠（.vendor/.desktopet/start.bat）"""
    try:
        desktopet_dir = BASE_DIR / ".vendor/.desktopet"
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
    """启动手机接口服务（.vendor/.cam/serve.py）"""
    try:
        phone_dir = BASE_DIR / ".vendor/.cam"
        serve_path = phone_dir / "serve.py"
        if not serve_path.exists():
            return jsonify({'status': 'error', 'message': 'serve.py not found'}), 400
        runtime_python = BASE_DIR / "runtime" / "311" / "python.exe"
        python = str(runtime_python) if runtime_python.exists() else sys.executable
        if sys.platform == "win32":
            subprocess.Popen([python, str(serve_path)], cwd=str(phone_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([python, str(serve_path)], cwd=str(phone_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/start_catpaw', methods=['POST'])
def start_catpaw():
    """启动 CatPaws iPhone 控制服务（.vendor/.CatPaws/src/server.py，与主项目共用 runtime）"""
    try:
        catpaw_dir = BASE_DIR / ".vendor/.CatPaws"
        server_path = catpaw_dir / "src" / "server.py"
        if not server_path.exists():
            return jsonify({'status': 'error', 'message': 'src/server.py not found'}), 400
        runtime_python = BASE_DIR / "runtime" / "311" / "python.exe"
        python = str(runtime_python) if runtime_python.exists() else sys.executable
        if sys.platform == "win32":
            subprocess.Popen([python, str(server_path)], cwd=str(catpaw_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([python, str(server_path)], cwd=str(catpaw_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    nickname = request.form.get('nickname', '') or request.form.get('name', '')
    uid = request.form.get('id', '')
    file = request.files.get('wav')
    if not nickname:
        return jsonify({'status': 'error', 'message': '昵称不能为空'}), 400
    if not file:
        return jsonify({'status': 'error', 'message': '未上传 wav 文件'}), 400
    try:
        result = speaker_db_tool.create_speaker(nickname, file.read(), uid)
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
    """扫描 .vendor/.Sovits 下可用的 ckpt 与 pth 权重文件（仅用户模型，不含底模）"""
    sovits_dir = BASE_DIR / ".vendor/.Sovits"
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
    """扫描 .vendor/.RVC 下可用的翻唱模型（weights）与特征索引（indices）"""
    rvc_dir = BASE_DIR / ".vendor/.RVC"
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
# ==================== 用户 ID（身份表） ====================
def _identity_bridge():
    """延迟导入身份桥接，避免未装依赖时影响配置管理器"""
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from func.pipeline.id_signup import IdSignupBridge
    return IdSignupBridge()


@app.route('/api/identity/users', methods=['GET'])
def identity_users():
    """列出全部用户：编号、昵称、各平台账号、好感度"""
    bridge = _identity_bridge()
    users = []
    for user in bridge.list_users():
        meowid = str(user.get('meowid') or '')
        profile = bridge.profile_of(meowid)
        users.append({
            'meowid': meowid,
            'nickname': str(user.get('nickname') or ''),
            'ext_accounts': user.get('ext_accounts') or {},
            'affinity': profile.get('affinity', 0),
            'birthday': str(profile.get('birthday') or ''),
            'summary': bridge.summary(meowid),
        })
    return jsonify(users)


@app.route('/api/identity/user', methods=['GET'])
def identity_user():
    """查单个用户详情：ref 支持 meowid / 昵称 / QQ号 / B站uid 四种写法"""
    key = str(request.args.get('ref', '') or '').strip()
    bridge = _identity_bridge()
    if key and not bridge.find(key):
        # 编号、昵称都没命中，再按各平台账号找（QQ号 / B站uid / 声纹名）
        try:
            from func.catbrain.UserMemory.identity.store import KNOWN_CHANNELS
            for channel in KNOWN_CHANNELS:
                meowid = bridge.resolve(channel, key)
                if meowid and not bridge._store().is_temp(meowid):
                    key = meowid
                    break
        except Exception:
            pass
    return jsonify(bridge.user_detail(key))


@app.route('/api/identity/nickname', methods=['POST'])
def identity_nickname():
    """改昵称"""
    data = request.get_json() or {}
    ok, msg = _identity_bridge().set_nickname(str(data.get('meowid') or ''), str(data.get('nickname') or ''))
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg})


@app.route('/api/identity/bind', methods=['POST'])
def identity_bind():
    """绑定平台账号"""
    data = request.get_json() or {}
    ok, msg, _owner = _identity_bridge().bind(
        str(data.get('meowid') or ''), str(data.get('channel') or ''), str(data.get('ext_account') or ''))
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg})


@app.route('/api/identity/unbind', methods=['POST'])
def identity_unbind():
    """解绑平台账号"""
    data = request.get_json() or {}
    ok, msg = _identity_bridge().unbind(str(data.get('meowid') or ''), str(data.get('channel') or ''))
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg})


@app.route('/api/identity/lookup', methods=['GET'])
def identity_lookup():
    """按昵称反查 B站 uid"""
    uid, err = _identity_bridge().lookup_bili(request.args.get('keyword', ''))
    return jsonify({'uid': uid, 'message': err})


def _backlog_dir():
    return BASE_DIR / "character" / "backlog"


def _safe_backlog_name(username):
    import re
    name = str(username or "").strip()
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', name)
    return name or "unnamed"


@app.route('/api/backlog/users', methods=['GET'])
def list_backlog_users():
    """列出有待办的用户（编号目录 + 老目录）"""
    return jsonify([name for name, _data in _identity_bridge().backlog_entries()])


@app.route('/api/backlog', methods=['GET'])
def get_backlog():
    """读某个用户的待办"""
    user = request.args.get('user', '')
    data = _identity_bridge().read_backlog(user)
    if not data:
        return jsonify({'username': user, 'to_do_list': []})
    data.setdefault('username', user)
    data.setdefault('to_do_list', [])
    return jsonify(data)


@app.route('/api/backlog', methods=['POST'])
def post_backlog():
    """写某个用户的待办"""
    data = request.get_json() or {}
    username = str(data.get('username') or '').strip()
    if not username:
        return jsonify({'status': 'error', 'message': '用户名不能为空'}), 400
    todos = data.get('to_do_list', [])
    if not isinstance(todos, list):
        todos = []
    try:
        _identity_bridge().save_backlog(username, {'username': username, 'to_do_list': todos})
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


# ===== 日志中心：/logs 页面 + 各服务无窗口启动（gui/tools/loghub.py） =====
try:
    from gui.tools import loghub
    loghub.register(app, BASE_DIR, GUI_DIR)
except Exception as _loghub_e:
    print('[loghub] 注册失败:', _loghub_e)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=1801, debug=False)
