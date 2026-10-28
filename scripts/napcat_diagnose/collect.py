#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""NapCat / QQ 登录态观测采集器（**只读**，不修改任何配置、不动任何 QQ 文件）

子命令
    snap   单次全量快照（文件元数据+哈希、注册表、进程模块、命名管道、网络、NapCat 产物、系统事件）
    watch  持续采集（1s 文件轮询 / 5s 进程+网络+管道 / 30s 注册表），落 events.jsonl

用法（建议管理员权限运行）
    runtime\311\python.exe scripts\napcat_diagnose\collect.py snap  --session A --label 00-before
    runtime\311\python.exe scripts\napcat_diagnose\collect.py watch --session A --duration 1800

输出
    scripts\napcat_diagnose\out\<session>\snap_<label>.json
    scripts\napcat_diagnose\out\<session>\events.jsonl
    scripts\napcat_diagnose\out\<session>\meta.json

安全约定：文件只读元数据与哈希；注册表值只保存 长度+哈希，短明文才保留原文；
不复制、不导出任何 QQ 数据文件本体。
"""

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    import psutil
except ImportError:
    sys.exit("需要 psutil：runtime\\311\\python.exe -m pip install psutil")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
# 默认落在脚本目录下；被权限挡住时可用环境变量 NAP_DIAG_OUT 指到别处
OUT_ROOT = os.environ.get('NAP_DIAG_OUT') or os.path.join(HERE, 'out')

# 大媒体目录直接跳过（占了 99% 的文件量，对登录态没有信息量）
SKIP_RE = re.compile(
    r'\\(Emoji|Pic|Video|File|avatar|Ptt|ams|dataline|VideoThumb|EmojiThumb|node_modules|static\\assets)\\|'
    r'\\log\\qq-log_|\\log-cache\\|\\nt_db\\.*\.material$|\\cache\\(?!qrcode)',
    re.IGNORECASE)

HASH_FULL_LIMIT = 2 * 1024 * 1024      # <=2MB 全量 sha256
HASH_EDGE = 64 * 1024                  # 大文件只算头尾 64KB + 长度

REL_PROC = {'qq.exe', 'napcatwinbootmain.exe', 'napcatwinboot.exe'}
REL_NAME_RE = re.compile(r'^(qq|napcat|napcatwinbootmain|napcatwinboot)\.exe$', re.IGNORECASE)
MOD_HINT = re.compile(r'napcat|hook|wrapper|qqnt|qq\.exe', re.IGNORECASE)
PIPE_HINT = re.compile(r'napcat|mojo|qq', re.IGNORECASE)

REG_KEYS = [('HKCU', r'Software\Tencent'),
            ('HKLM', r'SOFTWARE\Tencent'),
            ('HKLM', r'SOFTWARE\WOW6432Node\Tencent')]
REG_MAX_DEPTH = 7


# ---------------------------------------------------------------- 工具

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='milliseconds')


def rel(path, base):
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


def digest_file(path, size):
    """小文件全量、大文件头尾+长度。返回 None 表示读不了（被占用/无权限）。"""
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            if size <= HASH_FULL_LIMIT:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
            else:
                h.update(f.read(HASH_EDGE))
                f.seek(-HASH_EDGE, os.SEEK_END)
                h.update(f.read(HASH_EDGE))
                h.update(str(size).encode())
    except OSError:
        return None
    return h.hexdigest()[:32]


def scan_tree(base, do_hash=True):
    """返回 {relpath: [size, mtime_ns, ctime_ns, attrs, hash]}"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(base, topdown=True):
        dirnames[:] = [d for d in dirnames
                       if not SKIP_RE.search(os.path.join(dirpath, d) + '\\')]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            r = rel(full, base)
            if SKIP_RE.search('\\' + r):
                continue
            try:
                st = os.stat(full, follow_symlinks=False)
            except OSError:
                continue
            out[r] = [st.st_size, st.st_mtime_ns, st.st_ctime_ns,
                      int(getattr(st, 'st_file_attributes', 0)),
                      digest_file(full, st.st_size) if do_hash else None]
    return out


# ---------------------------------------------------------------- 路径清单

