# -*- coding: utf-8 -*-
# 临时：JS 词法级校验（注释/字符串/模板字符串含${}插值/括号栈）
import io, sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PAIRS = {")": "(", "]": "[", "}": "{"}

def scan_code(s, i, stack, path, stop_char=None):
    """扫描代码；stop_char 用于模板插值 ${ ... }；返回 (index, err)"""
    n = len(s)
    while i < n:
        c = s[i]
        if stop_char and c == stop_char:
            # 栈顶恰有匹配的开括号（对象字面量等）→ 先闭合内层，否则视为插值结束
            if stack and stack[-1] == PAIRS.get(c):
                stack.pop()
                i += 1
                continue
            if stack:
                return i, "stack-not-empty@%d" % i
            return i + 1, None
        if c in "'\"":
            q = c
            i += 1
            while i < n:
                if s[i] == "\\":
                    i += 2
                    continue
                if s[i] == q:
                    break
                i += 1
            if i >= n:
                return i, "unterminated-string(%s)@%d in %s" % (q, i, path)
            i += 1
            continue
        if c == "$" and i + 1 < n and s[i + 1] == "{":
            # 进入模板插值表达式（允许嵌套字符串/模板）
            i += 2
            sub_stack = []
            i, err = scan_code(s, i, sub_stack, path, stop_char="}")
            if err:
                return i, "template-interp: %s" % err
            continue
        if c == "`":
            i += 1
            while i < n:
                if s[i] == "\\":
                    i += 2
                    continue
                if s[i] == "$" and i + 1 < n and s[i + 1] == "{":
                    # 进入插值表达式（允许嵌套字符串/模板）
                    i += 2
                    sub_stack = []
                    i, err = scan_code(s, i, sub_stack, path, stop_char="}")
                    if err:
                        return i, "template-interp: %s" % err
                    continue
                if s[i] == "`":
                    break
                i += 1
            if i >= n:
                return i, "unterminated-template@%d in %s" % (i, path)
            i += 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "/":
            j = s.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "*":
            j = s.find("*/", i + 2)
            if j < 0:
                return i, "unterminated-block-comment in %s" % path
            i = j + 2
            continue
        if c == "/" and i + 1 < n and s[i + 1] not in ("/", "*", " ", "\t", "\n", "\r"):
            # 区分正则字面量与除法：前一个有效 token 为标识符/数字/闭括号/下划线/$ 时视为除法
            k = i - 1
            while k >= 0 and s[k] in " \t\r\n":
                k -= 1
            prev = s[k] if k >= 0 else ""
            is_div = prev.isalnum() or prev in "_$)]}'\"`"
            if not is_div:
                j = i + 1
                while j < n:
                    if s[j] == "\\":
                        j += 2
                        continue
                    if s[j] == "/":
                        break
                    j += 1
                if j < n:
                    i = j + 1
                    continue
        if c in "([{":
            stack.append(c)
            i += 1
            continue
        if c in ")]}":
            if not stack or stack[-1] != PAIRS[c]:
                return i, "unmatched-%s@%d in %s" % (c, i, path)
            stack.pop()
            i += 1
            continue
        i += 1
    if stop_char:
        return i, "eof-in-interp(missing %s)" % stop_char
    if stack:
        return i, "unclosed: %s @%d in %s" % (stack, i, path)
    return i, None

FILES = [
    "gui/js/config/core.js", "gui/js/orbit.js", "gui/js/modal.js",
    "gui/js/app/core.js", "gui/js/app/tts.js", "gui/js/i18n.js",
    "gui/locales/zh-CN.js", "gui/locales/en.js",
    "gui/js/config/tts.js", "gui/js/config/llm.js", "gui/js/config/toolbox.js",
    "gui/js/config/song.js", "gui/js/config/media.js", "gui/js/config/db.js",
    "gui/js/config/basic.js", "gui/js/config/character.js",
    "gui/js/app/llm.js", "gui/js/app/audio.js", "gui/js/app/toolbox.js",
    "gui/js/app/song.js", "gui/js/app/bind.js",
]

fails = 0
for p in FILES:
    s = io.open(p, encoding="utf-8", errors="strict").read()
    _, err = scan_code(s, 0, [], p)
    if err:
        fails += 1
        print("FAIL", p, "->", err)
    else:
        print("OK  ", p)
print("FAILS:", fails)
