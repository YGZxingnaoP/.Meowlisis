# -*- coding: utf-8 -*-
# gui/tools/loghub.py
r"""日志中心（Log Hub）—— /logs 页面 + 服务注册表 + 无窗口启动器

为什么做成独立模块：
    config_gui.py 在 gui 目录之外，直接改它风险大。这里做成自包含模块，
    config_gui.py 只需要两行（import + register）。register() 会顺手**接管**
    它原有的 /api/start_* 端点：命令怎么拼、env 怎么设、cwd 在哪，全部沿用
    原来的函数，只把 `CREATE_NEW_CONSOLE` 换成 `CREATE_NO_WINDOW` 并把
    stdout/stderr 重定向到 logs/svc_<服务>.log —— 这样终端窗口就不弹了，
    而每个服务"怎么启动"这件事没有任何改动，回归风险最低。

在 config_gui.py 里的用法（用 gui/tools/patch_loghub.py 自动插入）：
    from gui.tools import loghub
    loghub.register(app, BASE_DIR, GUI_DIR)

接口：
    GET  /logs                        日志页（gui/logs.html）
    GET  /api/logs/services           服务列表：状态/端口/日志文件大小
    GET  /api/logs/tail?svc=&since=   增量读日志（按字节偏移，只回新内容）
    POST /api/logs/start?svc=         启动（无窗口）
    POST /api/logs/stop?svc=          停止（按 pid 标记 / 项目自带 stop）
    POST /api/logs/clear?svc=         清空该服务日志文件
"""

import os
import re
import json
import time
import subprocess
import threading
from datetime import date
from pathlib import Path

from flask import jsonify, request, send_from_directory, send_file

# ============================================================================
# 服务注册表：一处配置全局生效
#   key       : 前端用的 id
#   name      : 侧边栏显示名
#   endpoint  : config_gui.py 里已有的启动端点（register 后就被接管成无窗口）
#   log       : 日志文件（相对项目根）；{date} 会替换成当天日期
#   builtin   : True = 这个日志文件是程序本来就写的，不需要重定向
#   cmdline   : **停止/状态兜底**用的命令行关键字（服务不是从本界面启动、
#               或 config_gui 重启后内存记录丢了，就靠它反查进程）。用绝对路径里的
#               目录名做关键字，避免 'server.py' 这种互相撞车。
# ============================================================================
SERVICES = {
    'main': {
        'name': '主程序', 'endpoint': 'start_main',
        'log': 'logs/log_{date}.txt', 'builtin': True,
        'cmdline': ['api.py'], 'desc': 'Meowlisis 主程序（语音/LLM/桌宠等）',
    },
    'painting': {
        'name': '绘画引擎', 'endpoint': 'start_painting_comfy',
        'log': 'logs/comfy_engine.log', 'builtin': True,
        'cmdline': ['--disable-auto-launch'], 'desc': '内置 ComfyUI 内核（常驻）',
        'force_nowindow': True,       # 顺手把 engine_window 关掉，不再弹引擎窗口
    },
    'sovits': {
        'name': 'SoVITS', 'endpoint': 'start_sovits',
        'log': 'logs/svc_sovits.log', 'cmdline': ['.Sovits'], 'desc': 'GPT-SoVITS 语音合成',
    },
    'sensevoice': {
        'name': 'SenseVoice', 'endpoint': 'start_sensevoice',
        'log': 'logs/svc_sensevoice.log', 'cmdline': ['.SenseVoice'], 'desc': '语音识别 + 声纹',
    },
    'napcat': {
        'name': 'NapCat', 'endpoint': 'start_napcat',
        'log': 'logs/svc_napcat.log', 'cmdline': ['NapCatWinBootMain'], 'desc': 'QQ 机器人',
    },
    'netease': {
        'name': '网易云搜歌', 'endpoint': 'start_netease',
        'log': 'logs/svc_netease.log', 'cmdline': ['.NeteaseMusic'], 'desc': '网易云搜歌服务',
    },
    'rvc': {
        'name': 'RVC 翻唱', 'endpoint': 'start_rvc',
        'log': 'logs/svc_rvc.log', 'cmdline': ['.RVC'], 'desc': 'RVC 翻唱服务',
    },
    'desktopet': {
        'name': '桌宠', 'endpoint': 'start_desktopet',
        'log': 'logs/svc_desktopet.log', 'cmdline': ['.desktopet'], 'desc': '桌宠',
    },
    'phone': {
        'name': '手机接口', 'endpoint': 'start_phone',
        'log': 'logs/svc_phone.log', 'cmdline': ['.phone'], 'desc': '手机端接口服务',
    },
}

