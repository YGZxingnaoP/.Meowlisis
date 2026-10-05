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
# 服务注册表 / 统一启动器
#   清单与"怎么启动"全部在 gui/tools/launcher.py（一处配置全局生效）；
#   本文件只负责"看日志 / 查状态 / 停止 / 页面渲染"。
#   启动入口（/api/logs/start 与 config_gui 的 /api/start_*）统一走 launcher。
# ============================================================================
try:
    from gui.tools.launcher import SERVICES, ORDER
    from gui.tools import launcher, log_rules
except ImportError:                     # 兼容"只把 gui/tools 加进 sys.path"的导入方式
    _ROOT = Path(__file__).resolve().parents[2]        # gui/tools/loghub.py -> 项目根
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from gui.tools.launcher import SERVICES, ORDER
    from gui.tools import launcher, log_rules

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
# 级别词：只认大写（Python logging 输出就是大写），避免正文里的 error/warn 被误判
_LEVEL = re.compile(r'\b(CRITICAL|FATAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE)\b')
# 级别归一到三档：ERROR / WARN / INFO（前端就按这三类分页签）
_LV_MAP = {'CRITICAL': 'ERROR', 'FATAL': 'ERROR', 'ERROR': 'ERROR',
           'WARNING': 'WARN', 'WARN': 'WARN',
           'INFO': 'INFO', 'DEBUG': 'INFO', 'TRACE': 'INFO'}
# Python logging 标准行：时间 - logger[line:xx] - LEVEL: 正文
_STD_LOG = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[,.]\d{1,6})?)\s*-\s*'
    r'(?P<src>.+?)\s*-\s*(?P<lv>CRITICAL|FATAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE)\s*:\s*'
    r'(?P<msg>.*)$')
# 异常堆栈：起点（Traceback...）、末尾（XxxError: ...）
_TB_START = re.compile(r'Traceback \(most recent call last\)')
_TB_TAIL = re.compile(r'\w+(?:Error|Exception|Warning)\b')

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


# netstat 结果整体缓存：一次调用拿到"pid → 端口集合"的全局映射，
# 而不是每个在跑的服务各跑一次 netstat（侧边栏只是展示用，20 秒的新鲜度足够）。
_ports_cache = {'ts': 0.0, 'map': {}}


def _ports_map(max_age=20):
    if _ports_cache['map'] and (time.time() - _ports_cache['ts']) < max_age:
        return _ports_cache['map']
    code, out = _run(['netstat', '-ano'], timeout=15)
    m = {}
    for line in (out or '').splitlines():
        if 'LISTENING' not in line:
            continue
        parts = line.split()
        if len(parts) >= 5:
            mm = re.search(r':(\d+)$', parts[1])
            if not mm:
                continue
            try:
                m.setdefault(int(parts[-1]), set()).add(int(mm.group(1)))
            except Exception:
                continue
    _ports_cache['ts'] = time.time()
    _ports_cache['map'] = m
    return m


def _ports_of(pid):
    """查该 pid 正在监听的端口（侧边栏展示用；走上面的整体缓存）"""
    if not pid:
        return []
    try:
        return sorted(_ports_map().get(int(pid), set()))
    except Exception:
        return []


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
    if _scan['busy'] or (max_age > 0 and (time.time() - _scan['ts']) < max_age):
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


# 子进程环境（PYTHONUNBUFFERED / PYTHONIOENCODING）已统一在 gui/tools/launcher.py 处理。


# ============================================================================
# 增量读日志
# ============================================================================
def _is_traceback_cont(ln, pending):
    """是否属于上一条 Traceback 的续行（缩进行 / File 行 / 末尾的 XxxError: 行）"""
    if ln.startswith((' ', '\t')):
        return True
    if pending is None:
        return False
    if _TB_TAIL.search(pending.get('txt') or ''):
        return False            # 已经出现 XxxError: → 堆栈结束
    return bool(re.match(r'^[\w.]*(?:Error|Exception|Warning)\b', ln))