def napcat_roots():
    shell = os.path.join(ROOT, '.vendor', '.NapCat', 'NapCat.Shell')
    hits = glob.glob(os.path.join(shell, 'versions', '*', 'resources', 'app', 'napcat'))
    return hits


# 只盯 QQ 相关目录：整个 Tencent 目录含 WeMeet/xwechat 等，几千个文件、2GB+，
# 与 QQ 登录态无关还极慢。
QQ_APPDATA_SUB = ('QQ', 'QQNT', 'qimei', 'beacon', 'libsdk', 'Logs')


def default_roots():
    """返回 [(tag, base, 是否算哈希)]；非 QQ 数据区只记 size/mtime，不算哈希。"""
    roots = []
    tf = r'D:\QQ\files\TencentFiles\Tencent Files'
    if os.path.isdir(tf):
        roots.append(('qq-data', tf, True))
    for env, tag in ((os.environ.get('APPDATA'), 'appdata'),
                     (os.environ.get('LOCALAPPDATA'), 'localappdata')):
        if not env:
            continue
        for sub in QQ_APPDATA_SUB:
            p = os.path.join(env, 'Tencent', sub)
            if os.path.isdir(p):
                roots.append(('%s-%s' % (tag, sub), p, False))
    docs = os.path.join(os.environ.get('USERPROFILE', ''), 'Documents', 'Tencent Files')
    if os.path.isdir(docs):
        roots.append(('documents', docs, False))
    for i, p in enumerate(napcat_roots()):
        roots.append(('napcat-app%d' % i, p, True))
    return roots


# ---------------------------------------------------------------- 注册表

def _ser_val(data, typ):
    import winreg
    if typ in (winreg.REG_BINARY,):
        raw = bytes(data)
    elif isinstance(data, str):
        raw = data.encode('utf-8', 'replace')
    else:
        raw = str(data).encode()
    item = {'t': typ, 'n': len(raw),
            'h': hashlib.sha256(raw).hexdigest()[:32]}
    # 只保留短的、看得懂的明文；长串/二进制一律只留哈希
    if isinstance(data, str) and len(data) <= 48 and not re.fullmatch(r'[A-Za-z0-9+/=]{24,}', data):
        item['raw'] = data
    elif isinstance(data, int):
        item['raw'] = data
    return item


def walk_reg(hive, hive_name, path, acc, depth=0):
    import winreg
    if depth > REG_MAX_DEPTH:
        return
    try:
        key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ)
    except OSError:
        return
    with key:
        vals = {}
        i = 0
        while True:
            try:
                vn, vd, vt = winreg.EnumValue(key, i)
            except OSError:
                break
            vals[vn or '(default)'] = _ser_val(vd, vt)
            i += 1
        if vals:
            acc['%s\\%s' % (hive_name, path)] = vals
        subs = []
        i = 0
        while True:
            try:
                subs.append(winreg.EnumKey(key, i))
            except OSError:
                break
            i += 1
        for s in subs:
            walk_reg(hive, hive_name, path + '\\' + s, acc, depth + 1)


def registry_snapshot():
    import winreg
    hives = {'HKCU': winreg.HKEY_CURRENT_USER, 'HKLM': winreg.HKEY_LOCAL_MACHINE}
    acc = {}
    for name, path in REG_KEYS:
        walk_reg(hives[name], name, path, acc)
    return acc


# ---------------------------------------------------------------- 进程 / 管道 / 网络

def related_proc(name, cmd):
    """只认真正的 QQ / NapCat 进程；别把我们自己的 python/powershell 抓进来。"""
    if REL_NAME_RE.match(name or ''):
        return True
    if re.match(r'^(node|electron)\.exe$', name or '', re.IGNORECASE) and 'napcat' in (cmd or '').lower():
        return True
    return False


