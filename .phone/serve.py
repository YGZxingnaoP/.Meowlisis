# -*- coding: utf-8 -*-
"""
.phone 手机界面独立服务（不改原项目，独立运行）

功能：
  1. 提供 HTTPS 静态页面（手机看桌宠 + 按住说话）
  2. 反向代理到主程序 api.py（http://127.0.0.1:1800），解决手机端跨域问题
  3. 首次启动自动生成自签名证书并落盘复用（.phone/cert/）

用法（在项目根目录 D:\\.Meowlisis 下）：
  runtime\\python.exe .phone\\serve.py

手机访问：
  https://<电脑局域网IP>:8443
首次访问会有证书警告，点「高级 / 继续前往」即可。
"""

import os
import sys
import socket
import shutil
import datetime
import subprocess

from flask import Flask, request, send_from_directory, Response
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
DESKTOPET_DIR = os.path.join(PROJECT_DIR, '.desktopet')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
CERT_DIR = os.path.join(BASE_DIR, 'cert')
CERT_PEM = os.path.join(CERT_DIR, 'cert.pem')
KEY_PEM = os.path.join(CERT_DIR, 'key.pem')

API_BASE = 'http://127.0.0.1:1800'
HOST = '0.0.0.0'
PORT = 8443

app = Flask(__name__)


# ==================== 静态页面 ====================

@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'index.html')


@app.route('/static/<path:p>')
def phone_static(p):
    return send_from_directory(STATIC_DIR, p)


@app.route('/pet/<path:p>')
def pet_files(p):
    """把 .desktopet 目录暴露为 /pet/，供手机页面 iframe 加载桌宠（同源，避免混合内容）"""
    return send_from_directory(DESKTOPET_DIR, p)


# ==================== 反向代理到主程序 api.py ====================

def _proxy(path, method='GET', **kw):
    url = API_BASE + path
    try:
        if method == 'POST':
            r = requests.post(url, timeout=60, **kw)
        else:
            r = requests.get(url, timeout=60, **kw)
        return Response(
            r.content,
            status=r.status_code,
            content_type=r.headers.get('Content-Type', 'application/json'),
        )
    except requests.exceptions.ConnectionError:
        return Response(
            '{"status":"error","message":"主程序 api.py 未启动"}',
            status=502,
            content_type='application/json',
        )


@app.route('/api/chat')
def api_chat():
    """文字对话（GET），转发 /chat"""
    return _proxy('/chat', params=request.args)


@app.route('/api/msg', methods=['POST'])
def api_msg():
    """文字对话（JSON），转发 /msg"""
    return _proxy('/msg', method='POST', json=request.get_json(silent=True) or {})


@app.route('/api/say', methods=['POST'])
def api_say():
    """TTS 复读，转发 /say"""
    return _proxy('/say', method='POST', data=request.get_data())


@app.route('/api/audio/send', methods=['POST'])
def api_audio_send():
    """语音上传，转发 /audio/send（16k 单声道 int16 PCM）"""
    return _proxy('/audio/send', method='POST', data=request.get_data())


@app.route('/api/chatreply')
def api_chatreply():
    """轮询 AI 回复文字，转发 /chatreply"""
    return _proxy('/chatreply', params=request.args)


@app.route('/api/tts')
def api_tts():
    """TTS 音频合成，转发主程序 /tts/audio"""
    return _proxy('/tts/audio', params=request.args)


@app.route('/api/mic', methods=['POST'])
def api_mic():
    """闭麦开关，转发 /mic"""
    return _proxy('/mic', method='POST', json=request.get_json(silent=True) or {})


# ==================== 证书生成 ====================

def ensure_cert():
    """生成/复用自签名证书，返回 (cert_pem, key_pem)；失败返回 None。"""
    if os.path.exists(CERT_PEM) and os.path.exists(KEY_PEM):
        return CERT_PEM, KEY_PEM
    os.makedirs(CERT_DIR, exist_ok=True)

    # 优先用 cryptography 生成（项目 runtime 自带）
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
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(u'localhost')]),
                critical=False,
            )
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

    # 回退到系统 openssl
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
    """获取本机局域网 IP（供手机访问提示用）"""
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


# ==================== 启动 ====================

if __name__ == '__main__':
    print('=' * 58)
    print('  喵呜手机界面服务 (.phone)')
    print('=' * 58)
    ip = lan_ip()

    cert = ensure_cert()
    if cert:
        cert_pem, key_pem = cert
        print(f'  手机请访问: https://{ip}:{PORT}')
        print('  首次访问有证书警告 -> 点「高级 / 继续前往」即可')
        print('  提示：语音识别走主程序 SenseVoice；AI 回复声音在电脑端播放')
        print('=' * 58)
        app.run(host=HOST, port=PORT, ssl_context=(cert_pem, key_pem), debug=False)
    else:
        print('[警告] 无法生成 HTTPS 证书，回退 HTTP（浏览器将无法授权麦克风，仅可用文字）')
        print(f'  手机请访问: http://{ip}:{PORT}')
        print('=' * 58)
        app.run(host=HOST, port=PORT, debug=False)