def _make_record(ln):
    """把一行原始日志解析成结构化记录。

    返回 {lv, ts, src, msg, txt, more, t}：
        lv   归一后的级别（ERROR / WARN / INFO / ''）
        ts   时间戳（非标准格式为空）
        src  来源 logger（非标准格式为空）
        msg  去掉时间/来源/级别后的正文（前端主行显示这个）
        txt  完整原始行（前端"原文"折叠里显示）
        more 归并进来的续行数（异常堆栈用）
        t    转译短句（匹配不到规则则为空，前端回退显示 msg）
    """
    m = _STD_LOG.match(ln)
    if m:
        rec = {
            'lv': _LV_MAP.get(m.group('lv'), ''),
            'ts': m.group('ts'),
            'src': (m.group('src') or '').strip(),
            'msg': m.group('msg'),
            'txt': ln,
            'more': 0,
        }
    else:
        lv = ''
        mm = _LEVEL.search(ln)
        if mm:
            lv = _LV_MAP.get(mm.group(1), '')
        elif _TB_START.search(ln):
            lv = 'ERROR'
        rec = {'lv': lv, 'ts': '', 'src': '', 'msg': ln, 'txt': ln, 'more': 0}
    # t = 转译短句（稳定 i18n key，不含变量）；d = 关键值（工具名/用户名…）
    rec['t'], rec['d'] = log_rules.translate(rec['msg'])
    return rec


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
    pending = None      # 正在归并的多行异常堆栈（Traceback 起 + 后续续行）
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
        # 多行异常堆栈：Traceback 起的那条 + 后续续行，归并成一条（前端折叠展开）
        if pending is not None and _is_traceback_cont(ln, pending):
            pending['txt'] += '\n' + ln
            pending['msg'] += '\n' + ln
            pending['more'] += 1
            pending['lv'] = 'ERROR'
            continue
        rec = _make_record(ln)
        pending = rec if _TB_START.search(ln) else None
        out.append(rec)
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
def _launch(key):
    """启动某个服务 —— 唯一实现。

    统一走 gui/tools/launcher.py：命令拼装 / 无窗口 / 日志落盘都在那边，
    这里只做"是否已在运行 / 防连点 / 启动后补 pid 标记"。

    返回 (ok: bool, body: dict)。
    """
    if key not in SERVICES:
        return False, {'status': 'error', 'message': '未知服务: %s' % key}
    if time.time() - _locks.get(key, 0) < 1.5:
        return False, {'status': 'error', 'message': '操作太快了，稍等一下'}
    _locks[key] = time.time()

    run, pid, ports = _running(key)
    if run:
        return True, {'status': 'ok', 'message': '已在运行', 'pid': pid,
                      'ports': ports, 'running': True}

    ok, msg, proc = launcher.start(key, _base())
    if not ok:
        return False, {'status': 'error', 'message': msg}

    # 直接持有 Popen 句柄：之后判断"在不在跑 / pid 是多少"是 O(1)，
    # 不必再起 powershell 反查进程（这里原来有个 6×0.8s 的后台线程，已删除）。
    if proc is not None:
        _procs[key] = proc
        try:
            _write_pid(key, proc.pid)
        except Exception:
            pass
    _scan['ts'] = 0.0        # 让状态缓存失效，下次刷新就是新状态
    return True, {'status': 'ok', 'message': msg, 'running': True,
                  'pid': (proc.pid if proc is not None else None)}


def start(key, app=None):
    """HTTP 入口：启动某个服务（统一启动器）"""
    ok, body = _launch(key)
    return jsonify(body)


def _start_view(key):
    """接管 config_gui.py 的 /api/start_<服务>：走同一个统一启动器。

    这样"主界面启动卡"和"日志页的启动按钮"是同一份启动实现，
    行为（无窗口 + 日志落盘 + 错误信息）完全一致。
    """
    def view(*a, **kw):
        ok, body = _launch(key)
        return jsonify(body)
    view.__name__ = 'start_' + key
    view.__loghub__ = True
    return view


