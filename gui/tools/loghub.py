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

try:
    import psutil as _psutil          # 有它就不必为每次存活判断去起 tasklist
except Exception:
    _psutil = None
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

# 形状归一化：把一行里的时间/ID/路径/数字/引号串抹平成占位符，
# 抹平后相同的行 = "同一件事在重复"，相邻的就能合并成一行 ×N。
# 这是唯一的降噪机制，不用为任何服务写规则。
_SHAPE = [
    (re.compile(r'\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[,.]\d+)?'), '<T>'),
    (re.compile(r'\b\d{2}:\d{2}:\d{2}\b'), '<T>'),
    (re.compile(r'\b[0-9a-fA-F]{8,}\b'), '<ID>'),
    (re.compile(r'[\u258f\u258e\u258d\u258c\u258b\u258a\u2589\u2588]{2,}'), '<BAR>'),
    (re.compile(r"[A-Za-z]:\\[^\s\"']*"), '<P>'),
    (re.compile(r'\d+\.\d+'), '<F>'),
    (re.compile(r'\d+'), '<N>'),
    (re.compile(r"[\"'][^\"']{0,40}[\"']"), '<S>'),
]


def shape_of(text):
    """抹平变量后的"形状"，用于判断两行是否是同一件事"""
    s = (text or '').strip()
    for rx, rep in _SHAPE:
        s = rx.sub(rep, s)
    return re.sub(r'\s+', ' ', s)[:140]


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


def _log_path(key, day=None):
    """该服务日志文件的绝对路径：指定日 → 今天 → 最新一天 → 旧版无日期文件"""
    if key == 'napcat':
        inner = _napcat_inner_log()
        if inner:                      # NapCat 自己的文件日志（fileLog=true 之后才有）
            return inner
    s = SERVICES.get(key) or {}
    rel = str(s.get('log') or '')
    today = date.today().strftime('%Y-%m-%d')
    if day:
        p = _base() / rel.replace('{date}', day)
        if p.is_file():
            return p
    if '{date}' in rel:
        p = _base() / rel.format(date=today)
        if p.is_file():
            return p
    pat = rel.replace('{date}', '*') if '{date}' in rel else ('logs/svc_%s_*.log' % key)
    try:
        cands = sorted(x for x in _base().glob(pat) if x.is_file())
    except Exception:
        cands = []
    if cands:
        return cands[-1]
    legacy = _base() / ('logs/svc_%s.log' % key)
    if legacy.is_file():
        return legacy
    return _base() / rel.format(date=today)


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
    if _psutil is not None:
        try:
            return bool(_psutil.pid_exists(int(pid)))
        except Exception:
            pass
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
          "-and $_.CommandLine -notmatch ' -c ' "
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


def _scan_all_cmdlines():
    """一次遍历进程表，同时算出每个服务匹配到的 pid。

    原来是对 9 个服务各起一个 powershell（每个 ~400ms，合计 3.6s，还各自全表扫描），
    这里改成进程内一趟走完；psutil 不在时才退回逐个 powershell。
    """
    found = {k: [] for k in ORDER}
    if _psutil is None:
        for key in ORDER:
            found[key] = _cmdline_pids(key)
        return found
    pats = {k: [x for x in (SERVICES.get(k, {}).get('cmdline') or []) if x] for k in ORDER}
    me = os.getpid()
    try:
        ppid = os.getppid()
    except Exception:
        ppid = 0
    for p in _psutil.process_iter(['pid', 'cmdline']):
        try:
            pid = p.info['pid']
            if pid == me or pid == ppid:
                continue
            cl = ' '.join(p.info.get('cmdline') or [])
            if not cl:
                continue
            if ' -c ' in (' ' + cl + ' ') and '.py' not in cl:
                continue            # python -c "..." 一次性脚本，别当成服务（会误杀/误判）
            for key, keys in pats.items():
                if keys and any(x in cl for x in keys):
                    found[key].append(pid)
        except Exception:
            continue
    for key in found:
        found[key] = sorted(found[key])
    return found


def _scan_worker():
    try:
        found = _scan_all_cmdlines()
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


def _live_pids(key):
    """现场扫一次该服务的进程（不吃缓存）—— 启停前判断"是不是已经有实例在外面跑" """
    try:
        found = _scan_all_cmdlines()
        return [x for x in found.get(key, []) if _pid_alive(x)]
    except Exception:
        try:
            return [x for x in _cmdline_pids(key) if _pid_alive(x)]
        except Exception:
            return []