ORDER = ['main', 'painting', 'sovits', 'sensevoice', 'napcat', 'netease', 'rvc', 'desktopet', 'phone']

_BASE = None            # 项目根 Path
_GUI = None             # gui 目录 Path
_procs = {}             # key -> Popen（本进程内启动的）
_locks = {}             # key -> 最近一次操作时间（防连点）

# CSI（\x1b[ + 参数 + 终结符，含 256 色/光标控制）、OSC（\x1b] ... \x07）、
# 以及两字符 Fe 转义，统一剥掉。否则日志页会残留 [32m / [0m / [12;34H 这类乱码。
_ANSI = re.compile(
    r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])')
# 其余不可见控制字符（\t 保留）
_CTRL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_LEVEL = re.compile(r'\b(CRITICAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACEBACK)\b')

# ============================================================================
# 路径 / 日志文件
# ============================================================================
def _base():
    return _BASE if _BASE is not None else Path('.').resolve()


def _log_path(key):
    """该服务日志文件的绝对路径"""
    if key == 'napcat':
        inner = _napcat_inner_log()
        if inner:                      # NapCat 自己的文件日志（fileLog=true 之后才有）
            return inner
    s = SERVICES.get(key) or {}
    rel = str(s.get('log') or '').format(date=date.today().strftime('%Y-%m-%d'))
    return _base() / rel


def _napcat_inner_log():
    """NapCat 自己的文件日志：<版本>/resources/app/napcat/logs/*.log（取最新那个）。

    比重定向出来的 logs/svc_napcat.log 有用得多 —— 后者只有引导器的启动输出，
    登录/收发消息/报错都在 NapCat 自己的日志里。它没写日志时回退到 svc_napcat.log。
    """
    versions = _napcat_root() / 'versions'
    best = None
    try:
        for p in versions.glob('*/resources/app/napcat/logs/*.log'):
            if not p.is_file():
                continue
            if best is None or p.stat().st_mtime > best.stat().st_mtime:
                best = p
    except Exception:
        best = None
    return best


def _pid_file(key):
    return _base() / 'logs' / ('svc_%s.pid' % key)


def _write_pid(key, pid):
    try:
        _pid_file(key).parent.mkdir(parents=True, exist_ok=True)
        _pid_file(key).write_text(json.dumps({
            'pid': int(pid), 'key': key,
            'started_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _read_pid(key):
    try:
        return int(json.loads(_pid_file(key).read_text(encoding='utf-8')).get('pid') or 0)
    except Exception:
        return 0


def _clear_pid(key):
    try:
        _pid_file(key).unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 所有调外部命令的地方统一走这里：CREATE_NO_WINDOW
# （不然 taskkill / netstat / powershell 在被无窗口启动的环境里会闪黑框）
# ---------------------------------------------------------------------------
def _run(args, timeout=20):
    """执行命令并返回 (returncode, stdout)。永不抛异常。"""
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, errors='replace', timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except Exception as e:
        return -1, str(e)


def _pid_alive(pid):
    if not pid:
        return False
    code, out = _run(['tasklist', '/FI', 'PID eq %d' % int(pid), '/NH'], timeout=12)
    return str(pid) in (out or '')


def _ports_of(pid):
    """netstat 反查该 pid 正在监听的端口（侧边栏展示用）"""
    if not pid:
        return []
    want = str(pid)
    code, out = _run(['netstat', '-ano'], timeout=15)
    ports = set()
    for line in (out or '').splitlines():
        if 'LISTENING' not in line:
            continue
        parts = line.split()
        if len(parts) >= 5 and parts[-1] == want:
            m = re.search(r':(\d+)$', parts[1])
            if m:
                ports.add(int(m.group(1)))
    return sorted(ports)


def _cmdline_pids(key):
    """按命令行关键字反查进程 —— 停止/状态的兜底手段。

    为什么需要：进程可能不是从本界面启动的（比如你手动开着、或打补丁之前就起着），
    这时内存句柄和 pid 标记文件都没有，只查这两处的话"停止"就是完全没反应。
    """
    keys = [k for k in (SERVICES.get(key, {}).get('cmdline') or []) if k]
    if not keys:
        return []
    rx = '|'.join(re.escape(k) for k in keys)
    me = os.getpid()
    pids = set()

    # 必须排除查询工具自己：powershell 的命令行里就含这个模式串，会匹配到它自己，
    # 结果就是"查出一堆乱 pid、状态永远显示运行中、停止永远报失败"。
    # （cmd.exe 不能排 —— .bat 启动的服务，根进程就是 cmd）
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '%s' "
          "-and $_.Name -notmatch '^(powershell|pwsh|wmic)\\.exe$' } | "
          "ForEach-Object { $_.ProcessId }" % rx.replace("'", "''"))
    code, out = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], timeout=30)
    for tok in (out or '').split():
        if tok.strip().isdigit():
            pids.add(int(tok))

    if not pids:      # 老系统/没 powershell 时退回 wmic
        code, out = _run(['wmic', 'process', 'get', 'ProcessId,CommandLine', '/format:csv'], timeout=30)
        for line in (out or '').splitlines():
            if re.search(rx, line, re.I) and 'wmic' not in line.lower():
                m = re.search(r',(\d+)\s*$', line)
                if m:
                    pids.add(int(m.group(1)))

    pids.discard(me)
    pids.discard(os.getppid() if hasattr(os, 'getppid') else 0)
    _scan['last_raw'] = sorted(pids)
    return sorted(pids)