def process_snapshot(with_modules=True):
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'exe', 'cmdline', 'ppid',
                                  'create_time', 'username', 'num_threads',
                                  'num_handles', 'memory_info']):
        info = p.info
        name = info.get('name') or ''
        cmd = ' '.join(info.get('cmdline') or [])
        if info['pid'] == os.getpid() or not related_proc(name, cmd):
            continue
        item = {
            'pid': info['pid'], 'ppid': info.get('ppid'), 'name': name,
            'exe': info.get('exe'), 'cmdline': cmd,
            'create_time': info.get('create_time'),
            'user': info.get('username'),
            'threads': info.get('num_threads'), 'handles': info.get('num_handles'),
            'rss_mb': round((info.get('memory_info').rss if info.get('memory_info') else 0) / 1048576, 1),
            'electron_type': (re.search(r'--type=([\w-]+)', cmd).group(1)
                              if re.search(r'--type=([\w-]+)', cmd) else None),
        }
        if with_modules:
            mods = []
            try:
                for m in p.memory_maps():
                    if m.path and MOD_HINT.search(m.path):
                        mods.append(m.path)
            except Exception as e:
                item['modules_error'] = str(e)
            item['modules'] = sorted(set(mods))
        try:
            item['children'] = [c.pid for c in p.children(recursive=False)]
        except Exception:
            item['children'] = []
        procs.append(item)
    procs.sort(key=lambda x: x['pid'])
    return procs


def qq_pids(procs=None):
    procs = procs if procs is not None else process_snapshot(with_modules=False)
    out = set()
    for p in procs:
        if (p.get('name') or '').lower() in REL_PROC:
            out.add(p['pid'])
        else:
            out.add(p['pid'])          # 包含 NapCat 启动器等
    return out


def pipe_snapshot(pids=None):
    """只看 NapCat 自己的管道，和 PID 属于 QQ 的 mojo 管道；别把整机 Chromium 的都列出来。"""
    try:
        names = os.listdir('\\\\.\\pipe\\')
    except OSError:
        return []
    hits = []
    for n in names:
        low = n.lower()
        if 'napcat' in low:
            hits.append(n)
            continue
        m = re.search(r'mojo\.(\d+)\.', n)
        if m and pids and int(m.group(1)) in pids:
            hits.append(n)
    return sorted(hits)


def net_snapshot(pids, with_dns=False):
    items = []
    try:
        conns = psutil.net_connections(kind='inet')
    except Exception:
        conns = []
    for c in conns:
        if c.pid and c.pid in pids:
            items.append({
                'pid': c.pid, 'status': c.status,
                'laddr': '%s:%s' % (c.laddr.ip, c.laddr.port) if c.laddr else None,
                'raddr': '%s:%s' % (c.raddr.ip, c.raddr.port) if c.raddr else None,
            })
    items.sort(key=lambda x: (x['pid'], str(x['laddr']), str(x['raddr'])))
    out = {'conns': items}
    if with_dns:
        names = []
        try:
            txt = subprocess.run(['ipconfig', '/displaydns'], capture_output=True,
                                 timeout=20).stdout
            for enc in ('gbk', 'utf-8', 'latin-1'):
                try:
                    txt = txt.decode(enc)
                    break
                except Exception:
                    continue
            names = sorted(set(re.findall(r'Record Name\s*\.*\s*:\s*(\S+)|记录名称\s*\.*\s*:\s*(\S+)',
                                          txt if isinstance(txt, str) else '')))
            names = sorted({a or b for a, b in names})
        except Exception as e:
            out['dns_error'] = str(e)
        out['dns'] = names
    return out


# ---------------------------------------------------------------- NapCat 产物

def napcat_snapshot():
    out = {'qrcode': [], 'config': [], 'logs': [], 'listening': []}
    for root in napcat_roots():
        for p in glob.glob(os.path.join(root, 'cache', 'qrcode.png')):
            try:
                st = os.stat(p)
                out['qrcode'].append({'path': p, 'size': st.st_size, 'mtime': st.st_mtime})
            except OSError:
                pass
        for p in glob.glob(os.path.join(root, 'config', '*.json')):
            try:
                st = os.stat(p)
                out['config'].append({'name': os.path.basename(p), 'size': st.st_size,
                                      'mtime': st.st_mtime,
                                      'hash': digest_file(p, st.st_size)})
            except OSError:
                pass
        for p in glob.glob(os.path.join(root, 'logs', '*.log')):
            try:
                st = os.stat(p)
                out['logs'].append({'name': os.path.basename(p), 'size': st.st_size,
                                    'mtime': st.st_mtime})
            except OSError:
                pass
    try:
        for c in psutil.net_connections(kind='inet'):
            if c.status == 'LISTEN' and c.laddr and c.laddr.port in (3001, 3000, 6099, 3002):
                out['listening'].append('%s:%s' % (c.laddr.ip, c.laddr.port))
    except Exception:
        pass
    # 会话目录（哪个 QQ 账号在用）
    tf = r'D:\QQ\files\TencentFiles\Tencent Files'
    if os.path.isdir(tf):
        out['account_dirs'] = sorted(d for d in os.listdir(tf)
                                     if os.path.isdir(os.path.join(tf, d)))
    return out