def _log_tail(key, lines=12):
    """读服务日志尾部，启动失败时把真实报错甩给用户"""
    try:
        path = _log_path(key)
        if not path.is_file():
            return ''
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            body = handle.readlines()[-lines:]
        return ''.join(body).strip()
    except Exception:
        return ''


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


def _fast_kill(pid):
    """psutil 直接终止进程及其子进程；比 taskkill.exe 少起一个进程（省 ~180ms）"""
    if _psutil is None:
        return None
    try:
        p = _psutil.Process(int(pid))
        try:
            kids = p.children(recursive=True)
        except Exception:
            kids = []
        for c in kids:
            try:
                c.kill()
            except Exception:
                pass
        p.kill()
        return True
    except Exception:
        return None


def _taskkill(pid):
    code, out = _run(['taskkill', '/F', '/T', '/PID', str(pid)], timeout=20)
    return code == 0, (out or '').strip().replace('\r', ' ').replace('\n', ' ')


# ============================================================================
# NapCat 专用：登录二维码 + WebUI 信息
# ============================================================================
def _napcat_root():
    return _base() / '.vendor/.NapCat' / 'NapCat.Shell'


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


def read_tail(key, since=None, limit=1500, first_bytes=192 * 1024, day=None):
    """按字节偏移读日志。

    since=None 首次读：只取文件尾部 first_bytes，避免几十 MB 老日志拖死浏览器。
    since 有值：只读 since 之后的新内容（增量轮询用，几乎零成本）。
    返回 (lines, offset, size)。offset 永远停在最后一个换行之后，
    这样"半行"不会被截断返回，下次也不会重复。
    """
    path = _log_path(key, day)
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
    prev_shape = None   # 上一条的形状，用于相邻合并
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
        shp = (rec.get('lv'), shape_of(rec['msg']))
        if out and shp == prev_shape:
            top = out[-1]
            top['n'] = int(top.get('n') or 1) + 1
            top['last'] = ln
            continue
        rec['n'] = 1
        rec['_k'] = shp
        prev_shape = shp
        out.append(rec)
    if len(out) > 1:
        freq = {}
        for r in out:
            freq[r['_k']] = freq.get(r['_k'], 0) + 1
        keep, first = [], {}
        for r in out:
            k = r.pop('_k', None)
            if freq.get(k, 0) >= REPEAT_MIN and r.get('lv') != 'ERROR':
                if k in first:
                    top = first[k]
                    top['n'] = int(top.get('n') or 1) + int(r.get('n') or 1)
                    top['last'] = r.get('last') or r.get('txt')
                    continue
                first[k] = r
            keep.append(r)
        out = keep
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

    # 关键防线：现场再扫一次。_running() 可能依赖过期缓存，而外部（launcher.cmd、
    # 命令行）起的实例不会进内存句柄；不查就再起一个 → 两个进程抢同一个端口
    # （Werkzeug 允许端口复用，手机连到哪个进程是随机的，表现为时好时坏）
    others = _live_pids(key)
    if others:
        return False, {'status': 'error', 'running': True, 'pid': others[0],
                       'message': '已经有实例在跑（pid %s），先点停止再启动；'
                                  '重复启动会让两个进程抢同一个端口' % others[0]}

    ok, msg, proc = launcher.start(key, _base())
    if not ok:
        return False, {'status': 'error', 'message': msg}

    # 直接持有 Popen 句柄：之后判断"在不在跑 / pid 是多少"是 O(1)，
    # 不必再起 powershell 反查进程（这里原来有个 6×0.8s 的后台线程，已删除）。
    if proc is not None:
        # 进程立刻退出（端口被占、配置错、依赖缺失）要当场报出来，
        # 不能先显示"已启动"再等下一次刷新
        deadline = time.time() + 1.2
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.05)
        if proc.poll() is not None:
            tail = _log_tail(key)
            return False, {'status': 'error', 'running': False,
                           'message': '进程启动后立刻退出（exit=%s）%s'
                                      % (proc.returncode,
                                         ('：' + tail.splitlines()[-1][:160]) if tail else ''),
                           'detail': tail}
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
        def _stop_engine():
            try:
                from func.toolbox.flux_painter.config import TBFluxPainterConfig
                from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter
                get_managed_painter(TBFluxPainterConfig()).stop()
            except Exception:
                pass
        threading.Thread(target=_stop_engine, daemon=True).start()
        msgs.append('引擎正在后台停止（它自己的停下流程最长约 25 秒，不在界面上等）')

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
        try:
            if not _scan.get('busy') and time.time() - _scan.get('ts', 0) > 2:
                _scan['pids'] = _scan_all_cmdlines()      # 同步扫一次，~40ms
                _scan['ts'] = time.time()
        except Exception:
            pass
        pids = [x for x in _scan_pids(key) if _pid_alive(x)]
    if not pids and _psutil is None:
        pids = [x for x in _cmdline_pids(key) if _pid_alive(x)]

    for pid in pids:
        r = _fast_kill(pid)
        if r is None:
            ok, out = _taskkill(pid)
        else:
            ok, out = True, ''
        (killed if ok else failed).append(pid)
    if killed:
        msgs.append('已结束进程 ' + ','.join(str(x) for x in killed))

    # 复查：只针对刚杀掉的 pid，用 psutil 轮询（最多 0.25s）
    deadline = time.time() + 0.25
    leftover = list(killed)
    while leftover and time.time() < deadline:
        leftover = [x for x in leftover if _pid_alive(x)]
        if leftover:
            time.sleep(0.05)
    if leftover:
        failed.extend(leftover)
    if failed:
        msgs.append('这些杀不掉（权限？）: ' + ','.join(str(x) for x in failed))

    # 复查第二步：现场再扫一遍，确认这个服务真的没有残留进程
    # （快路径只杀"记录里的 pid"，外部起的实例、或被杀进程拉起的子进程会漏网，
    #  端口就会一直被占着，表现为"已停止"但下次启动失败/手机连到旧进程）
    time.sleep(0.15)
    stale = [x for x in _live_pids(key) if x not in killed]
    if stale:
        msgs.append('还有残留进程没结束: ' + ','.join(str(x) for x in stale) + '（可再点一次停止）')
        leftover = sorted(set(list(leftover) + stale))
    if not pids:
        msgs.append('没找到它的进程：可能本来就已停止，或不是从本界面启动的'
                    '（点 ⟳ 刷新可更新状态）')

    if key in _scan.get('pids', {}):
        _scan['pids'][key] = []          # 刚杀过的服务直接置空，不必 9 个服务全量重扫
    return jsonify({
        'status': 'ok',
        'message': '；'.join(m for m in msgs if m),
        'killed': killed, 'failed': failed,
        'running': bool(leftover),
    })