# 后台扫描缓存：不让 /api/logs/services 每次都等 powershell
_scan = {'ts': 0.0, 'pids': {}, 'busy': False, 'err': ''}


def _scan_worker():
    try:
        found = {}
        for key in ORDER:
            found[key] = _cmdline_pids(key)
        _scan['pids'] = found
        _scan['ts'] = time.time()
        _scan['err'] = ''
    except Exception as e:
        _scan['err'] = str(e)
    finally:
        _scan['busy'] = False


def _ensure_scan(max_age=25):
    if _scan['busy'] or (time.time() - _scan['ts']) < max_age:
        return
    _scan['busy'] = True
    threading.Thread(target=_scan_worker, daemon=True).start()


def _scan_pids(key):
    return list(_scan['pids'].get(key) or [])


def _running(key):
    """运行状态 + pid + 端口。

    查三处：本进程内存句柄 → pid 标记文件 → 后台命令行扫描（覆盖"手动启动/重启前启动"）。
    """
    p = _procs.get(key)
    if p is not None:
        if p.poll() is None:
            return True, p.pid, _ports_of(p.pid)
        _procs.pop(key, None)
    pid = _read_pid(key)
    if pid and _pid_alive(pid):
        return True, pid, _ports_of(pid)
    if pid:
        _clear_pid(key)
    found = _scan_pids(key)
    if found:
        return True, found[0], _ports_of(found[0])
    return False, 0, []


def _all_pids(key):
    """把该服务能查到的进程全找出来（停止时用）"""
    pids = []
    p = _procs.get(key)
    if p is not None and p.poll() is None:
        pids.append(p.pid)
    pid = _read_pid(key)
    if pid and _pid_alive(pid) and pid not in pids:
        pids.append(pid)
    for x in _cmdline_pids(key):          # 兜底：现场查一次，不用缓存
        if x not in pids:
            pids.append(x)
    return pids


def _taskkill(pid):
    code, out = _run(['taskkill', '/F', '/T', '/PID', str(pid)], timeout=20)
    return code == 0, (out or '').strip().replace('\r', ' ').replace('\n', ' ')


# ============================================================================
# NapCat 专用：登录二维码 + WebUI 信息
# ============================================================================
def _napcat_root():
    return _base() / '.NapCat' / 'NapCat.Shell'


def _napcat_qr_path():
    """NapCat 把登录二维码写成 PNG（不需要解析控制台 ASCII 图）。

    版本目录名会随升级变化（现在是 9.9.26-44498），所以扫所有版本取最新的那个。
    """
    versions = _napcat_root() / 'versions'
    cands = []
    try:
        cands = [p for p in versions.glob('*/resources/app/napcat/cache/qrcode.png') if p.is_file()]
    except Exception:
        cands = []
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def _napcat_webui():
    """读 NapCat 自带 WebUI 的地址/令牌（能扫码、能看状态，作为二维码的备选入口）"""
    try:
        cfg = json.loads((_napcat_root() / 'versions').glob('*/resources/app/napcat/config/webui.json')
                         .__next__().read_text(encoding='utf-8'))
        port = int(cfg.get('port') or 6099)
        return {'url': 'http://127.0.0.1:%d' % port, 'token': str(cfg.get('token') or ''),
                'disabled': bool(cfg.get('disableWebUI'))}
    except Exception:
        return {'url': 'http://127.0.0.1:6099', 'token': '', 'disabled': False}


