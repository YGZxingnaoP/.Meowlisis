#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""NapCat 无窗口化所需的配置改动（幂等，自动备份，可回退）

为什么必须改：
    napcat.quick.bat 只有两行 —— `NapCatWinBootMain.exe 10086` + `pause`。
    NapCat 是注入到 QQ.exe 里跑的，日志走它自己的 logger：
        consoleLog: true  → 打到控制台窗口
        fileLog:    false → 不落盘
    所以一旦按 loghub 的方式去掉控制台，它的日志就哪儿都没有了。
    把 fileLog 改成 true 之后，日志会落到 NapCat 自己的 logs 目录，
    登录二维码本来就有 PNG（resources/app/napcat/cache/qrcode.png），
    于是 NapCat 也能无窗口运行，扫的码在 /logs 页面里显示。

用法：
    D:\.Meowlisis\runtime\python.exe D:\.Meowlisis\gui\tools\napcat_setup.py           # 只看现状
    ... --apply                                                                          # 改（备份后）
    ... --revert                                                                         # 还原备份
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))          # D:\.Meowlisis
SHELL_DIR = os.path.join(ROOT, '.NapCat', 'NapCat.Shell')
CONFIG_GLOB = os.path.join(SHELL_DIR, 'versions', '*', 'resources', 'app', 'napcat', 'config', 'napcat.json')
QR_GLOB = os.path.join(SHELL_DIR, 'versions', '*', 'resources', 'app', 'napcat', 'cache', 'qrcode.png')


def find(pat):
    hits = sorted(glob.glob(pat))
    return hits[-1] if hits else None


def show():
    cfg_path = find(CONFIG_GLOB)
    qr_path = find(QR_GLOB)
    print('NapCat Shell : %s' % SHELL_DIR)
    print('配置文件     : %s' % (cfg_path or '（找不到）'))
    if cfg_path:
        cfg = json.load(open(cfg_path, encoding='utf-8'))
        for k in ('fileLog', 'fileLogLevel', 'consoleLog', 'consoleLogLevel'):
            print('    %-16s = %s' % (k, cfg.get(k)))
        need = cfg.get('fileLog') is not True
        print('    需要改 fileLog → true 吗: %s' % ('需要' if need else '不需要，已经是 true'))
    print('登录二维码   : %s' % (qr_path or '（还没有，未扫码登录过）'))
    if qr_path:
        print('    mtime = %s' % datetime.datetime.fromtimestamp(os.path.getmtime(qr_path)))
    return cfg_path


def apply():
    cfg_path = show()
    if not cfg_path:
        print('\n找不到 napcat.json，先跑一次 NapCat 让它生成配置，再回来改。')
        return 1
    cfg = json.load(open(cfg_path, encoding='utf-8'))
    if cfg.get('fileLog') is True:
        print('\nfileLog 已经是 true，无需改动。')
        return 0

    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = cfg_path + '.bak-' + stamp
    shutil.copyfile(cfg_path, bak)
    cfg['fileLog'] = True
    if not cfg.get('fileLogLevel') or cfg.get('fileLogLevel') == 'debug':
        cfg['fileLogLevel'] = 'info'          # 文件日志别用 debug，一天能写几十 MB
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print('\n已备份: %s' % bak)
    print('已改  : %s' % cfg_path)
    print('        fileLog = true, fileLogLevel = %s' % cfg['fileLogLevel'])
    print('\n注意：NapCat 退出时可能会把自己的配置写回去（覆盖本次改动）。')
    print('      如果发现日志文件一直是空的，重跑一次本脚本即可。')
    print('还原  : python gui\\tools\\napcat_setup.py --revert')
    return 0


def revert():
    cfg_path = find(CONFIG_GLOB)
    if not cfg_path:
        print('找不到 napcat.json')
        return 1
    baks = sorted(glob.glob(cfg_path + '.bak-*'))
    if not baks:
        print('没有备份可还原')
        return 1
    shutil.copyfile(baks[-1], cfg_path)
    print('已从 %s 还原 %s' % (baks[-1], cfg_path))
    return 0


def main():
    ap = argparse.ArgumentParser(description='NapCat 无窗口化配置')
    ap.add_argument('--apply', action='store_true', help='把 fileLog 改成 true（备份后）')
    ap.add_argument('--revert', action='store_true', help='还原最近的备份')
    args = ap.parse_args()
    if args.revert:
        return revert()
    if args.apply:
        return apply()
    show()
    print('\n（当前只是查看；要改加 --apply）')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
