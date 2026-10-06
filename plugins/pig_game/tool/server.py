# -*- coding: utf-8 -*-
"""猪种配置工具 · 后端（纯 Python 标准库，README 见同目录 说明.txt）

· 不 import 主项目、也不 import 插件任何代码，只读写 assets/ 下的文件
· 起一个只监听 127.0.0.1 的小服务，浏览器打开就是配置界面

双击「启动工具.bat」，或：
    python server.py
    python server.py --port 8899 --no-browser
    python server.py --assets D:\\别的路径\\assets
"""

import argparse
import base64
import io
import json
import os
import re
import shutil
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)                       # pig_game/
UI_DIR = os.path.join(HERE, "ui")
ASSETS = os.path.join(PLUGIN, "assets")              # 可被 --assets 覆盖
COMMANDS_PY = os.path.join(PLUGIN, "text", "commands.py")

BANNER_PX = (1400, 600)
ICON_PX = (512, 512)
SPECIES_FILE = "species.json"

# ---------------------------------------------------------------- 表单字段
# 前端按这份 spec 自动渲染表单，改这里就够了
FIELDS = [
    {"k": "id", "t": "text", "label": "id", "hint": "英文小写下划线，别和别的猪种撞",
     "req": True, "lock_edit": True, "width": "half"},
    {"k": "name", "t": "text", "label": "名字", "hint": "显示名，如 龙猪",
     "req": True, "width": "half"},
    {"k": "type", "t": "select", "label": "类型", "width": "half",
     "opts": [["base", "普通猪"], ["magic", "魔法猪"]]},
    {"k": "aliases", "t": "list", "label": "别名", "hint": "逗号分隔；越长越优先匹配",
     "width": "full"},

    {"k": "coin_per_day", "t": "num", "label": "每天产币", "step": 1, "width": "third"},
    {"k": "attack", "t": "num", "label": "战斗点数", "step": 1, "width": "third"},
    {"k": "steal_rate", "t": "num", "label": "被偷率 0~1", "step": 0.05, "width": "third"},

    {"k": "stealable", "t": "check", "label": "可被偷", "width": "third"},
    {"k": "tradable", "t": "check", "label": "可交易", "width": "third"},
    {"k": "shop_price", "t": "num", "label": "天降猪猪售价", "step": 1, "width": "third",
     "hint": "金币/只；0 = 商店不上架"},

    {"k": "craft", "t": "recipe", "label": "合成配方", "hint": "材料 id : 数量",
     "width": "full", "magic_only": True},
    {"k": "obtain_dates", "t": "list", "label": "限定日期 / 时间段",
     "hint": "空 = 不限时；2026-12-25 / 12-25 / 2026-10-06~2026-12-01", "width": "full"},

    # -------- 高级：默认折叠，一般不用动 --------
    {"k": "team_bonus", "t": "num", "label": "整队加成", "hint": "魔法猪用",
     "step": 0.05, "width": "third", "sec": "adv"},
    {"k": "base_price", "t": "num", "label": "估价", "step": 1, "width": "third",
     "sec": "adv"},
    {"k": "trade_count_max", "t": "num", "label": "单笔交易上限", "step": 1,
     "width": "third", "sec": "adv"},
    {"k": "death_prob", "t": "num", "label": "打卡死亡概率", "step": 0.05,
     "width": "third", "sec": "adv"},
    {"k": "breed.base_prob", "t": "num", "label": "繁殖基础概率", "step": 0.05,
     "width": "third", "sec": "adv"},
    {"k": "breed.cap", "t": "num", "label": "繁殖上限", "step": 1, "width": "third",
     "sec": "adv"},
    {"k": "breed.aff_influence", "t": "num", "label": "好感度影响系数", "step": 0.05,
     "width": "third", "sec": "adv"},
]

DEFAULTS = {
    "id": "", "name": "", "type": "base", "aliases": [],
    "steal_rate": 0.5, "coin_per_day": 1, "attack": 5, "team_bonus": 0.0,
    "stealable": True, "tradable": True, "base_price": 10, "trade_count_max": 5,
    "shop_price": 0,
    "craft": None, "obtain_dates": [], "death_prob": 0.0,
    "breed": {"enabled": True, "base_prob": 0.5, "amount": 1, "cap": 60,
              "aff_influence": 0.5},
}


# ---------------------------------------------------------------- 工具函数
def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def list_species():
    out = []
    if not os.path.isdir(ASSETS):
        return out
    for name in sorted(os.listdir(ASSETS)):
        if name.startswith("_") or name.startswith("."):
            continue
        p = os.path.join(ASSETS, name, SPECIES_FILE)
        if not os.path.isfile(p):
            continue
        try:
            d = read_json(p)
        except Exception:
            continue
        d.setdefault("id", name)
        d["_folder"] = name
        d["_has_image"] = os.path.isfile(os.path.join(ASSETS, name, "image.png"))
        d["_has_icon"] = os.path.isfile(os.path.join(ASSETS, name, "icon.png"))
        out.append(d)
    return out


