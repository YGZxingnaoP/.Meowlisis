# -*- coding: utf-8 -*-
# gui/tools/check_i18n.py
r"""i18n 词条覆盖检查（开发用，跑一次看结果即可）。

扫描 gui 下的 JS / HTML 里"会显示给用户的中文原文"：
    - _t('...') / I18n.text('...') / this._t('...')
    - data-i18n="..." / data-i18n-title="..." / data-i18n-alt="..."
    - HTML 属性里的中文（placeholder / title / alt）
再与 gui/locales/en.js 的词条求差集，报告：
    1) 缺英文词条的中文原文（英文界面会回退显示中文）；
    2) en.js 里重复定义的 key（对象重复 key 后者覆盖前者）。

用法：
    python gui/tools/check_i18n.py
"""

import os
import re
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parent.parent          # gui/
LOCALES = GUI / 'locales' / 'en.js'
CJK = re.compile(r'[\u4e00-\u9fff]')

# 取 _t('...') / I18n.text("...") 这类调用里的字面量
CALL_PAT = re.compile(
    r'(?:_t|I18n\.text)\(\s*([\'"])((?:[^\\]|\\.)*?)\1', re.S)
# 取 HTML 属性里的字面量
ATTR_PAT = re.compile(
    r'data-i18n(?:-title|-alt)?\s*=\s*"([^"]*)"'
    r'|(?:placeholder|title|alt)\s*=\s*"([^"]*)"')


def _iter_files():
    for root, dirs, files in os.walk(GUI):
        dirs[:] = [d for d in dirs if d not in ('locales', 'resource', '__pycache__')]
        for fn in files:
            if fn.endswith(('.js', '.html')):
                yield Path(root) / fn


def _unescape(s):
    """把 JS 字面量里的转义还原（\\\\ \\" \\' \\n），保证两边 key 可比"""
    return (s.replace('\\\\', '\x00')
             .replace('\\"', '"')
             .replace("\\'", "'")
             .replace('\\n', '\n')
             .replace('\x00', '\\'))


def collect_used():
    """返回 {中文原文: [出现位置, ...]}"""
    used = {}
    for path in _iter_files():
        try:
            text = path.read_text(encoding='utf-8')
        except Exception:
            continue
        rel = str(path.relative_to(GUI)).replace('\\', '/')
        for m in CALL_PAT.finditer(text):
            s = _unescape(m.group(2))
            if CJK.search(s or ''):
                used.setdefault(s, []).append(rel)
        for m in ATTR_PAT.finditer(text):
            s = (m.group(1) or m.group(2) or '').strip()
            # 属性值里是模板/表达式（${...} / _t(...)）时跳过，由 CALL_PAT 负责
            if not s or '$' in s or '_t(' in s or 'I18n.text(' in s:
                continue
            if CJK.search(s):
                used.setdefault(s, []).append(rel)
    return used


def collect_defined():
    """读 en.js 的 key（按行解析），返回 (keys, duplicates)"""
    keys, dups = set(), []
    if not LOCALES.exists():
        return keys, dups
    rx = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*:')
    for line in LOCALES.read_text(encoding='utf-8').splitlines():
        m = rx.match(line)
        if not m:
            continue
        k = _unescape(m.group(1))
        if k in keys:
            dups.append(k)
        keys.add(k)
    return keys, dups


def main():
    used = collect_used()
    defined, dups = collect_defined()

    missing = sorted(k for k in used if k not in defined)
    print('== i18n 覆盖检查 ==')
    print('界面使用的中文原文: %d 条' % len(used))
    print('en.js 已定义词条  : %d 条' % len(defined))
    print()
    if dups:
        print('!! en.js 重复定义的 key（后者会覆盖前者）:')
        for k in sorted(set(dups)):
            print('   - %s' % k)
        print()
    if missing:
        print('!! 缺少英文词条（英文界面会回退显示中文）: %d 条' % len(missing))
        for k in missing:
            print('   - %s        [%s]' % (k.replace('\n', '\\n'), used[k][0]))
    else:
        print('英文词条已覆盖全部界面中文。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