def _napcat_info():
    qr = _napcat_qr_path()
    exists = bool(qr and qr.is_file())
    return {
        'qr': {'exists': exists,
               'mtime': int(qr.stat().st_mtime) if exists else 0,
               'url': '/api/logs/napcat_qr'},
        'webui': _napcat_webui(),
    }


def _child_env(env):
    """子进程环境：必须让 Python 子进程无缓冲输出。

    stdout 被重定向到文件（不是终端）时，Python 会切成块缓冲，
    日志要攒满 4~8KB 才落盘 —— 表现就是"点了启动但日志页半天没动静"。
    PYTHONUNBUFFERED=1 关掉它；PYTHONIOENCODING 统一成 utf-8，前端就不用猜编码。
    """
    e = dict(env) if env else os.environ.copy()
    e.setdefault('PYTHONUNBUFFERED', '1')
    e.setdefault('PYTHONIOENCODING', 'utf-8')
    return e


# ============================================================================
# 增量读日志
# ============================================================================
def read_tail(key, since=None, limit=1500, first_bytes=192 * 1024):
    """按字节偏移读日志。

    since=None 首次读：只取文件尾部 first_bytes，避免几十 MB 老日志拖死浏览器。
    since 有值：只读 since 之后的新内容（增量轮询用，几乎零成本）。
    返回 (lines, offset, size)。offset 永远停在最后一个换行之后，
    这样"半行"不会被截断返回，下次也不会重复。
    """
    path = _log_path(key)
    if not path.is_file():
        return [], 0, 0
    size = path.stat().st_size
    start = since if isinstance(since, int) and since >= 0 else None
    if start is None or start > size:
        start = max(0, size - first_bytes)
    if start == size:
        return [], size, size
    with open(path, 'rb') as f:
        f.seek(start)
        blob = f.read(min(size - start, 4 * 1024 * 1024))
    cut = blob.rfind(b'\n')
    if cut < 0:
        return [], start, size          # 还没有完整的一行
    text = _decode(blob[:cut + 1])
    offset = start + cut + 1
    raw = text.split('\n')[:-1]
    if len(raw) > limit:
        raw = raw[-limit:]
    root = str(_base())
    roots = [root + os.sep, root + '/']
    out = []
    for ln in raw:
        ln = _ANSI.sub('', ln)          # 去颜色 / 光标控制转义
        ln = _CTRL.sub('', ln)          # 去其余不可见控制字符
        # 注意顺序：先去掉"行尾"的 \r —— Windows 上 Python logging 写的是 CRLF，
        # 若先按 \r 切分会把整行切成空串（这是最初 tail 一直返回 0 行的原因）。
        ln = ln.rstrip('\r')
        if '\r' in ln:                  # 行内还有 \r → 进度条原地刷新，只留最后一次
            ln = ln.split('\r')[-1]
        ln = ln.rstrip()                # 清掉 banner 那种一长串行尾空格
        for p in roots:                 # 项目根绝对路径压成相对路径，读起来清爽
            ln = ln.replace(p, '')
        if not ln.strip():
            continue
        m = _LEVEL.search(ln)
        lv = (m.group(1) if m else '').upper()
        out.append({'lv': lv, 'txt': ln})
    return out, offset, size


def _decode(blob):
    """日志编码兜底：项目日志是 utf-8；子进程/第三方 exe 可能是 gbk"""
    for enc in ('utf-8', 'gbk', 'mbcs'):
        try:
            return blob.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return blob.decode('utf-8', errors='replace')


