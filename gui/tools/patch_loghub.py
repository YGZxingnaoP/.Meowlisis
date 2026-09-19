#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""给项目根的 config_gui.py 打补丁：接入日志中心（gui/tools/loghub.py）

config_gui.py 在 gui 目录之外，所以这里用脚本改（和项目里 _patch_align.py 一个思路）。
只插入一小段，不动任何既有代码：

    # ===== 日志中心：/logs 页面 + 各服务无窗口启动 =====
    try:
        from gui.tools import loghub
        loghub.register(app, BASE_DIR, GUI_DIR)
    except Exception as _e:
        print('[loghub] 注册失败:', _e)

register() 做的事情：
  · 加路由  /logs  /api/logs/services  /api/logs/tail  /api/logs/start  /api/logs/stop  /api/logs/clear
  · **接管**已有的 /api/start_main|sovits|sensevoice|painting_comfy|napcat|netease|rvc|desktopet|phone
    → 不再弹终端窗口，输出改为写入 logs/svc_<服务>.log

用法：
    D:\.Meowlisis\runtime\python.exe D:\.Meowlisis\gui\tools\patch_loghub.py            # 打补丁
    ... --dry                                                                           # 只看会改成什么
    ... --check                                                                         # 只体检，不写
    ... --revert                                                                        # 从最近的备份还原
"""

import argparse
import datetime
import glob
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))       # D:\.Meowlisis
TARGET = os.path.join(ROOT, 'config_gui.py')
ANCHOR = "if __name__ == '__main__':"

BLOCK = '''# ===== 日志中心：/logs 页面 + 各服务无窗口启动（gui/tools/loghub.py） =====
try:
    from gui.tools import loghub
    loghub.register(app, BASE_DIR, GUI_DIR)
except Exception as _loghub_e:
    print('[loghub] 注册失败:', _loghub_e)

'''


def backups():
    return sorted(glob.glob(TARGET + '.bak-*'))


def do_revert():
    baks = backups()
    if not baks:
        print('没有找到备份（%s.bak-*），无法还原' % TARGET)
        return 1
    src = baks[-1]
    shutil.copyfile(src, TARGET)
    print('已从备份还原：%s -> %s' % (src, TARGET))
    return 0


def main():
    ap = argparse.ArgumentParser(description='给 config_gui.py 接入日志中心')
    ap.add_argument('--dry', action='store_true', help='只显示改动，不写文件')
    ap.add_argument('--check', action='store_true', help='只体检，不写文件')
    ap.add_argument('--revert', action='store_true', help='从最近备份还原')
    args = ap.parse_args()

    if not os.path.isfile(TARGET):
        print('找不到 %s' % TARGET)
        return 1
    if args.revert:
        return do_revert()

    text = open(TARGET, encoding='utf-8').read()
    lines = text.splitlines(True)

    # ---- 体检 ----
    need = ['BASE_DIR', 'GUI_DIR', 'gui.tools', 'app.run(host=']
    miss = [n for n in need if n not in text]
    print('目标文件 : %s (%d 行, %d 字节)' % (TARGET, len(lines), len(text)))
    print('体检     : ' + ('OK，关键标识都在' if not miss else '缺以下标识 -> %s' % miss))
    if miss:
        return 1

    already = 'loghub' in text
    if already and not args.dry:
        print('已打过补丁（文件里已出现 loghub），不用重复打。')
        print('如需重打：先 --revert 再跑。')
        return 0

    # ---- 找插入点：最后一个 `if __name__ == '__main__':` ----
    idx = None
    for i, l in enumerate(lines):
        if l.strip() == ANCHOR:
            idx = i
    if idx is None:
        print('找不到插入锚点 %r，为安全起见不动文件。' % ANCHOR)
        return 1

    print('\n插入位置 : 第 %d 行之前（%s）' % (idx + 1, lines[idx].strip()))
    print('插入内容 :')
    for l in BLOCK.rstrip('\n').split('\n'):
        print('    ' + l)

    if args.dry or args.check:
        print('\n(--dry/--check 模式，未写入任何文件)')
        return 0

    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = TARGET + '.bak-' + stamp
    shutil.copyfile(TARGET, bak)

    new = ''.join(lines[:idx]) + BLOCK + ''.join(lines[idx:])
    open(TARGET, 'w', encoding='utf-8', newline='').write(new)
    print('\n已备份   : %s' % bak)
    print('已写入   : %s (+%d 行)' % (TARGET, len(BLOCK.rstrip('\n').split('\n'))))
    print('\n下一步：重启主程序（或已经跑着的 config_gui.py）后，浏览器打开')
    print('        http://127.0.0.1:1801/logs')
    print('撤销方法：python gui\\tools\\patch_loghub.py --revert')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
