import os
import sys
import base64
import socket
import shutil
import threading
import time
import datetime
import subprocess

from flask import Flask, request, send_from_directory, Response, jsonify
import requests
from werkzeug.serving import WSGIRequestHandler, make_server

import config as phone_config
from tts_relay import TtsRelay
from audio_gateway import AudioGateway
from ws_hub import WsHub

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = phone_config.BASE_DIR
PROJECT_DIR = phone_config.PROJECT_DIR
DESKTOPET_DIR = phone_config.DESKTOPET_DIR
STATIC_DIR = phone_config.STATIC_DIR
CERT_PEM = phone_config.CERT_PEM
KEY_PEM = phone_config.KEY_PEM
API_BASE = phone_config.API_BASE
HOST = phone_config.HOST
PORT = phone_config.HTTPS_PORT

app = Flask(__name__, static_folder=None)

phone_config.apply_project_config()
def _read_mode():
    """读取持久化的模式（没有记录时用默认模式）"""
    try:
        with open(phone_config.MODE_FILE, 'r', encoding='utf-8') as f:
            m = f.read().strip()
        if m in ('call', 'chat'):
            return m
    except Exception:
        pass
    return phone_config.DEFAULT_MODE


def _write_mode(mode):
    """持久化模式，避免重启后静默回到聊天"""
    try:
        with open(phone_config.MODE_FILE, 'w', encoding='utf-8') as f:
            f.write('call' if mode == 'call' else 'chat')
    except Exception:
        pass


tts_relay = TtsRelay(phone_config.TTS_MAX_BLOCKS, phone_config.TTS_PENDING_LIMIT,
                     phone_config.TTS_META_HOLD_SECS,
                     phone_config.TTS_MAX_PENDING_BYTES,
                     phone_config.TTS_MAX_BLOCK_BYTES)
tts_relay.set_mode(_read_mode())
audio_gateway = AudioGateway(
    API_BASE,
    target_rate=phone_config.AUDIO_TARGET_RATE,
    frame_bytes=phone_config.AUDIO_FRAME_BYTES,
    converter=phone_config.AUDIO_RESAMPLE_CONVERTER,
    energy_threshold=phone_config.AUDIO_ENERGY_THRESHOLD,
    silence_secs=phone_config.AUDIO_SILENCE_SECS,
    max_utterance_secs=phone_config.AUDIO_MAX_UTTERANCE_SECS,
    send_timeout=phone_config.AUDIO_SEND_TIMEOUT,
    batch_secs=phone_config.AUDIO_SEND_BATCH_SECS,
    log=print,
)
ws_hub = WsHub(on_audio=audio_gateway.feed, gop_max=phone_config.VIDEO_GOP_MAX)


class PhoneRequestHandler(WSGIRequestHandler):
    """在同一 HTTPS 端口上拦截 /ws 升级，其余请求交回 Flask"""

    def run_wsgi(self):
        """识别 WebSocket 升级并接管连接"""
        is_ws = (self.headers.get('Upgrade', '').lower() == 'websocket'
                 and bool(self.headers.get('Sec-WebSocket-Key'))
                 and self.path.split('?')[0] == '/ws')
        if is_ws:
            self.close_connection = True
            try:
                ws_hub.serve(self.connection, self.headers)
            except Exception:
                pass
            return
        return super().run_wsgi()


@app.route('/')
def index():
    """手机端主页"""
    return send_from_directory(STATIC_DIR, 'index.html')


@app.route('/cam')
def cam_page():
    """电脑端观看页"""
    return send_from_directory(STATIC_DIR, 'cam.html')


@app.route('/debug')
def debug_page():
    """手机音频诊断页（看当前模式与最近收到的流）"""
    return send_from_directory(STATIC_DIR, 'debug.html')


@app.route('/static/<path:p>')
def phone_static(p):
    """手机端与观看端的静态资源（禁用缓存，保证前端改动即时生效）"""
    resp = send_from_directory(STATIC_DIR, p)
    resp.headers['Cache-Control'] = 'no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.route('/pet/<path:p>')
def pet_files(p):
    """把 .desktopet 暴露为 /pet/ 供 iframe 加载桌宠"""
    return send_from_directory(DESKTOPET_DIR, p)


def _proxy(path, method='GET', **kw):
    """反向代理到主程序 api.py"""
    url = API_BASE + path
    timeout = 60 if method == 'POST' else 15
    try:
        if method == 'POST':
            r = requests.post(url, timeout=timeout, **kw)
        else:
            r = requests.get(url, timeout=timeout, **kw)
        return Response(r.content, status=r.status_code,
                        content_type=r.headers.get('Content-Type', 'application/json'))
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return Response('{"status":"error","message":"主程序 api.py 未启动或无响应"}',
                        status=502, content_type='application/json')


@app.route('/api/chat')
def api_chat():
    """文字对话代理"""
    name = request.args.get('username')
    if name:
        audio_gateway.set_username(name)
    return _proxy('/chat', params=request.args)


@app.route('/api/msg', methods=['POST'])
def api_msg():
    """文字消息代理"""
    return _proxy('/msg', method='POST', json=request.get_json(silent=True) or {})


@app.route('/api/say', methods=['POST'])
def api_say():
    """TTS 复读代理"""
    return _proxy('/say', method='POST', data=request.get_data())


@app.route('/api/audio/send', methods=['POST'])
def api_audio_send():
    """语音上传代理"""
    return _proxy('/audio/send', method='POST', data=request.get_data(), params=request.args)


@app.route('/api/audio/end', methods=['POST'])
def api_audio_end():
    """说话结束代理"""
    return _proxy('/audio/end', method='POST', data=b'')


@app.route('/api/phone/audio')
def api_phone_audio():
    """识别字幕代理"""
    return _proxy('/phone/audio', params=request.args)