# ============================================================================
# 路由注册
# ============================================================================
# ============================================================================
# 进度：画图 / 语音 —— 数据全部从真实日志解析
#   绘画：logs/comfy_engine.log 的 tqdm 行（百分比/步进/已用/预计/速率）
#         + 当日主日志的 [flux_painter] 阶段行（档位/提示词/已提交/异常）
#   语音：当日主日志的「播放片段 N」、字幕 JSON（chatStatus + text）、打断行
#   不连接原项目的任何 WebSocket，不修改原项目任何文件。
# ============================================================================
_TQDM = re.compile(
    r'^\s*(?P<pct>\d{1,3})%\|[^|]*\|\s*(?P<cur>\d+)/(?P<tot>\d+)\s*\['
    r'(?P<el>\d+:\d+(?::\d+)?)<(?P<eta>\?|\d+:\d+(?::\d+)?)\s*,\s*(?P<rate>[\d.?]+)(?P<unit>it/s|s/it)\]')
_STAMP = re.compile(r'^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})')
_FLUX_STAGES = [
    (re.compile(r'绘图引擎就绪'), ('引擎就绪', 'running')),
    (re.compile(r'画质档位=(\S+?)[（(]'), ('准备画布', 'running')),
    (re.compile(r'法典自检'), ('检索画作法典', 'running')),
    (re.compile(r'提示词产出 title=(\S+?)\s'), ('提示词就绪', 'running')),
    (re.compile(r'任务已提交 clip=(\S+)'), ('已提交给引擎', 'running')),
    (re.compile(r'未解析到正向提示词'), ('提示词为空', 'error')),
    (re.compile(r'本次绘画提前结束'), ('提前结束', 'error')),
    (re.compile(r'图像已生成|出图完成|绘制完成'), ('出图完成', 'done')),
]
_TTS_SEG = re.compile(r'\[(?P<tid>[0-9a-fA-F-]{8,})\]\s*播放片段\s*(?P<n>\d+)')
_TTS_SUB = re.compile(
    r"'traceid':\s*'(?P<tid>[^']*)'\s*,\s*'chatStatus':\s*'(?P<st>[^']*)'"
    r"(?:\s*,\s*'text':\s*'(?P<tx>.*?)'\s*\})?")
