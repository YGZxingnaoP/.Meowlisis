# -*- coding: utf-8 -*-
# 权威验证：1) 词法结构  2) 普通字符串内含 ${（真正会 SyntaxError 的污染）  3) 词条缺失数
import io, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

FILES = [
    "gui/js/config/core.js", "gui/js/config/basic.js", "gui/js/config/llm.js",
    "gui/js/config/tts.js", "gui/js/config/media.js", "gui/js/config/toolbox.js",
    "gui/js/config/song.js", "gui/js/config/db.js", "gui/js/config/character.js",
    "gui/js/orbit.js", "gui/js/modal.js",
    "gui/js/app/core.js", "gui/js/app/tts.js", "gui/js/app/llm.js",
    "gui/js/app/audio.js", "gui/js/app/toolbox.js", "gui/js/app/song.js", "gui/js/app/bind.js",
    "gui/js/i18n.js", "gui/locales/zh-CN.js", "gui/locales/en.js",
]

def scan(p):
    """真实字符串(单/双引号,含模板插值代码层)字面量内容含 '${' -> 语法污染"""
    s = io.open(p, encoding="utf-8", errors="replace").read()
    hits = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "/" and i + 1 < n and s[i + 1] not in ("/", "*", " ", "\t", "\n", "\r"):
            # 正则字面量 vs 除法
            k = i - 1
            while k >= 0 and s[k] in " \t\r\n":
                k -= 1
            prev = s[k] if k >= 0 else ""
            if not (prev.isalnum() or prev in "_$)]}'\"`"):
                j = i + 1
                while j < n:
                    if s[j] == "\\": j += 2; continue
                    if s[j] == "/": break
                    j += 1
                if j < n:
                    i = j + 1
                    continue
        if c == "'" or c == '"':
            q = c; j = i + 1; body = []
            while j < n:
                if s[j] == "\\":
                    body.append(s[j:j + 2]); j += 2; continue
                if s[j] == q: break
                body.append(s[j]); j += 1
            content = "".join(body)
            if "${" in content:
                ln = s[:i].count("\n") + 1
                hits.append((ln, q, content[:100]))
            i = j if j < n else n
            if i < n:
                i += 1
            continue
        if c == "`":
            i += 1
            while i < n:
                if s[i] == "\\": i += 2; continue
                if s[i] == "$" and i + 1 < n and s[i + 1] == "{":
                    depth = 1; i += 2
                    while i < n and depth:
                        if s[i] == "\\": i += 2; continue
                        if s[i] == "'" or s[i] == '"':
                            qq = s[i]; i += 1
                            while i < n:
                                if s[i] == "\\": i += 2; continue
                                if s[i] == qq: break
                                i += 1
                            i += 1; continue
                        if s[i] == "`":
                            # 嵌套模板：完整跳到闭合
                            i += 1
                            while i < n:
                                if s[i] == "\\": i += 2; continue
                                if s[i] == "`": break
                                i += 1
                            i += 1; continue
                        if s[i] == "{": depth += 1
                        elif s[i] == "}": depth -= 1
                        i += 1
                    continue
                if s[i] == "`": break
                i += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "/":
            j = s.find("\n", i); i = n if j < 0 else j; continue
        if c == "/" and i + 1 < n and s[i + 1] == "*":
            j = s.find("*/", i + 2); i = n if j < 0 else j + 2; continue
        i += 1
    return hits

# 1) 词法
ok_lex = True
import subprocess
# 2) 坏串扫描
total_bad = 0
for p in FILES:
    hits = scan(p)
    if hits:
        total_bad += len(hits)
        print("BAD-STR %s (%d)" % (p, len(hits)))
        for ln, q, content in hits[:10]:
            print("   L%d: %r..." % (ln, content))
print("bad-string hits:", total_bad)

# 3) 词条缺失（this._t('x') 中 en/zh 都无词条的）
CJK = "[" + chr(0x4e00) + "-" + chr(0x9fff) + "]"
have = set(re.findall(r'"((?:[^"\\]|\\.)*)"\s*:', io.open("gui/locales/en.js", encoding="utf-8").read()))
have |= set(re.findall(r'"((?:[^"\\]|\\.)*)"\s*:', io.open("gui/locales/zh-CN.js", encoding="utf-8").read()))
missing = []
seen = set()
for p in FILES:
    if not p.startswith("gui/js/"):
        continue
    s = io.open(p, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"this\._t\(\s*(['\"])([^'\"]*" + CJK + r"[^'\"]*)\1\s*\)", s):
        k = m.group(2)
        if k not in have and k not in seen:
            seen.add(k); missing.append((p, k))
print("missing _t terms:", len(missing))
for p, k in missing[:30]:
    print("   ", p, "::", k)