def events_snapshot(max_events=60):
    ps = ('Get-WinEvent -LogName Application -MaxEvents %d -ErrorAction SilentlyContinue | '
          'Select-Object TimeCreated,Id,LevelDisplayName,ProviderName,@{n="Msg";e={$_.Message}} | '
          'ConvertTo-Json -Compress -Depth 3') % max_events
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                           capture_output=True, timeout=60)
        txt = r.stdout.decode('utf-8', 'replace').strip()
        if not txt:
            return []
        data = json.loads(txt)
        if isinstance(data, dict):
            data = [data]
        keep = []
        for e in data:
            msg = str(e.get('Msg') or '')
            if re.search(r'qq|tencent|napcat', msg, re.I) or re.search(
                    r'qq|tencent', str(e.get('ProviderName') or ''), re.I):
                e['Msg'] = msg[:400]
                keep.append(e)
        return keep[:20]
    except Exception as e:
        return [{'error': str(e)}]


# ---------------------------------------------------------------- 快照 / 采集

def make_snapshot(session_dir, label, with_modules=True, with_events=True, meta_only=False):
    t0 = time.time()
    snap = {'meta': {'session': os.path.basename(session_dir), 'label': label,
                     'ts': time.time(), 'iso': now_iso(),
                     'argv': sys.argv, 'pid': os.getpid()},
            'files': {}, 'registry': {}, 'processes': [], 'pipes': [],
            'net': {}, 'napcat': {}, 'events': []}
    for tag, base, do_hash in default_roots():
        snap['files'][tag] = {'base': base, 'tree': scan_tree(base, do_hash and not meta_only)}
    try:
        snap['registry'] = registry_snapshot()
    except Exception as e:
        snap['registry'] = {'__error__': str(e)}
    procs = process_snapshot(with_modules=with_modules)
    snap['processes'] = procs
    snap['pipes'] = pipe_snapshot(qq_pids(procs))
    snap['net'] = net_snapshot(qq_pids(procs))
    snap['napcat'] = napcat_snapshot()
    if with_events:
        snap['events'] = events_snapshot()
    snap['meta']['elapsed'] = round(time.time() - t0, 2)
    path = os.path.join(session_dir, 'snap_%s.json' % label)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False)
    os.replace(tmp, path)
    return path, snap


class Writer:
    def __init__(self, path):
        self.f = open(path, 'a', encoding='utf-8', buffering=1)
        self.t0 = time.time()

    def emit(self, kind, **kw):
        rec = {'t': round(time.time() - self.t0, 3), 'iso': now_iso(), 'kind': kind}
        rec.update(kw)
        self.f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


