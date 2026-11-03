# -*- coding: utf-8 -*-
# gui/tools/catpaws_sign.py
"""CatPaws 签名信息（bundle id / 签名后缀）获取与同步。

重签重装后签名器会给 bundle id 加后缀（例如 ...xctrunner.D79NHBM8JL →
...xctrunner.27KKPW936V）。launcher 的 config.json 和 CatPaws 服务端的
config.yml 各缓存了一份 id，对不上时 runwda 只会报
"Did not find test app ... Is it installed?"，表现就是 WDA 永远拉不起来。

本工具从设备上读出实际安装的 id，和两处配置比对，可选写回。

用法：
    runtime\\311\\python.exe gui\\tools\\catpaws_sign.py            # 只看
    runtime\\311\\python.exe gui\\tools\\catpaws_sign.py --apply     # 写回配置
    runtime\\311\\python.exe gui\\tools\\catpaws_sign.py --json      # 机器可读
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from flask import jsonify

BASE_DIR = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = BASE_DIR / '.vendor' / '.CatPaws' / 'catpaws-launcher'
IOS_EXE = LAUNCHER_DIR / 'ios.exe'
LAUNCHER_CONFIG = LAUNCHER_DIR / 'config.json'
SERVER_CONFIG = BASE_DIR / '.vendor' / '.CatPaws' / 'config.yml'

RUNNER_PREFIX = 'com.facebook.WebDriverAgentRunner.xctrunner'
CATCAM_PREFIX = 'com.meowlisis.catcam'
APP_LINE = re.compile(r'^(\S+)\s+(.+?)\s+(\S+)\s*$')
UDID_LINE = re.compile(r'"deviceList"\s*:\s*\[\s*"([0-9A-Fa-f\-]+)"')

# 三处缓存：(配置文件, 键名, 界面上的说法)
SLOTS = (
    ('launcher', 'config.json', 'runner_id', 'launcher runner_id'),
    ('server', 'config.yml', 'runner_bundle_id', '服务端 runner_bundle_id'),
    ('server', 'config.yml', 'catcam_bundle_id', '服务端 catcam_bundle_id'),
)


def _run_ios(args, timeout=30):
    """跑 ios.exe，返回 stdout；失败返回空串（不抛异常，接口不能被设备状态拖挂）"""
    if not IOS_EXE.is_file():
        return ''
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    try:
        proc = subprocess.run(
            [str(IOS_EXE)] + list(args),
            cwd=str(LAUNCHER_DIR),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            creationflags=flags,
        )
    except Exception:
        return ''
    return proc.stdout or ''


def _version_key(text):
    """1.4.0 / 1.0.7 排序用；解析不了当 0.0"""
    nums = re.findall(r'\d+', str(text or ''))
    return tuple(int(n) for n in nums[:4]) or (0,)


def list_apps():
    """设备上已安装的 app： [{id, name, version}]"""
    apps = []
    for line in _run_ios(['apps', '--list']).splitlines():
        match = APP_LINE.match(line.strip())
        if not match:
            continue
        apps.append({'id': match.group(1), 'name': match.group(2), 'version': match.group(3)})
    return apps


def _pick(apps, prefix):
    """按 id 前缀取最新的那个（旧版本可能没卸干净，排序后取最高版本）"""
    hits = [app for app in apps if app['id'].startswith(prefix)]
    if not hits:
        return None, []
    hits.sort(key=lambda app: _version_key(app['version']), reverse=True)
    return hits[0], hits[1:]


def _suffix(bundle_id, prefix):
    """从 ...xctrunner.27KKPW936V / ...catcam.27KKPW936V 里取签名后缀"""
    if not bundle_id or not bundle_id.startswith(prefix):
        return ''
    rest = bundle_id[len(prefix):].lstrip('.')
    return rest.split('.')[0] if rest else ''


def _launcher_value(key):
    try:
        data = json.loads(LAUNCHER_CONFIG.read_text(encoding='utf-8'))
    except Exception:
        return ''
    return str(data.get(key) or '').strip()


def _server_value(key):
    try:
        text = SERVER_CONFIG.read_text(encoding='utf-8')
    except Exception:
        return ''
    for line in text.splitlines():
        match = re.match(r'^\s*%s:\s*(\S+)\s*$' % re.escape(key), line)
        if match:
            return match.group(1).strip()
    return ''


def _read(slot, key):
    return _launcher_value(key) if slot == 'launcher' else _server_value(key)


def probe():
    """设备实际签名 + 三处缓存配置，返回差异清单（前端直接吃这个）"""
    apps = list_apps()
    runner, runner_others = _pick(apps, RUNNER_PREFIX)
    catcam, _ = _pick(apps, CATCAM_PREFIX)
    udid_match = UDID_LINE.search(_run_ios(['list'], timeout=20))

    runner_id = runner['id'] if runner else ''
    catcam_id = catcam['id'] if catcam else ''
    suffix = _suffix(runner_id, RUNNER_PREFIX) or _suffix(catcam_id, CATCAM_PREFIX)

    expected = {'runner_id': runner_id, 'runner_bundle_id': runner_id, 'catcam_bundle_id': catcam_id}
    rows, stale = [], []
    for slot, filename, key, label in SLOTS:
        current = _read(slot, key)
        want = expected.get(key, '')
        ok = bool(current and want and current == want)
        rows.append({'slot': slot, 'file': filename, 'key': key, 'label': label,
                     'current': current, 'expected': want, 'ok': ok})
        if not ok:
            stale.append(rows[-1])

    problems = []
    if not apps:
        problems.append('读不到设备 app 列表：手机没插/没解锁/没信任，或 ios.exe 缺失')
    elif not runner_id:
        problems.append('设备上没装 CatPaws runner：用 iloader 重装（7 天证书到期也会这样）')
    elif not catcam_id:
        problems.append('设备上没装 CatCam')
    elif _suffix(catcam_id, CATCAM_PREFIX) != suffix:
        problems.append('CatCam 与 runner 的签名后缀不一致（装了不同批次的包？）')

    return {
        'status': 'ok',
        'ok': bool(runner_id) and not problems,
        'device': udid_match.group(1) if udid_match else '',
        'runner': runner or {},
        'catcam': catcam or {},
        'runner_others': runner_others,
        'suffix': suffix,
        'configs': rows,
        'stale': stale,
        'problems': problems,
        'paths': {'launcher': str(LAUNCHER_CONFIG), 'server': str(SERVER_CONFIG)},
    }


def _write_launcher(updates):
    try:
        data = json.loads(LAUNCHER_CONFIG.read_text(encoding='utf-8'))
    except Exception:
        data = {}
    data.update(updates)
    LAUNCHER_CONFIG.write_text(
        json.dumps(data, ensure_ascii=False, indent=4) + '\n', encoding='utf-8')


def _write_server(updates):
    """只改那两行，避免 yaml 重新序列化把整份配置的格式搅乱"""
    text = SERVER_CONFIG.read_text(encoding='utf-8')
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        for key, value in updates.items():
            match = re.match(r'^(\s*)%s:\s*\S*\s*$' % re.escape(key), line.rstrip('\r\n'))
            if not match:
                continue
            lines[index] = '%s%s: %s\n' % (match.group(1), key, value)
    SERVER_CONFIG.write_text(''.join(lines), encoding='utf-8')


def apply(snapshot):
    """把差异写回两处配置；返回实际写过的 [{file, key, value}]"""
    launcher_updates, server_updates, written = {}, {}, []
    for row in snapshot.get('stale') or []:
        if not row.get('expected'):
            continue
        if row['slot'] == 'launcher':
            launcher_updates[row['key']] = row['expected']
        else:
            server_updates[row['key']] = row['expected']
        written.append({'file': row['file'], 'key': row['key'],
                        'from': row['current'], 'value': row['expected']})
    if launcher_updates:
        _write_launcher(launcher_updates)
    if server_updates:
        _write_server(server_updates)
    return written


def _label(app):
    """显示名里常常已经带了版本号（"CatPaws 1.0.7"），别重复拼"""
    name = str(app.get('name') or '')
    version = str(app.get('version') or '')
    if version and not name.endswith(version):
        name = ('%s %s' % (name, version)).strip()
    return name


def _print_report(snapshot):
    print('== CatPaws 签名 ==')
    print('UDID        : %s' % (snapshot['device'] or '（没读到设备）'))
    runner = snapshot['runner']
    print('Runner id   : %s%s' % (
        runner.get('id') or '（未安装）',
        '  (%s)' % _label(runner) if runner else ''))
    catcam = snapshot['catcam']
    print('CatCam id   : %s%s' % (
        catcam.get('id') or '（未安装）',
        '  (%s)' % _label(catcam) if catcam else ''))
    print('签名后缀    : %s' % (snapshot['suffix'] or '-'))
    for other in snapshot.get('runner_others') or []:
        print('  另有旧 runner: %s (%s)' % (other['id'], other.get('version')))
    print()
    print('%-16s %-22s %-12s %s' % ('配置', '键', '状态', '当前值'))
    for row in snapshot['configs']:
        print('%-16s %-22s %-12s %s' % (
            row['file'], row['key'], ' 一致' if row['ok'] else ' 不一致',
            row['current'] or '（空）'))
    for problem in snapshot.get('problems') or []:
        print('!! %s' % problem)


def main():
    parser = argparse.ArgumentParser(description='获取 CatPaws 签名后缀并同步配置')
    parser.add_argument('--apply', action='store_true', help='把差异写回 launcher/服务端配置')
    parser.add_argument('--json', action='store_true', help='输出 JSON（供前端或脚本使用）')
    args = parser.parse_args()

    snapshot = probe()
    if args.apply:
        if snapshot['runner'] or snapshot['catcam']:
            written = apply(snapshot)
            snapshot = probe()
            snapshot['written'] = written
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0 if snapshot['ok'] else 1
    _print_report(snapshot)
    if snapshot.get('written'):
        print()
        print('已写回：')
        for item in snapshot['written']:
            print('  %s  %s = %s' % (item['file'], item['key'], item['value']))
    elif args.apply:
        print()
        print('配置已是最新，无需写回。')
    return 0 if snapshot['ok'] else 1


# ===== GUI 接口（config_gui.py 注册，面板「获取签名」按钮用） =====
def register(app):
    @app.route('/api/catpaws/sign')
    def _catpaws_sign():
        return jsonify(probe())

    @app.route('/api/catpaws/sign/apply', methods=['POST'])
    def _catpaws_sign_apply():
        snapshot = probe()
        if not snapshot['runner'] and not snapshot['catcam']:
            return jsonify({'status': 'error', 'message': '设备上读不到 CatPaws/CatCam，先插线解锁'}), 400
        written = apply(snapshot)
        after = probe()
        after['written'] = written
        return jsonify(after)


if __name__ == '__main__':
    sys.exit(main())
