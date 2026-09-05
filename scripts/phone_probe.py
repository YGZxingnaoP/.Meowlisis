# -*- coding: utf-8 -*-
"""
手机录音完整性捕获器（纯旁路，不改主项目、不 import func/*）

为什么存在：语音识别老只出"句号"，怀疑手机录到的根本不是完整人声。
本脚本开一个 HTTPS 端口（默认 8444），复用 .phone 的证书与静态页面；
手机访问本脚本端口时，页面功能与直连 8443 完全一致（/api/* 全部转发），
但 /api/audio/send 上传的每一块 PCM 会被原样截获、拼接、落盘成 wav，
并实时打印"收到第 N 块 / 累计 X 秒"。松开说话后还能自动看主程序识别结果。

用法（在项目根目录）:
  runtime\\python.exe scripts\\phone_probe.py                # 默认旁路捕获端口 8444
  runtime\\python.exe scripts\\phone_probe.py --port 8445    # 换端口
  runtime\\python.exe scripts\\phone_probe.py --out D:\\cap   # 录音落盘目录
  runtime\\python.exe scripts\\phone_probe.py --self --seconds 4   # 电脑麦克风自检(直接打8443)

流程:
  1. 启动本脚本（需 8443 serve.py 与主程序 api.py 已运行）
  2. 手机浏览器访问 https://<电脑IP>:8444  （证书警告点「继续前往」）
  3. 按住说话 3~5 秒 → 脚本实时打印接收统计，松开后自动保存 rec_*.wav
  4. 用播放器试听该 wav → 判断手机到底录到了什么
"""
import argparse
import datetime
import json
import os
import socket
import ssl
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHONE_DIR = os.path.join(ROOT, '.phone')
STATIC_DIR = os.path.join(PHONE_DIR, 'static')
CERT_PEM = os.path.join(PHONE_DIR, 'cert', 'cert.pem')
KEY_PEM = os.path.join(PHONE_DIR, 'cert', 'key.pem')
PET_DIR = os.path.join(ROOT, '.desktopet')
LOG_DIR = os.path.join(ROOT, 'logs')

PHONE_8443 = 'https://127.0.0.1:8443'
API_1800 = 'http://127.0.0.1:1800'
SAMPLE_RATE = 16000

import requests
requests.packages.urllib3.disable_warnings()


def now():
    return time.strftime('%H:%M:%S')


def log(msg):
    print(f'[{now()}] {msg}', flush=True)