# ============================================================================
# 启动 / 停止
# ============================================================================
def _make_start_view(key, orig):
    """把 config_gui.py 原有的启动函数包一层：无窗口 + 输出落盘。

    只替换 subprocess.Popen 的 creationflags / stdout / stderr / stdin，
    其余（命令拼装、env、cwd、错误处理）原样复用 —— 这是改动最小的做法。
    """
    def view(*a, **kw):
        try:
            s = SERVICES[key]
            if s.get('force_nowindow'):
                try:
                    from func.toolbox.flux_painter.config import TBFluxPainterConfig
                    TBFluxPainterConfig().engine_window = False
                except Exception:
                    pass
            log_path = _log_path(key)
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                logf = open(log_path, 'ab', buffering=0)
            except Exception as e:
                return jsonify({'status': 'error', 'message': '打不开日志文件: %s' % e}), 500

            real_popen = subprocess.Popen
            spawned = []

            def fake_popen(*pa, **pk):
                pk['creationflags'] = subprocess.CREATE_NO_WINDOW
                pk['stdout'] = logf
                pk['stderr'] = subprocess.STDOUT
                pk['stdin'] = subprocess.DEVNULL
                pk['env'] = _child_env(pk.get('env'))
                p = real_popen(*pa, **pk)
                spawned.append(p)
                return p

            subprocess.Popen = fake_popen
            try:
                resp = orig(*a, **kw)
            finally:
                subprocess.Popen = real_popen
                try:
                    logf.close()        # 父进程副本关掉；子进程持有自己的句柄，继续写
                except Exception:
                    pass
            if spawned:
                _procs[key] = spawned[-1]
                _write_pid(key, spawned[-1].pid)
            return resp
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    view.__name__ = getattr(orig, '__name__', 'start_' + key)
    return view


def start(key, app):
    """HTTP 入口：启动某个服务（复用被接管的原端点函数）"""
    if key not in SERVICES:
        return jsonify({'status': 'error', 'message': '未知服务: %s' % key}), 400
    if time.time() - _locks.get(key, 0) < 1.5:
        return jsonify({'status': 'error', 'message': '操作太快了，稍等一下'}), 429
    _locks[key] = time.time()
    run, pid, ports = _running(key)
    if run:
        return jsonify({'status': 'ok', 'message': '已在运行', 'pid': pid, 'ports': ports,
                        'running': True})
    fn = app.view_functions.get(SERVICES[key].get('endpoint') or '')
    if fn is None:
        return jsonify({'status': 'error',
                        'message': '找不到启动端点 %s（config_gui.py 可能没打补丁）'
                                   % SERVICES[key].get('endpoint')}), 500
    resp = fn()
    # 原函数一般返回 jsonify 响应，这里原样返回；补一个运行状态
    try:
        code = resp.status_code
        body = resp.get_json() or {}
    except Exception:
        code, body = 200, {}
    if code != 200 or body.get('status') == 'error':
        return resp
    body['running'] = True
    body.setdefault('message', '已启动')
    return jsonify(body), code


def stop(key):
    """停止：内存句柄 + pid 标记 + **命令行反查**，三路全上。

    之前只查前两路，所以"打补丁之前就在跑的服务""手动起的服务"点停止完全没反应。
    现在无论如何都会真的去找进程，并把结果如实回给前端。
    """
    if key not in SERVICES:
        return jsonify({'status': 'error', 'message': '未知服务: %s' % key}), 400

    msgs, killed, failed = [], [], []

    # 绘画引擎走项目自带的 stop（它有自己的 pid 标记与常驻语义）
    if key == 'painting':
        try:
            from func.toolbox.flux_painter.config import TBFluxPainterConfig
            from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter
            ok = get_managed_painter(TBFluxPainterConfig()).stop()
            msgs.append('引擎已停止' if ok else '引擎未在运行')
        except Exception as e:
            msgs.append('引擎停止失败: %s' % e)

    _procs.pop(key, None)
    _clear_pid(key)

    for pid in _all_pids(key):
        if not _pid_alive(pid):          # 已经死了就别报"杀不掉"，那会污染 running 判断
            continue
        ok, out = _taskkill(pid)
        (killed if ok else failed).append(pid)
    if killed:
        msgs.append('已结束进程 ' + ','.join(str(x) for x in killed))

    time.sleep(0.8)                      # 给系统一点时间回收
    still = [x for x in _cmdline_pids(key) if _pid_alive(x)]
    for pid in still:                    # 复查残留（-T 没带掉的子进程再补一刀）
        ok, out = _taskkill(pid)
        (killed if ok else failed).append(pid)
    if failed:
        msgs.append('这些杀不掉（权限？）: ' + ','.join(str(x) for x in failed))

    _scan['ts'] = 0.0                    # 让状态缓存立刻失效，下次刷新就是新状态
    final = [x for x in _cmdline_pids(key) if _pid_alive(x)]
    if not killed and not failed and not final:
        msgs.append('没找到它的进程：可能本来就已停止，或不是从本界面启动的'
                    '（点 ⟳ 刷新可更新状态）')
    return jsonify({
        'status': 'ok',
        'message': '；'.join(m for m in msgs if m),
        'killed': killed, 'failed': failed,
        'running': bool(final),
    })