_TTS_INT = re.compile(r'检测到用户开始说话')
PROG_FRESH = 120
REPEAT_MIN = 3


def _tail_lines(path, nbytes, limit=800):
    """读文件尾部若干行（已去 ANSI / 控制符 / 行内 \\r 原地刷新）"""
    try:
        if not path.is_file():
            return [], 0.0
        size = path.stat().st_size
        with open(path, 'rb') as f:
            f.seek(max(0, size - nbytes))
            blob = f.read()
    except Exception:
        return [], 0.0
    text = _decode(blob)
    out = []
    for ln in text.split('\n'):
        ln = _ANSI.sub('', ln).rstrip('\r')
        if '\r' in ln:
            ln = ln.split('\r')[-1]
        ln = _CTRL.sub('', ln).strip()
        if ln:
            out.append(ln)
    return out[-limit:], path.stat().st_mtime


def _epoch_of(ln):
    m = _STAMP.match(ln)
    if not m:
        return 0.0
    try:
        return time.mktime(time.strptime(m.group(1).replace('T', ' '), '%Y-%m-%d %H:%M:%S'))
    except Exception:
        return 0.0


def _hms(sec):
    if sec is None:
        return None
    parts = [int(x) for x in str(sec).split(':')]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _day_log():
    return _base() / 'logs' / ('log_%s.txt' % date.today().strftime('%Y-%m-%d'))


def read_progress():
    """画图 / 语音的当前进度（全部来自日志，取不到就是 idle）"""
    now = time.time()
    lines, mtime = _tail_lines(_day_log(), 256 * 1024)
    engine = SERVICES.get('painting', {}).get('log') or 'logs/comfy_engine.log'
    eng_lines, eng_mtime = _tail_lines(_base() / engine, 128 * 1024)

    paint = {'state': 'idle', 'age': None}
    tq = None
    for ln in reversed(eng_lines):
        m = _TQDM.match(ln)
        if m:
            tq = m
            break
    stage, detail, s_state, s_age = '', '', '', None
    for ln in reversed(lines):
        if 'flux_painter' not in ln:
            continue
        for rx, (txt, st) in _FLUX_STAGES:
            m = rx.search(ln)
            if m:
                stage, s_state = txt, st
                detail = (m.group(1) or '').strip() if m.groups() else ''
                ts = _epoch_of(ln)
                s_age = int(now - ts) if ts else None
                break
        if stage:
            break
    if tq and (now - eng_mtime) <= PROG_FRESH:
        pct = int(tq.group('pct'))
        paint = {
            'state': 'done' if pct >= 100 else 'running',
            'percent': pct,
            'step': '%s/%s' % (tq.group('cur'), tq.group('tot')),
            'elapsed': _hms(tq.group('el')),
            'eta': _hms(tq.group('eta')) if tq.group('eta').isdigit() or ':' in tq.group('eta') else None,
            'rate': tq.group('rate') + tq.group('unit'),
            'stage': stage or '引擎绘制中',
            'detail': detail,
            'age': int(now - eng_mtime),
        }
    elif s_state and s_age is not None and s_age <= PROG_FRESH:
        paint = {'state': s_state, 'stage': stage, 'detail': detail, 'age': s_age,
                 'percent': 100 if s_state == 'done' else None}
    elif s_state == 'error' and s_age is not None and s_age <= 1800:
        paint = {'state': 'error', 'stage': stage, 'detail': detail, 'age': s_age}

    tts = {'state': 'idle', 'age': None, 'seg': 0, 'total': 0, 'text': ''}
    seg = sub = intr = None
    seg_n = 0
    for ln in reversed(lines):
        if sub is None:
            m = _TTS_SUB.search(ln)
            if m:
                sub = (m.group('tid'), m.group('st'), (m.group('tx') or ''), _epoch_of(ln))
                continue
        if seg is None:
            m = _TTS_SEG.search(ln)
            if m:
                seg = (m.group('tid'), int(m.group('n')), _epoch_of(ln))
                continue
        if intr is None and _TTS_INT.search(ln):
            intr = _epoch_of(ln)
            continue
        if sub and seg and intr:
            break
    if seg is not None or sub is not None:
        tid = (seg[0] if seg else (sub[0] if sub else ''))
        seg_n = sum(1 for ln in lines if _TTS_SEG.search(ln) and _TTS_SEG.search(ln).group('tid') == tid)
    cands = [x for x in (
        ('intr', intr), ('sub', sub[3] if sub else None), ('seg', seg[2] if seg else None)) if x[1]]
    if cands:
        newest = max(cands, key=lambda x: x[1])
        age = int(now - newest[1])
        if newest[0] == 'intr' and age <= 600:
            tts = {'state': 'interrupted', 'age': age, 'seg': seg[1] if seg else 0,
                   'total': seg_n, 'text': sub[2] if sub else ''}
        elif age <= 600 and sub and sub[1] == 'end':
            tts = {'state': 'idle', 'age': age, 'seg': 0, 'total': 0, 'text': ''}
        elif age <= 600:
            tts = {'state': 'playing', 'age': age, 'seg': seg[1] if seg else 0,
                   'total': seg_n, 'text': (sub[2] if sub else '')}
    return {'paint': paint, 'tts': tts, 'ts': int(now)}


