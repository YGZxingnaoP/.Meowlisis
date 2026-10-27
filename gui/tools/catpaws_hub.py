# -*- coding: utf-8 -*-
# gui/tools/catpaws_hub.py
# 手机操作（CatPaws）面板后端：配置读写、服务/设备状态、回复流、启动器拉起
import os
import subprocess
import sys
import threading
from pathlib import Path

import requests
import yaml
from flask import jsonify, request, send_file, Response

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / '.vendor' / '.CatPaws' / 'config.yml'
LAUNCHER_DIR = BASE_DIR / '.vendor' / '.CatPaws' / 'catpaws-launcher'
LAUNCHER_CMD = LAUNCHER_DIR / 'start.cmd'

MAIN_API = 'http://127.0.0.1:1800'
CATPAWS_API = 'http://127.0.0.1:18110'
RUNNER_PING = 'http://127.0.0.1:8100/cw/v1/ping'


def _get(url, timeout=3.0):
    try:
        response = requests.get(url, timeout=timeout)
        return response.json() if response.content else {}
    except Exception as exc:
        return {'ok': False, 'message': str(exc)}


def _post(url, payload=None, timeout=8.0):
    try:
        response = requests.post(url, json=payload or {}, timeout=timeout)
        return response.json() if response.content else {}
    except Exception as exc:
        return {'ok': False, 'message': str(exc)}


def read_config():
    """读取 CatPaws 配置文件（唯一真值）"""
    if not CONFIG_PATH.is_file():
        return {}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as handle:
            data = yaml.safe_load(handle) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge(base, patch):
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def write_config(patch):
    """把前端提交的片段合并写回配置文件"""
    data = read_config()
    _merge(data, patch or {})
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix('.yml.tmp')
    with open(tmp, 'w', encoding='utf-8') as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    os.replace(tmp, CONFIG_PATH)
    return data


def runner_status():
    """CatPawsRunner（WDA）探活：直接打设备的 /cw/v1/ping"""
    try:
        response = requests.get(RUNNER_PING, timeout=2.5)
        body = response.json() if response.content else {}
        return {'ok': response.status_code == 200, 'ping': body,
                'detail': body.get('app') or '', 'version': body.get('version') or ''}
    except Exception as exc:
        return {'ok': False, 'message': str(exc)}


def status_payload():
    """面板总状态：服务端 / 模块 / 设备（三路并发探活，避免任一离线拖慢面板）"""
    results = {}

    def worker(name, probe):
        try:
            results[name] = probe()
        except Exception as exc:
            results[name] = {'ok': False, 'message': str(exc)}

    probes = [
        ('server', lambda: _get(CATPAWS_API + '/cw/status', timeout=2.0)),
        ('module', lambda: _get(MAIN_API + '/catpaws/status', timeout=2.0)),
        ('runner', runner_status),
    ]
    threads = [threading.Thread(target=worker, args=(name, probe), daemon=True)
               for name, probe in probes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=4.0)
    vendor = results.get('server') or {'ok': False, 'message': '探测超时'}
    module = results.get('module') or {'ok': False, 'message': '探测超时'}
    runner = results.get('runner') or {'ok': False, 'message': '探测超时'}
    return {
        'status': 'ok',
        'server': {'ok': bool(vendor.get('ok')), 'data': vendor},
        'module': {'ok': bool(module.get('status') == 'ok'), 'data': module},
        'runner': runner,
    }