def list_scenes():
    d = os.path.join(ASSETS, "scene")
    if not os.path.isdir(d):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(d)
                  if f.lower().endswith((".png", ".jpg", ".jpeg")))


def crop_save(raw, dst, size):
    """居中裁剪到目标尺寸再存 PNG；没装 Pillow 就原样存。"""
    try:
        from PIL import Image
    except Exception:
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(raw)
        return {"ok": True, "info": "未裁剪（没装 Pillow，原样保存）"}
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    ow, oh = im.size
    tw, th = size
    tr, sr = tw / float(th), ow / float(oh)
    if sr > tr:
        nw = int(round(oh * tr))
        x = (ow - nw) // 2
        im = im.crop((x, 0, x + nw, oh))
    elif sr < tr:
        nh = int(round(ow / tr))
        y = (oh - nh) // 2
        im = im.crop((0, y, ow, y + nh))
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    im.save(dst)
    return {"ok": True, "info": "%dx%d → %dx%d（居中裁剪，不拉伸）" % (ow, oh, tw, th)}


# ---------------------------------------------------------------- 词表
WORDS_RE = re.compile(r"(SPECIES_WORDS\s*=\s*\()(?P<body>.*?)(\n\))", re.S)


def read_words():
    if not os.path.isfile(COMMANDS_PY):
        return []
    m = WORDS_RE.search(open(COMMANDS_PY, encoding="utf-8").read())
    return re.findall(r'"([^"]+)"', m.group("body")) if m else []


def write_words(words):
    if not os.path.isfile(COMMANDS_PY):
        return False
    src = open(COMMANDS_PY, encoding="utf-8").read()
    m = WORDS_RE.search(src)
    if not m:
        return False
    words = sorted({w for w in words if w}, key=len, reverse=True)
    body = "".join('\n    "%s",' % w for w in words)
    src = src[:m.start()] + "SPECIES_WORDS = (" + body + "\n)" + src[m.end():]
    open(COMMANDS_PY, "w", encoding="utf-8").write(src)
    return True


def sync_words():
    """把所有猪种的 name + aliases 全量同步进词表。"""
    words = []
    for sp in list_species():
        words.append(sp.get("name"))
        words.extend(sp.get("aliases") or [])
    before = read_words()
    ok = write_words(words)
    after = read_words()
    return {"ok": ok, "before": before, "after": after,
            "added": [w for w in after if w not in before],
            "removed": [w for w in before if w not in after]}