def port_up(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(('127.0.0.1', port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


# ---------------- 录音捕获器 ----------------
CAP_LOCK = threading.Lock()
CAP = {
    'active': False, 'buf': bytearray(), 'chunks': 0, 'user': '',
    'start_ts': None, 'last_chunk_ts': None,
}


def cap_start(username):
    with CAP_LOCK:
        if CAP['active']:
            return False
        CAP['active'] = True
        CAP['buf'] = bytearray()
        CAP['chunks'] = 0
        CAP['user'] = username or '手机用户'
        CAP['start_ts'] = time.time()
        CAP['last_chunk_ts'] = time.time()
        log(f'🎙 捕获开始 username={username} —— 请在手机端说话...')
        return True


def cap_feed(data):
    with CAP_LOCK:
        if not CAP['active'] or not data:
            return
        CAP['buf'].extend(data)
        CAP['chunks'] += 1
        CAP['last_chunk_ts'] = time.time()
        secs = len(CAP['buf']) / 2 / SAMPLE_RATE
        log(f'   第 {CAP["chunks"]} 块 +{len(data)}B，累计 {len(CAP["buf"])}B ≈ {secs:.2f}s')


def cap_finish(outdir):
    with CAP_LOCK:
        if not CAP['active']:
            return None
        CAP['active'] = False
        buf = bytes(CAP['buf'])
        user = CAP['user']
        chunks = CAP['chunks']
        secs = len(buf) / 2 / SAMPLE_RATE
    os.makedirs(outdir, exist_ok=True)
    fn = os.path.join(outdir,
                      'rec_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                      + '_' + user + '.wav')
    if buf:
        with wave.open(fn, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(buf)
    log('=' * 56)
    log(f'✅ 录音捕获完成：{chunks} 块，共 {len(buf)}B ≈ {secs:.2f}s，说话人={user}')
    log(f'   已保存: {fn}')
    log('   请用播放器试听：是"完整人声"还是"静音/环境噪声"')
    log('=' * 56)
    return fn


# ---------------- 转发到真实服务（保持页面功能） ----------------
def relay(method, path, query, body=None):
    """把 /api/xxx 转发到 8443（优先）或 1800（去掉 /api 前缀）"""
    qs = ('?' + query) if query else ''
    if path == '/api/tts/pending':
        if not port_up(8443):
            return 200, {'Content-Type': 'application/json'}, json.dumps(
                {'seq': -1, 'meta': {}, 'blocks': []}).encode()
    target8443 = port_up(8443)
    if target8443:
        url = PHONE_8443 + path + qs
    elif path.startswith('/api/'):
        url = API_1800 + path[len('/api'):] + qs   # /api/audio/send -> /audio/send
    else:
        url = API_1800 + path + qs
    try:
        if method == 'POST':
            r = requests.post(url, data=body, timeout=60, verify=False,
                              headers={'Content-Type': 'application/octet-stream'})
        else:
            r = requests.get(url, timeout=15, verify=False)
        ctype = r.headers.get('Content-Type', 'application/json')
        return r.status_code, {'Content-Type': ctype}, r.content
    except Exception:
        return 502, {'Content-Type': 'application/json'}, json.dumps(
            {'status': 'error', 'message': '转发失败'}).encode()


MIME = {
    '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8', '.json': 'application/json',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.svg': 'image/svg+xml', '.webp': 'image/webp',
    '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2',
    '.ttf': 'font/ttf', '.mp3': 'audio/mpeg', '.wav': 'audio/wav',
}


def static_file(fs_path, raw_path):
    if not os.path.isfile(fs_path):
        return 404, {'Content-Type': 'text/plain'}, b'not found'
    with open(fs_path, 'rb') as f:
        data = f.read()
    ext = os.path.splitext(raw_path)[1].lower()
    return 200, {'Content-Type': MIME.get(ext, 'application/octet-stream')}, data


OUT_DIR = None
STOP_WATCH = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass  # 不打印访问日志，保持输出只与录音相关

    def _send(self, code, headers, body):
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    # ---------- 路由 ----------
    def do_GET(self):
        parts = urlsplit(self.path)
        path, query = parts.path, parts.query
        if path == '/':
            code, h, b = static_file(os.path.join(STATIC_DIR, 'index.html'), '/')
        elif path.startswith('/static/'):
            code, h, b = static_file(os.path.join(STATIC_DIR, path[len('/static/'):]), path)
        elif path.startswith('/pet/'):
            code, h, b = static_file(os.path.join(PET_DIR, path[len('/pet/'):]), path)
        elif path.startswith('/api/'):
            code, h, b = relay('GET', path, query)
        else:
            code, h, b = 404, {'Content-Type': 'text/plain'}, b'not found'
        self._send(code, h, b)

    def do_POST(self):
        parts = urlsplit(self.path)
        path, query = parts.path, parts.query
        n = int(self.headers.get('Content-Length', 0) or 0)
        body = self.rfile.read(n) if n > 0 else b''
        if path == '/api/audio/send':
            params = dict(x.split('=', 1) for x in query.split('&')) if query else {}
            user = params.get('username', '手机用户')
            if not CAP['active']:
                cap_start(user)
            cap_feed(body)
            code, h, b = relay('POST', path, query, body)
        elif path == '/api/audio/end':
            fn = cap_finish(OUT_DIR)
            code, h, b = relay('POST', path, query, body)
            if fn:
                threading.Thread(target=watch_recognition, args=(fn,), daemon=True).start()
        else:
            code, h, b = relay('POST', path, query, body)
        self._send(code, h, b)


# ---------------- 结束后观察主程序识别结果 ----------------
def tail_logs_keywords(keywords, seconds=25):
    best = None
    for p in [os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.endswith('.txt')] if os.path.isdir(LOG_DIR) else []:
        if os.path.isfile(p) and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
            best = p
    if not best:
        return
    with open(best, encoding='utf-8', errors='ignore') as f:
        base = len(f.read().splitlines())
    t0 = time.time()
    seen = 0
    while time.time() - t0 < seconds:
        with open(best, encoding='utf-8', errors='ignore') as f:
            lines = f.read().splitlines()[base:]
        for ln in lines:
            if any(k in ln for k in keywords):
                print(f'[识别日志] {ln[:300]}', flush=True)
                seen += 1
        base += len(lines)
        time.sleep(0.8)


def watch_recognition(fn):
    log('（服务端识别观察中，最多 25s...）')
    tail_logs_keywords(['识别到最终文本', '说话人', '通过说话人验证', '不在目标',
                        '空文本', '[inject]', 'subtitle', '已送入 AI'])


# ---------------- 电脑麦克风自检（直接打 8443，模拟手机按住说话） ----------------
def self_check(seconds, text_prompt):
    try:
        import pyaudio
        import numpy as np
    except ImportError:
        log('自检需要 pyaudio/numpy：runtime 未装，跳过（请用 --proxy 模式）')
        return
    log(f'自检：请对电脑麦克风说出 ——「{text_prompt}」')
    for i in range(3, 0, -1):
        log(f'  {i} 秒后开始录音...')
        time.sleep(1)
    pa = pyaudio.PyAudio()
    info = pa.get_default_input_device_info()
    dev_rate = int(info.get('defaultSampleRate', 48000))
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=dev_rate,
                     input=True, frames_per_buffer=int(dev_rate * 0.1))
    log(f'🎙 录音 {seconds}s（设备 {info.get("name")} @{dev_rate}Hz）...')
    frames = []
    for _ in range(int(seconds * dev_rate / (dev_rate * 0.1))):
        frames.append(stream.read(int(dev_rate * 0.1), exception_on_overflow=False))
    stream.stop_stream(); stream.close(); pa.terminate()
    raw = b''.join(frames)
    if dev_rate != SAMPLE_RATE:
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        # 线性插值重采样到 16k
        ratio = dev_rate / SAMPLE_RATE
        idx = np.arange(int(len(a) / ratio)) * ratio
        i0 = idx.astype(np.int64)
        i1 = np.minimum(i0 + 1, len(a) - 1)
        frac = idx - i0
        a16 = a[i0] * (1 - frac) + a[i1] * frac
        raw = np.clip(a16 * 32768, -32768, 32767).astype(np.int16).tobytes()
    log(f'录音完成：{len(raw)}B ≈ {len(raw)/2/SAMPLE_RATE:.2f}s，上传 8443...')
    r = requests.post('https://127.0.0.1:8443/api/audio/send',
                      params={'username': '自检'}, data=raw, verify=False, timeout=30)
    log(f'/api/audio/send -> HTTP {r.status_code} {r.text[:80]}')
    time.sleep(0.3)
    r2 = requests.post('https://127.0.0.1:8443/api/audio/end', verify=False, timeout=10)
    log(f'/api/audio/end -> HTTP {r2.status_code}')
    log('等待主程序识别（25s）...')
    tail_logs_keywords(['识别到最终文本', '说话人', '通过说话人验证', '不在目标', '空文本'])


def main():
    ap = argparse.ArgumentParser(description='手机录音完整性捕获器（旁路 8444 / 自检 8443）')
    ap.add_argument('--port', type=int, default=8444)
    ap.add_argument('--out', default=os.path.join(ROOT, '.temp', 'phone_capture'))
    ap.add_argument('--self', action='store_true', help='电脑麦克风自检模式（直接打 8443）')
    ap.add_argument('--seconds', type=int, default=5, help='自检录音秒数')
    ap.add_argument('--prompt', default='测试一二三四五，今天天气怎么样', help='自检提示语')
    args = ap.parse_args()

    global OUT_DIR
    OUT_DIR = args.out

    log('==== 手机录音完整性捕获器 ====')
    log(f'8443(.phone): {"UP" if port_up(8443) else "DOWN"} | 1800(api.py): {"UP" if port_up(1800) else "DOWN"}')
    if not port_up(1800):
        log('⚠ 主程序 api.py 未启动：能捕获录音，但无法识别（请先启动 api.py）')

    if args.self:
        self_check(args.seconds, args.prompt)
        return

    if not (os.path.exists(CERT_PEM) and os.path.exists(KEY_PEM)):
        log('缺少 .phone/cert/cert.pem（先运行一次 runtime\\python.exe .phone\\serve.py 生成）')
        return

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_PEM, KEY_PEM)
    srv = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)

    ip = lan_ip()
    log('=' * 56)
    log('  手机请访问:  https://%s:%d' % (ip, args.port))
    log('  证书警告 → 点「高级 / 继续前往」')
    log('  然后「按住说话」3~5 秒，本窗口会实时打印收到的录音统计')
    log('  录音将保存到: %s' % os.path.abspath(OUT_DIR))
    log('  按 Ctrl+C 退出')
    log('=' * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
