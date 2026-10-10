# -*- coding: utf-8 -*-
# scripts/make_config_example.py
# 从 config.yml 生成 config.example.yml：只清空密钥类字段的值，注释、缩进、结构全部原样保留
#
# 用法（在项目根目录执行）：
#   runtime\python.exe scripts\make_config_example.py
#   runtime\python.exe scripts\make_config_example.py --in config.yml --out config.example.yml
#
# 生成后自己打开看一遍，确认没有漏掉的密钥（搜 sk- 、token 、password 这几个词）

import os
import re
import sys
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

# 值要被清空的字段名（不区分大小写，字段名里带这些词的都会清空）
SECRET_KEYS = [
    "api_key", "api-key", "apikey", "api_secret", "secret", "secret_key", "secret-key",
    "app_secret", "app_key", "appkey", "client_secret", "client_id", "app_id", "appid",
    "access_token", "refresh_token", "token", "password", "passwd", "pwd",
    "cookie", "cookies", "authorization", "private_key", "session_key",
    "sign_key", "encrypt_key", "aes_key", "smtp_password", "bot_token",
]
KEY_PAT = re.compile(
    r"^(?P<head>\s*-?\s*(?:" + "|".join(SECRET_KEYS) + r")\s*:\s*)"
    r"(?P<val>.*?)"
    r"(?P<tail>\s*(?:#.*)?)$",
    re.IGNORECASE)
PLACEHOLDER = '""'
EMPTY_VALUES = ("", '""', "''", "null", "~", "#")


def blank_line(line):
    """命中密钥字段就把值清成空串，返回新行和是否命中"""
    m = KEY_PAT.match(line)
    if not m:
        return line, False
    val = m.group("val").strip()
    if val in EMPTY_VALUES or val.startswith("#"):
        return line, False
    return m.group("head") + PLACEHOLDER + m.group("tail"), True


def main():
    args = sys.argv[1:]
    src = args[args.index("--in") + 1] if "--in" in args else "config.yml"
    dst = args[args.index("--out") + 1] if "--out" in args else "config.example.yml"
    if not os.path.exists(src):
        print(f"[错误] 找不到 {src}")
        return 1
    with open(src, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, hits = [], []
    for i, line in enumerate(lines, 1):
        new_line, hit = blank_line(line)
        if hit:
            hits.append((i, line.strip().split(":")[0].lstrip("- ").strip()))
        out.append(new_line)
    header = [
        "# ============================================================",
        "# 这是配置模板，由 scripts/make_config_example.py 生成",
        "# 密钥类字段已经清空，填上自己的再改名为 config.yml；",
        "# 或者直接启动程序，程序发现没有 config.yml 时会用它自动生成一份。",
        f"# 生成时间：{datetime.datetime.now():%Y-%m-%d %H:%M}",
        "# ============================================================",
    ]
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(header + out) + "\n")
    print(f"[完成] {dst}（正文 {len(lines)} 行）")
    print(f"[清空] {len(hits)} 处密钥字段：")
    for line_no, key in hits:
        print(f"       第 {line_no} 行   {key}")
    print("[提醒] 打开看一遍，确认没漏（搜 sk- 、token 、password）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