def _start_launcher():
    """拉起 .CatPaws\\catpaws-launcher（独立窗口，便于看日志）"""
    if not LAUNCHER_CMD.is_file():
        return {'status': 'error', 'message': 'catpaws-launcher/start.cmd 不存在'}
    try:
        if sys.platform == 'win32':
            subprocess.Popen([str(LAUNCHER_CMD)], cwd=str(LAUNCHER_DIR),
                             creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
        else:
            subprocess.Popen([str(LAUNCHER_CMD)], cwd=str(LAUNCHER_DIR),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'status': 'ok', 'message': '已拉起 catpaws-launcher，等它就绪（约 10~30 秒）'}
    except Exception as exc:
        return {'status': 'error', 'message': str(exc)}


def register(app):
    """注册手机操作面板的全部接口"""

    @app.route('/api/catpaws/config', methods=['GET'])
    def _catpaws_config_get():
        return jsonify({'status': 'ok', 'path': str(CONFIG_PATH), 'config': read_config()})

    @app.route('/api/catpaws/config', methods=['POST'])
    def _catpaws_config_post():
        body = request.get_json(silent=True) or {}
        patch = body.get('config') if isinstance(body.get('config'), dict) else body
        if not isinstance(patch, dict) or not patch:
            return jsonify({'status': 'error', 'message': '没有可保存的内容'}), 400
        try:
            data = write_config(patch)
        except Exception as exc:
            return jsonify({'status': 'error', 'message': str(exc)}), 500
        return jsonify({'status': 'ok', 'config': data})

    @app.route('/api/catpaws/status')
    def _catpaws_status():
        return jsonify(status_payload())

    @app.route('/api/catpaws/replies')
    def _catpaws_replies():
        since = request.args.get('since', '0')
        limit = request.args.get('limit', '200')
        data = _get('%s/cw/replies?since=%s&limit=%s' % (CATPAWS_API, since, limit), timeout=3)
        return jsonify(data if isinstance(data, dict) else {'ok': False})

    @app.route('/api/catpaws/ops')
    def _catpaws_ops():
        limit = request.args.get('limit', '200')
        data = _get('%s/cw/ops?limit=%s' % (CATPAWS_API, limit), timeout=3)
        return jsonify(data if isinstance(data, dict) else {'ok': False})

    @app.route('/api/catpaws/screenshot')
    def _catpaws_screenshot():
        edge = request.args.get('max_edge', '720')
        try:
            response = requests.get('%s/cw/screenshot?max_edge=%s' % (CATPAWS_API, edge), timeout=8)
        except Exception as exc:
            return jsonify({'status': 'error', 'message': str(exc)}), 502
        if response.status_code != 200:
            return jsonify({'status': 'error', 'message': 'HTTP %s' % response.status_code}), 502
        return Response(response.content, mimetype='image/png',
                        headers={'Cache-Control': 'no-store'})

    @app.route('/api/catpaws/stream', methods=['POST'])
    def _catpaws_stream():
        body = request.get_json(silent=True) or {}
        return jsonify(_post(CATPAWS_API + '/cw/stream', {'on': bool(body.get('on', True))}))

    @app.route('/api/catpaws/start', methods=['POST'])
    def _catpaws_start():
        body = request.get_json(silent=True) or {}
        goal = str(body.get('goal') or '').strip()
        meowid = str(body.get('meowid') or '').strip()
        if not goal:
            return jsonify({'status': 'error', 'message': '目标不能为空'}), 400
        if not meowid:
            meowid = _first_meowid()
        data = _post(MAIN_API + '/catpaws/start', {'goal': goal, 'meowid': meowid}, timeout=15)
        return jsonify(data if isinstance(data, dict) else {'status': 'error'})

    @app.route('/api/catpaws/stop', methods=['POST'])
    def _catpaws_stop():
        return jsonify(_post(MAIN_API + '/catpaws/stop', {}, timeout=10))

    @app.route('/api/catpaws/answer', methods=['POST'])
    def _catpaws_answer():
        body = request.get_json(silent=True) or {}
        text = str(body.get('text') or '').strip()
        meowid = str(body.get('meowid') or '').strip() or _first_meowid()
        if not text:
            return jsonify({'status': 'error', 'message': '内容为空'}), 400
        data = _post(MAIN_API + '/msg', {'msg': text, 'meowid': meowid, 'source': 'api'}, timeout=15)
        return jsonify(data if isinstance(data, dict) else {'status': 'error'})

    @app.route('/api/catpaws/runner')
    def _catpaws_runner():
        return jsonify(runner_status())

    @app.route('/api/catpaws/launcher', methods=['POST'])
    def _catpaws_launcher():
        return jsonify(_start_launcher())

    @app.route('/api/catpaws/snapshot')
    def _catpaws_snapshot():
        """一次拉全：状态 + 服务列表里的 catpaw/phone 运行情况（面板首屏用）"""
        return jsonify({'status': 'ok', 'panel': status_payload(),
                        'config': read_config()})


def _first_meowid():
    """取第一个非临时身份编号（面板手动启动时用）"""
    try:
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        from func.pipeline.id_signup import IdSignupBridge
        bridge = IdSignupBridge()
        for user in bridge.list_users():
            meowid = str(user.get('meowid') or '').strip()
            if not meowid or meowid.startswith('temp-'):
                continue
            return meowid
    except Exception:
        pass
    return ''