def watch(session_dir, duration, interval_files=1.0, interval_proc=5.0,
          interval_reg=30.0, with_modules=False, meta_only=False):
    w = Writer(os.path.join(session_dir, 'events.jsonl'))
    all_roots = default_roots()
    # watch 只盯"会变的那几个"
    roots = [(tag, base, dh and not meta_only) for tag, base, dh in all_roots
             if tag.startswith(('qq-data', 'napcat-app'))]
    state = {}
    for tag, base, dh in roots:
        state[tag] = scan_tree(base, dh)
    last_proc = last_reg = 0.0
    last_proc_state = {}
    w.emit('start', roots=[{'tag': t, 'base': b} for t, b, _ in roots],           files={t: len(v) for t, v in state.items()})
    deadline = time.time() + duration if duration > 0 else None
    print('[watch] 开始，按 Ctrl+C 结束；输出 %s' % os.path.join(session_dir, 'events.jsonl'))
    try:
        while True:
            if deadline and time.time() > deadline:
                break
            # 1) 文件轮询
            for tag, base, dh in roots:
                cur = scan_tree(base, dh)
                prev = state[tag]
                for r, v in cur.items():
                    if r not in prev:
                        w.emit('file_add', root=tag, path=r, size=v[0], hash=v[4])
                    elif prev[r][0] != v[0] or prev[r][1] != v[1] or prev[r][4] != v[4]:
                        w.emit('file_mod', root=tag, path=r, size=v[0], d_size=v[0] - prev[r][0],
                               hash=v[4], d_hash=(v[4] != prev[r][4]))
                for r in prev.keys() - cur.keys():
                    w.emit('file_del', root=tag, path=r)
                state[tag] = cur
            # 2) 进程 / 管道 / 网络
            now = time.time()
            if now - last_proc >= interval_proc:
                last_proc = now
                procs = process_snapshot(with_modules=with_modules)
                sig = {p['pid']: (p.get('name'), p.get('electron_type'), p.get('threads'))
                       for p in procs}
                for pid, s in sig.items():
                    if pid not in last_proc_state:
                        w.emit('proc_add', pid=pid, name=s[0], etype=s[1])
                    elif last_proc_state[pid] != s:
                        w.emit('proc_mod', pid=pid, before=list(last_proc_state[pid]), after=list(s))
                for pid in last_proc_state.keys() - sig.keys():
                    w.emit('proc_del', pid=pid)
                last_proc_state = sig
                w.emit('pipes', names=pipe_snapshot(qq_pids(procs)))
                net = net_snapshot(qq_pids(procs))
                w.emit('net', conns=net['conns'][:80])
                w.emit('napcat', data=napcat_snapshot())
            # 3) 注册表（低频）
            if now - last_reg >= interval_reg:
                last_reg = now
                reg = registry_snapshot()
                w.emit('registry', keys=len(reg), data=reg)
            time.sleep(interval_files)
    except KeyboardInterrupt:
        w.emit('stop', reason='interrupt')
    finally:
        w.emit('stop', reason='done')
        w.close()
        make_snapshot(session_dir, 'final', with_modules=with_modules, meta_only=meta_only)
        print('[watch] 结束，final 快照已写入')


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description='NapCat/QQ 登录态观测采集器（只读）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    s1 = sub.add_parser('snap', help='单次全量快照')
    s1.add_argument('--session', required=True)
    s1.add_argument('--label', default=None)
    s1.add_argument('--no-modules', action='store_true')
    s1.add_argument('--no-events', action='store_true')
    s1.add_argument('--meta-only', action='store_true', help='只记 size/mtime，不算哈希（最快，适合"扫码瞬间"）')

    s2 = sub.add_parser('watch', help='持续采集')
    s2.add_argument('--session', required=True)
    s2.add_argument('--duration', type=int, default=1800, help='秒，0=不自动停')
    s2.add_argument('--modules', action='store_true', help='每轮也抓模块列表（更慢）')
    s2.add_argument('--meta-only', action='store_true')

    args = ap.parse_args()
    session_dir = os.path.join(OUT_ROOT, args.session)
    os.makedirs(session_dir, exist_ok=True)
    meta_path = os.path.join(session_dir, 'meta.json')
    if not os.path.exists(meta_path):
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump({'created': now_iso(), 'host': os.environ.get('COMPUTERNAME'),
                       'user': os.environ.get('USERNAME')}, f, ensure_ascii=False, indent=2)

    if args.cmd == 'snap':
        label = args.label or datetime.now().strftime('%H%M%S')
        path, snap = make_snapshot(session_dir, label,
                                   with_modules=not args.no_modules,
                                   with_events=not args.no_events,
                                   meta_only=args.meta_only)
        print('快照: %s  (%.1fs, 文件 %d 个, 进程 %d 个, 管道 %d 个, 连接 %d 条)'
              % (path, snap['meta']['elapsed'],
                 sum(len(v['tree']) for v in snap['files'].values()),
                 len(snap['processes']), len(snap['pipes']),
                 len(snap['net'].get('conns', []))))
    else:
        watch(session_dir, args.duration, with_modules=args.modules,
              meta_only=args.meta_only)


if __name__ == '__main__':
    main()
