#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""两份快照的差量报告（只读）

用法
    python diff.py --a out\A\snap_00-before.json --b out\A\snap_01-after.json
    python diff.py --a ... --b ... --out out\A\diff_00_01.md

输出一份 markdown：文件增删改、注册表增删改、进程与模块、命名管道、网络连接、NapCat 产物。
"""

import argparse
import json
import os


def load(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def key_file(snap):
    """{root_tag: {relpath: (size, hash)}}"""
    out = {}
    for tag, v in snap.get('files', {}).items():
        out[tag] = {r: (val[0], val[4]) for r, val in v.get('tree', {}).items()}
    return out


def flat_reg(snap):
    out = {}
    for k, vals in snap.get('registry', {}).items():
        if k == '__error__':
            continue
        for vn, vv in vals.items():
            out['%s::%s' % (k, vn)] = (vv.get('t'), vv.get('n'), vv.get('h'), vv.get('raw'))
    return out


def proc_map(snap):
    return {p['pid']: p for p in snap.get('processes', [])}


def sec_dirs_removed(a, b):
    return sorted(set(a.get('napcat', {}).get('account_dirs', []))
                  - set(b.get('napcat', {}).get('account_dirs', [])))


def md_table(headers, rows, limit=400):
    out = ['| ' + ' | '.join(headers) + ' |',
           '|' + '|'.join(['---'] * len(headers)) + '|']
    for r in rows[:limit]:
        out.append('| ' + ' | '.join(str(x) for x in r) + ' |')
    if len(rows) > limit:
        out.append('| … 共 %d 行，已截断 |' % len(rows))
    return '\n'.join(out)


def build(a_path, b_path):
    a, b = load(a_path), load(b_path)
    line = []
    line.append('# 差量报告\n')
    line.append('- A: `%s`  (label=%s)' % (os.path.basename(a_path),
                                           a.get('meta', {}).get('label')))
    line.append('- B: `%s`  (label=%s)' % (os.path.basename(b_path),
                                           b.get('meta', {}).get('label')))
    line.append('- 生成: %s\n' % b.get('meta', {}).get('iso'))

    # ---------------- 文件
    fa, fb = key_file(a), key_file(b)
    for tag in sorted(set(fa) | set(fb)):
        ta, tb = fa.get(tag, {}), fb.get(tag, {})
        added = sorted(tb.keys() - ta.keys())
        removed = sorted(ta.keys() - tb.keys())
        changed = sorted(r for r in ta.keys() & tb.keys() if ta[r] != tb[r])
        if not (added or removed or changed):
            continue
        line.append('## 文件：%s\n' % tag)
        line.append('新增 %d / 消失 %d / 变化 %d\n' % (len(added), len(removed), len(changed)))
        rows = []
        for r in added:
            rows.append(('+', r, tb[r][0], ''))
        for r in removed:
            rows.append(('-', r, ta[r][0], ''))
        for r in changed:
            da, db = ta[r][0], tb[r][0]
            rows.append(('~', r, '%s→%s' % (da, db),
                         'hash %s' % ('changed' if ta[r][1] != tb[r][1] else 'same')))
        if rows:
            line.append(md_table(['', 'path', 'size', 'note'], rows))
            line.append('')

    # ---------------- 注册表
    ra, rb = flat_reg(a), flat_reg(b)
    added = sorted(rb.keys() - ra.keys())
    removed = sorted(ra.keys() - rb.keys())
    changed = sorted(k for k in ra.keys() & rb.keys() if ra[k] != rb[k])
    line.append('## 注册表\n')
    line.append('新增 %d / 消失 %d / 变化 %d\n' % (len(added), len(removed), len(changed)))
    if added or removed or changed:
        rows = [('+', k, rb[k][3] if len(rb[k]) > 3 else '') for k in added]
        rows += [('-', k, ra[k][3] if len(ra[k]) > 3 else '') for k in removed]
        rows += [('~', k, '') for k in changed]
        line.append(md_table(['', 'key::value', 'raw(短值)'], rows))
    line.append('')

    # ---------------- 进程
    pa, pb = proc_map(a), proc_map(b)
    line.append('## 进程\n')
    rows = []
    for pid, p in pb.items():
        if pid not in pa:
            rows.append(('+', pid, p.get('name'), p.get('electron_type'),
                         p.get('cmdline', '')[:120]))
    for pid, p in pa.items():
        if pid not in pb:
            rows.append(('-', pid, p.get('name'), p.get('electron_type'),
                         p.get('cmdline', '')[:120]))
    for pid in pa.keys() & pb.keys():
        ma, mb = set(pa[pid].get('modules') or []), set(pb[pid].get('modules') or [])
        if ma != mb:
            rows.append(('mod', pid, pb[pid].get('name'), '',
                         '新加载 %s' % sorted(mb - ma)))
    if rows:
        line.append(md_table(['', 'pid', 'name', 'etype', 'note'], rows))
    else:
        line.append('（无变化）')
    line.append('')

    # ---------------- 管道 / 网络
    la, lb = set(a.get('pipes', [])), set(b.get('pipes', []))
    line.append('## 命名管道\n')
    line.append('- 新增: %s' % (sorted(lb - la) or '无'))
    line.append('- 消失: %s\n' % (sorted(la - lb) or '无'))

    def conns(s):
        return {('%s→%s' % (c.get('laddr'), c.get('raddr')), c.get('status'))
                for c in s.get('net', {}).get('conns', [])}
    ca, cb = conns(a), conns(b)
    line.append('## 网络连接\n')
    line.append('- 新增: %s' % (sorted(cb - ca)[:40] or '无'))
    line.append('- 消失: %s\n' % (sorted(ca - cb)[:40] or '无'))

    # ---------------- NapCat 产物
    line.append('## NapCat 产物\n')
    for key in ('qrcode', 'config', 'logs', 'listening'):
        va = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in a.get('napcat', {}).get(key, [])}
        vb = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in b.get('napcat', {}).get(key, [])}
        if va != vb:
            line.append('- **%s**: +%d / -%d' % (key, len(vb - va), len(va - vb)))
            for x in sorted(vb - va):
                line.append('  - + `%s`' % x[:200])
            for x in sorted(va - vb):
                line.append('  - - `%s`' % x[:200])
    line.append('')
    return '\n'.join(line)


def main():
    ap = argparse.ArgumentParser(description='快照差量报告')
    ap.add_argument('--a', required=True)
    ap.add_argument('--b', required=True)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    text = build(args.a, args.b)
    out = args.out or os.path.join(os.path.dirname(args.b),
                                  'diff_%s.md' % os.path.basename(args.b).replace('snap_', '').replace('.json', ''))
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text[:4000])
    print('\n[写出] %s' % out)


if __name__ == '__main__':
    main()