# ---------------------------------------------------------------- 体检
def check():
    book = {sp["id"]: sp for sp in list_species()}
    words = read_words()
    items, bad = [], 0
    for sid, d in book.items():
        p = []
        if not d.get("name"):
            p.append("缺 name")
        if d.get("type") not in ("base", "magic"):
            p.append("type 必须是 base / magic")
        if d.get("type") == "magic":
            if not d.get("craft"):
                p.append("魔法猪缺 craft 配方")
            if d.get("stealable") or d.get("tradable"):
                p.append("魔法猪建议 stealable / tradable 关掉")
        if d.get("craft") and d.get("type") != "magic":
            p.append("普通猪不该有 craft")
        for mid in (d.get("craft") or {}):
            if mid not in book:
                p.append("配方里的材料「%s」不存在" % mid)
        for k, lo, hi in (("steal_rate", 0, 1), ("death_prob", 0, 1),
                          ("team_bonus", 0, 9), ("coin_per_day", 0, 9999)):
            v = d.get(k, 0)
            if not isinstance(v, (int, float)) or not (lo <= v <= hi):
                p.append("%s = %r 超出 %s~%s" % (k, v, lo, hi))
        if not d.get("_has_image"):
            p.append("缺 image.png（会回退卡面 card.png）")
        for w in [d.get("name")] + list(d.get("aliases") or []):
            if w and w not in words:
                p.append("词表缺「%s」" % w)
                break
        if p:
            bad += 1
        items.append({"id": sid, "problems": p})
    return {"count": len(book), "bad": bad, "items": items,
            "scenes": list_scenes(), "words": words}


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "PigTool/1.0"

    def log_message(self, fmt, *a):        # 静音
        pass

    # ---------- 工具 ----------
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _file(self, path):
        if not os.path.isfile(path):
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(path)[1].lower()
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8",
                 ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".svg": "image/svg+xml", ".ico": "image/x-icon"}.get(
            ext, "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---------- 路由 ----------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._file(os.path.join(UI_DIR, "index.html"))
        if path == "/api/state":
            return self._json({
                "plugin": PLUGIN, "assets": ASSETS, "exists": os.path.isdir(ASSETS),
                "fields": FIELDS, "defaults": DEFAULTS,
                "species": list_species(), "scenes": list_scenes(),
            })
        if path == "/api/check":
            return self._json(check())
        if path == "/api/words":
            return self._json({"words": read_words(), "path": COMMANDS_PY,
                               "exists": os.path.isfile(COMMANDS_PY)})
        if path.startswith("/api/thumb/"):
            name = path[len("/api/thumb/"):]
            sid, _, kind = name.rpartition("__")
            if not sid:
                sid, kind = name, "image"
            fn = "icon.png" if kind == "icon" else "image.png"
            return self._file(os.path.join(ASSETS, sid, fn))
        if path.startswith("/api/scene/"):
            name = path[len("/api/scene/"):]
            for ext in (".png", ".jpg", ".jpeg"):
                p = os.path.join(ASSETS, "scene", name + ext)
                if os.path.isfile(p):
                    return self._file(p)
            return self._send(404, "no scene", "text/plain; charset=utf-8")
        return self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._body()

        if path == "/api/save":
            sid = str(body.get("id") or "").strip()
            data = body.get("data") or {}
            if not re.match(r"^[a-z][a-z0-9_]*$", sid):
                return self._json({"ok": False, "msg": "id 只能英文小写字母/数字/下划线"})
            data["id"] = sid
            folder = os.path.join(ASSETS, sid)
            try:
                write_json(os.path.join(folder, SPECIES_FILE), data)
            except Exception as e:
                return self._json({"ok": False, "msg": "写入失败：%s" % e})
            return self._json({"ok": True, "msg": "已保存 assets/%s/species.json" % sid})

        if path == "/api/delete":
            sid = str(body.get("id") or "")
            folder = os.path.join(ASSETS, sid)
            if not os.path.isdir(folder):
                return self._json({"ok": False, "msg": "没有这个猪种"})
            shutil.rmtree(folder, ignore_errors=True)
            return self._json({"ok": True, "msg": "已删除 %s（词表改动请点「同步词表」）" % sid})

        if path == "/api/image":
            sid = str(body.get("id") or "")
            kind = "icon" if body.get("kind") == "icon" else "image"
            raw64 = str(body.get("data") or "")
            if not sid or not raw64:
                return self._json({"ok": False, "msg": "缺参数"})
            if "," in raw64[:100]:
                raw64 = raw64.split(",", 1)[1]
            try:
                raw = base64.b64decode(raw64)
            except Exception:
                return self._json({"ok": False, "msg": "图片数据坏了"})
            dst = os.path.join(ASSETS, sid, kind + ".png")
            try:
                r = crop_save(raw, dst, ICON_PX if kind == "icon" else BANNER_PX)
            except Exception as e:
                return self._json({"ok": False, "msg": "处理失败：%s" % e})
            r["msg"] = "%s/%s.png  %s" % (sid, kind, r.get("info", ""))
            return self._json(r)

        if path == "/api/scene":
            name = re.sub(r"[^A-Za-z0-9_\-]", "", str(body.get("name") or ""))
            raw64 = str(body.get("data") or "")
            if not name or not raw64:
                return self._json({"ok": False, "msg": "场景名只能是英文/数字/下划线，且要选图"})
            if "," in raw64[:100]:
                raw64 = raw64.split(",", 1)[1]
            dst = os.path.join(ASSETS, "scene", name + ".png")
            try:
                r = crop_save(base64.b64decode(raw64), dst, BANNER_PX)
            except Exception as e:
                return self._json({"ok": False, "msg": "处理失败：%s" % e})
            r["msg"] = "scene/%s.png  %s" % (name, r.get("info", ""))
            r["scenes"] = list_scenes()
            return self._json(r)

        if path == "/api/sync":
            try:
                r = sync_words()
            except Exception as e:
                return self._json({"ok": False, "msg": "同步失败：%s" % e})
            msg = "词表已同步"
            if r["added"]:
                msg += "，新增：" + "、".join(r["added"])
            if r["removed"]:
                msg += "，移除：" + "、".join(r["removed"])
            r["msg"] = msg
            return self._json(r)

        return self._send(404, "not found", "text/plain; charset=utf-8")


def main():
    global ASSETS
    ap = argparse.ArgumentParser(description="猪种配置工具")
    ap.add_argument("--port", type=int, default=8756)
    ap.add_argument("--assets", default="", help="assets 目录（默认取插件目录下的 assets）")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--version", action="store_true", help="只打印版本后退出")
    args = ap.parse_args()

    if args.version:
        print("pig-game 猪种配置工具 1.0")
        return 0

    if args.assets:
        ASSETS = os.path.abspath(args.assets)

    port = args.port
    for _ in range(20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        print("[x] 找不到空闲端口")
        return 1

    url = "http://127.0.0.1:%d/" % port
    print("=" * 58)
    print(" 猪种配置工具")
    print("=" * 58)
    print(" 插件目录 : %s" % PLUGIN)
    print(" 资源目录 : %s%s" % (ASSETS, "" if os.path.isdir(ASSETS) else "   ← 不存在！"))
    print(" 词  表   : %s%s" % (COMMANDS_PY, "" if os.path.isfile(COMMANDS_PY) else "   ← 不存在"))
    print(" 界面地址 : %s" % url)
    print("=" * 58)
    print(" 关掉这个窗口 = 关闭工具。\n")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