@app.route('/api/chatreply')
def api_chatreply():
    """AI 回复文字代理"""
    return _proxy('/chatreply', params=request.args)


@app.route('/api/tts')
def api_tts():
    """整句 TTS 代理"""
    return _proxy('/tts/audio', params=request.args)


@app.route('/api/mic', methods=['POST'])
def api_mic():
    """闭麦开关代理"""
    return _proxy('/mic', method='POST', json=request.get_json(silent=True) or {})


@app.route('/api/tts/phone', methods=['POST'])
def tts_phone_push():
    """主程序推流入口：?start=1 开句 / ?end=1 结句 / body 为 PCM 块"""
    if request.args.get('start'):
        tts_relay.start_meta(request.get_json(silent=True) or {})
        return 'ok'
    if request.args.get('end'):
        tts_relay.end_meta()
        return 'ok'
    tts_relay.push(request.get_data())
    return 'ok'


@app.route('/api/tts/pending')
def tts_phone_pending():
    """手机轮询增量音频块（带当前模式）"""
    seq = request.args.get('seq', type=int, default=-1)
    return jsonify(tts_relay.pending(seq))


@app.route('/api/mode', methods=['GET', 'POST'])
def api_mode():
    """查询或切换 聊天|通话 模式"""
    if request.method == 'POST':
        mode = request.args.get('mode')
        if not mode:
            mode = (request.get_json(silent=True) or {}).get('mode')
        tts_relay.set_mode(mode)
        _write_mode(tts_relay.get_mode())
    return jsonify({'mode': tts_relay.get_mode()})


@app.route('/api/tts/debug')
def tts_debug():
    """排查用：最近若干条手机音频流的来源/保留/字节数"""
    return jsonify(tts_relay.debug())


def start_obs_http():
    """OBS 浏览器源专用：纯 HTTP 的观看页 + WebSocket（OBS 不接受自签名 HTTPS）"""
    obs = Flask('obs-http', static_folder=None)

    @obs.route('/')
    @obs.route('/cam')
    def obs_cam():
        return send_from_directory(STATIC_DIR, 'cam.html')

    @obs.route('/static/<path:p>')
    def obs_static(p):
        resp = send_from_directory(STATIC_DIR, p)
        resp.headers['Cache-Control'] = 'no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        return resp

    @obs.route('/pet/<path:p>')
    def obs_pet_file(p):
        return send_from_directory(DESKTOPET_DIR, p)

    @obs.route('/pet')
    @obs.route('/pet/')
    def obs_pet_index():
        return send_from_directory(DESKTOPET_DIR, 'renderer/index.html')

    srv = make_server(HOST, phone_config.PET_HTTP_PORT, obs, threaded=True,
                      request_handler=PhoneRequestHandler)
    threading.Thread(target=srv.serve_forever, daemon=True, name='obs-http').start()
    return srv


def ensure_cert():
    """生成或复用自签名证书"""
    if os.path.exists(CERT_PEM) and os.path.exists(KEY_PEM):
        return CERT_PEM, KEY_PEM
    os.makedirs(phone_config.CERT_DIR, exist_ok=True)
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u'MeowlisisPhone'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u'Meowlisis'),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=1))
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(u'localhost')]), critical=False)
            .sign(key, hashes.SHA256())
        )
        with open(KEY_PEM, 'wb') as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
        with open(CERT_PEM, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        print('[phone] 已生成自签名证书 ->', CERT_PEM)
        return CERT_PEM, KEY_PEM
    except Exception as e:
        print(f'[phone] cryptography 生成证书失败: {e}')
    openssl = shutil.which('openssl')
    if openssl:
        try:
            subprocess.run(
                [openssl, 'req', '-x509', '-newkey', 'rsa:2048',
                 '-keyout', KEY_PEM, '-out', CERT_PEM,
                 '-days', '3650', '-nodes', '-subj', '//CN=MeowlisisPhone'],
                check=True, capture_output=True,
            )
            print('[phone] 已通过 openssl 生成自签名证书')
            return CERT_PEM, KEY_PEM
        except Exception as e:
            print(f'[phone] openssl 生成证书失败: {e}')
    return None


def lan_ip():
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '127.0.0.1'


if __name__ == '__main__':
    print('=' * 58)
    print('  喵呜手机界面服务 (.phone)')
    print('=' * 58)
    ip = lan_ip()
    cert = ensure_cert()
    try:
        start_obs_http()
        obs_url = f'http://127.0.0.1:{phone_config.PET_HTTP_PORT}/cam'
    except Exception as e:
        obs_url = '(开启失败: %s)' % e
    if cert:
        cert_pem, key_pem = cert
        print(f'  手机请访问: https://{ip}:{PORT}')
        print(f'  电脑观看页: https://{ip}:{PORT}/cam')
        print(f'  OBS 浏览器源: {obs_url}')
        print(f'  音频诊断页: https://{ip}:{PORT}/debug')
        print(f'  当前模式: {"通话（手机听全部）" if tts_relay.get_mode() == "call" else "聊天（只放手机自己的对话）"}')
        print('  首次访问有证书警告 -> 点「高级 / 继续前往」即可')
        print('=' * 58)
        app.run(host=HOST, port=PORT, ssl_context=(cert_pem, key_pem), debug=False,
                threaded=True, request_handler=PhoneRequestHandler)
    else:
        print('[警告] 无法生成 HTTPS 证书，回退 HTTP（浏览器将无法授权摄像头/麦克风）')
        print(f'  手机请访问: http://{ip}:{PORT}')
        print('=' * 58)
        app.run(host=HOST, port=PORT, debug=False, threaded=True,
                request_handler=PhoneRequestHandler)