def register(app, base_dir=None, gui_dir=None):
    global _BASE, _GUI
    if base_dir:
        _BASE = Path(base_dir).resolve()
    if gui_dir:
        _GUI = Path(gui_dir).resolve()
    if _GUI is None:
        _GUI = Path(__file__).resolve().parent.parent      # gui/
    _register_webdriver_api(app)

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
            _ensure_scan(600)      # 平时 10 分钟才扫一次；点 ⟳ (deep=1) 立刻重扫
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
        day = request.args.get('date') or None
        lines, offset, size = read_tail(key, since, limit, day=day)
        run, pid, ports = _running(key)
        return jsonify({'status': 'ok', 'key': key, 'lines': lines,
                        'offset': offset, 'size': size,
                        'running': run, 'pid': pid, 'ports': ports})



    @app.route('/api/logs/progress')
    def _loghub_progress():
        return jsonify(read_progress())

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

def _register_webdriver_api(app):
    """Selenium 驱动状态 / 一键下载（网页搜索真实浏览器抓取用）"""
    try:
        from func.database.search.spider.selenium_spider import CatLearnSeleniumSpider
    except Exception as e:
        print('[webdriver] 导入失败:', e)
        return
    from flask import jsonify

    @app.route('/api/webdriver/status')
    def _webdriver_status():
        try:
            sp = CatLearnSeleniumSpider()
            ver = sp.edge_version()
            p = sp.ensure_driver()
            dv = sp._driver_version(p) if p else ''
            return jsonify({'ok': bool(p), 'edge_version': ver, 'driver_version': dv,
                            'driver_path': p or '',
                            'match': bool(p) and bool(ver) and dv.split('.')[0] == ver.split('.')[0],
                            'download_url': ('https://msedgedriver.microsoft.com/%s/edgedriver_win64.zip' % ver) if ver else '',
                            'official_url': 'https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/'})
        except Exception as e:
            return jsonify({'ok': False, 'error': '%s: %s' % (type(e).__name__, str(e)[:120])})

    @app.route('/api/webdriver/install', methods=['POST'])
    def _webdriver_install():
        try:
            sp = CatLearnSeleniumSpider()
            ver = sp.edge_version()
            CatLearnSeleniumSpider._driver_path = ""
            p = sp._download_driver(ver) if ver else ''
            return jsonify({'ok': bool(p), 'driver_path': p or '',
                            'driver_version': sp._driver_version(p) if p else '',
                            'edge_version': ver})
        except Exception as e:
            return jsonify({'ok': False, 'error': '%s: %s' % (type(e).__name__, str(e)[:120])})
    print('[webdriver] 已注册 /api/webdriver/status 与 /api/webdriver/install')