# ============================================================================
# 路由注册
# ============================================================================
def register(app, base_dir=None, gui_dir=None):
    global _BASE, _GUI
    if base_dir:
        _BASE = Path(base_dir).resolve()
    if gui_dir:
        _GUI = Path(gui_dir).resolve()
    if _GUI is None:
        _GUI = Path(__file__).resolve().parent.parent      # gui/

    # ---- 1. 接管 config_gui.py 原有的启动端点（换成无窗口版）----
    taken = []
    for key in ORDER:
        ep = SERVICES[key].get('endpoint')
        if not ep:
            continue
        fn = app.view_functions.get(ep)
        if fn is None:
            continue
        # 已经接管过就不重复包装
        if getattr(fn, '__loghub__', False):
            taken.append(ep)
            continue
        wrapped = _make_start_view(key, fn)
        wrapped.__loghub__ = True
        app.view_functions[ep] = wrapped
        taken.append(ep)

    # ---- 2. 新路由 ----
    @app.route('/logs')
    def _loghub_page():
        return send_from_directory(str(_GUI), 'logs.html')

    @app.route('/api/logs/services')
    def _loghub_services():
        _ensure_scan()          # 后台刷新"命令行反查"缓存，状态才认得出手动启动的服务
        items = []
        for key in ORDER:
            s = SERVICES[key]
            run, pid, ports = _running(key)
            lp = _log_path(key)
            try:
                size = lp.stat().st_size if lp.is_file() else 0
                mtime = int(lp.stat().st_mtime) if lp.is_file() else 0
            except Exception:
                size, mtime = 0, 0
            items.append({
                'key': key, 'name': s['name'], 'desc': s.get('desc', ''),
                'running': run, 'pid': pid, 'ports': ports,
                'log': str(lp.relative_to(_base())).replace('\\', '/'),
                'log_exists': lp.is_file(), 'size': size, 'mtime': mtime,
            })
            if key == 'napcat':
                items[-1].update(_napcat_info())
        return jsonify({'status': 'ok', 'items': items,
                        'patched': sorted(taken), 'ts': int(time.time())})

    @app.route('/api/logs/napcat_qr')
    def _loghub_napcat_qr():
        """NapCat 登录二维码（它自己写的 PNG，直接透传；前端用 mtime 当 cache-buster）"""
        p = _napcat_qr_path()
        if not p or not p.is_file():
            return jsonify({'status': 'error',
                            'message': '还没有二维码：NapCat 未在扫码登录，或已登录过'}), 404
        resp = send_file(str(p), mimetype='image/png')
        resp.headers['Cache-Control'] = 'no-store, max-age=0'
        return resp

    @app.route('/api/logs/tail')
    def _loghub_tail():
        key = request.args.get('svc', 'main')
        if key not in SERVICES:
            return jsonify({'status': 'error', 'message': '未知服务: %s' % key}), 400
        since = request.args.get('since')
        try:
            since = int(since) if since not in (None, '') else None
        except Exception:
            since = None
        try:
            limit = min(5000, max(50, int(request.args.get('limit') or 1500)))
        except Exception:
            limit = 1500
        lines, offset, size = read_tail(key, since, limit)
        run, pid, ports = _running(key)
        return jsonify({'status': 'ok', 'key': key, 'lines': lines,
                        'offset': offset, 'size': size,
                        'running': run, 'pid': pid, 'ports': ports})

    @app.route('/api/logs/start', methods=['POST'])
    def _loghub_start():
        key = request.args.get('svc') or (request.get_json(silent=True) or {}).get('svc', '')
        return start(key, app)

    @app.route('/api/logs/stop', methods=['POST'])
    def _loghub_stop():
        key = request.args.get('svc') or (request.get_json(silent=True) or {}).get('svc', '')
        return stop(key)

    @app.route('/api/logs/clear', methods=['POST'])
    def _loghub_clear():
        key = request.args.get('svc') or (request.get_json(silent=True) or {}).get('svc', '')
        if key not in SERVICES:
            return jsonify({'status': 'error', 'message': '未知服务: %s' % key}), 400
        lp = _log_path(key)
        if not lp.is_file():
            return jsonify({'status': 'ok', 'message': '日志文件不存在'})
        try:
            with open(lp, 'wb'):
                pass                     # 截断
            return jsonify({'status': 'ok', 'message': '已清空 %s' % lp.name})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    print('[loghub] /logs 已注册；接管启动端点: %s' % (', '.join(taken) or '无'))
    return {'taken': taken}