def stop(key):
    """停止：**快路径优先**（内存句柄 + pid 文件），命令行反查只作兜底。

    快路径命中时全程只用 tasklist（毫秒级），不再起 powershell 全量扫进程；
    只有"本界面没记录、pid 文件也没有"时才反查一次命令行，保证手动起的服务也能停。
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

    # ---- 快路径：内存句柄 + pid 文件（都是 O(1)/毫秒级）----
    pids = []
    proc = _procs.pop(key, None)
    if proc is not None:
        try:
            if proc.poll() is None:
                pids.append(proc.pid)
        except Exception:
            pass
    pid_file = _read_pid(key)
    if pid_file and _pid_alive(pid_file) and pid_file not in pids:
        pids.append(pid_file)
    _clear_pid(key)

    # ---- 兜底：快路径什么都没拿到，才反查一次命令行（1~2s）----
    if not pids:
        pids = [x for x in _cmdline_pids(key) if _pid_alive(x)]

    for pid in pids:
        ok, out = _taskkill(pid)
        (killed if ok else failed).append(pid)
    if killed:
        msgs.append('已结束进程 ' + ','.join(str(x) for x in killed))

    # 复查：只针对刚杀掉的 pid，用 tasklist 轮询（最多 1s），取代原来的 sleep(0.8)
    deadline = time.time() + 1.0
    leftover = list(killed)
    while leftover and time.time() < deadline:
        leftover = [x for x in leftover if _pid_alive(x)]
        if leftover:
            time.sleep(0.15)
    if leftover:
        failed.extend(leftover)
    if failed:
        msgs.append('这些杀不掉（权限？）: ' + ','.join(str(x) for x in failed))
    if not pids:
        msgs.append('没找到它的进程：可能本来就已停止，或不是从本界面启动的'
                    '（点 ⟳ 刷新可更新状态）')

    _scan['ts'] = 0.0                    # 状态缓存立刻失效，下次刷新就是新状态
    return jsonify({
        'status': 'ok',
        'message': '；'.join(m for m in msgs if m),
        'killed': killed, 'failed': failed,
        'running': bool(leftover),
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

    # 统一日志目录（launcher 落盘 / 本模块读取都用它）
    launcher.set_base(_base())

    # ---- 1. 接管 config_gui.py 的启动端点 ----
    # 原实现是把 subprocess.Popen 临时换掉（猴补丁）；现在所有启动统一走
    # gui/tools/launcher.py，这里只把端点替换成"调同一个启动器"的壳。
    # 主界面启动卡（/api/start_*）与日志页按钮（/api/logs/start）因此行为一致。
    taken = []
    for key in ORDER:
        ep = SERVICES[key].get('endpoint')
        if not ep:
            continue
        fn = app.view_functions.get(ep)
        if fn is None:
            continue
        if getattr(fn, '__loghub__', False):
            taken.append(ep)
            continue
        app.view_functions[ep] = _start_view(key)
        taken.append(ep)

    # ---- 2. 新路由 ----
    @app.route('/logs')
    def _loghub_page():
        return send_from_directory(str(_GUI), 'logs.html')

    @app.route('/api/logs/services')
    def _loghub_services():
        # 状态判断走快路径（内存句柄 + pid 文件 + tasklist），本接口不再等 powershell。
        # deep=1（用户点 ⟳）时强制让后台重新扫一遍命令行，用于认出手动启动的服务；
        # 扫描在后台线程里跑，本次响应照样立刻返回，下一次轮询就能看到新状态。
        if request.args.get('deep') not in (None, '', '0', 'false'):
            _scan['ts'] = 0.0
            _ensure_scan(0)
        else:
            _ensure_scan()
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
