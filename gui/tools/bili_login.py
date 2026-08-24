# -*- coding: utf-8 -*-
# gui/tools/bili_login.py
# B站扫码登录工具（供 config_gui 的 Web 接口调用）
# 提供 start_login / check_login：返回二维码 base64 与登录状态，成功后写回 config.yml

import os
import io
import base64
import threading

import requests
import yaml
import qrcode

# 项目根目录（gui/tools/bili_login.py → 上三级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yml")

GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
# 扫码登录成功后用 ticket 换取真实 cookie 的接口
EXCHANGE_URL = "https://passport.bilibili.com/x/passport-login/web/exchange_cookie"
# 官方接口固定的 source 参数，缺失会导致登录成功后返回的 url 为空/凭证缺失
SOURCE = "main-fe-header"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://passport.bilibili.com/login",
}

# 模拟真实浏览器访问跳转链，避免风控拦截
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://passport.bilibili.com/login",
    "Upgrade-Insecure-Requests": "1",
}

# 模块级状态：当前有效的 qrcode_key（同一时间只允许一个扫码会话）
_state = {"qrcode_key": None, "target": "danmaku"}
_lock = threading.Lock()


def start_login(target="danmaku"):
    """生成 B站登录二维码，返回 dict（含二维码 base64 图片）

    target: danmaku=写回 danmaku.blivedm；web_browse=写回 llm_active.web_browse
    """
    target = target if target in ("danmaku", "web_browse") else "danmaku"
    try:
        resp = requests.get(GENERATE_URL, params={"source": SOURCE}, headers=HEADERS, timeout=10)
        data = resp.json()
    except Exception as e:
        return {"ok": False, "message": f"生成二维码请求失败：{e}"}

    if data.get("code") != 0:
        return {"ok": False, "message": data.get("message") or f"code={data.get('code')}"}

    info = data.get("data") or {}
    qr_url = info.get("url", "")
    qr_key = info.get("qrcode_key", "")
    if not qr_url or not qr_key:
        return {"ok": False, "message": "二维码数据不完整"}

    # 二维码转 base64 PNG，供前端 <img> 直接展示
    try:
        img = qrcode.make(qr_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        return {"ok": False, "message": f"生成二维码图片失败：{e}"}

    with _lock:
        _state["qrcode_key"] = qr_key
        _state["target"] = target

    return {"ok": True, "qrcode_key": qr_key, "qrcode": qr_b64, "target": target}


def check_login(qrcode_key=None, target=None):
    """轮询一次登录状态，返回 dict。

    target: 优先用调用方传入的 target；缺省回退到 start_login 时记录的 target。

    status 取值：
      waiting  - 未扫码/状态未知
      scanned  - 已扫码，等待手机确认
      expired  - 二维码失效
      success  - 登录成功（已写回 config.yml，返回 sessdata/bili_jct 供前端回填）
      error    - 出错
    """
    key = qrcode_key or _state.get("qrcode_key")
    if not key:
        return {"ok": False, "status": "error", "message": "没有有效的扫码会话，请重新扫码登录"}

    write_target = target if target in ("danmaku", "web_browse") else _state.get("target", "danmaku")

    try:
        resp = requests.get(POLL_URL, params={"qrcode_key": key, "source": SOURCE},
                            headers=HEADERS, timeout=10)
        data = resp.json().get("data") or {}
    except Exception as e:
        return {"ok": False, "status": "error", "message": f"轮询异常：{e}"}

    code = data.get("code")
    if code == 86101:
        return {"ok": True, "status": "waiting", "message": "等待扫码"}
    if code == 86090:
        return {"ok": True, "status": "scanned", "message": "已扫码，请在手机上确认登录"}
    if code == 86038:
        with _lock:
            _state["qrcode_key"] = None
        return {"ok": False, "status": "expired", "message": "二维码已失效，请重新扫码登录"}

    if code == 0:
        cred_url = data.get("url", "") or ""
        sessdata, bili_jct, dedeuserid = parse_credential(cred_url)

        # 新流程：url 为 crossDomain 跳转页，直接模拟浏览器爬取 Set-Cookie
        if not sessdata or not bili_jct:
            try:
                sessdata, bili_jct, dedeuserid = fetch_cookies_via_crossdomain(cred_url)
            except Exception as e:
                return {"ok": False, "status": "error",
                        "message": f"爬取登录 cookie 失败：{e}"}

        if not sessdata or not bili_jct:
            # 诊断：把 url 关键片段脱敏返回，便于定位
            hint = cred_url[:160] if cred_url else "(url 为空)"
            return {"ok": False, "status": "error",
                    "message": f"解析登录凭证失败（sessdata={'有' if sessdata else '空'}, "
                               f"bili_jct={'有' if bili_jct else '空'}）url片段: {hint}"}

        # 登录成功后：web_browse 场景顺带解析 mid（DedeUserID 即 B站 UID/mid），写回 config
        mid = None
        if write_target == "web_browse":
            if dedeuserid and str(dedeuserid).isdigit():
                mid = int(dedeuserid)
            else:
                mid = fetch_mid(sessdata)

        try:
            update_config(sessdata, bili_jct, write_target, mid)
        except Exception as e:
            return {"ok": False, "status": "error", "message": f"写入 config.yml 失败：{e}"}

        with _lock:
            _state["qrcode_key"] = None

        return {
            "ok": True,
            "status": "success",
            "message": f"登录成功（UID {mid or dedeuserid or ''}）",
            "dedeuserid": dedeuserid,
            "mid": mid,
            "sessdata": sessdata,
            "bili_jct": bili_jct,
            "target": write_target,
        }

    return {"ok": True, "status": "waiting", "message": f"状态码 {code}"}


def fetch_mid(sessdata):
    """用 SESSDATA 调 B站 nav 接口获取当前账号 mid（UID），失败返回 None"""
    if not sessdata:
        return None
    try:
        r = requests.get(
            "https://api.bilibili.com/x/web-interface/nav",
            cookies={"SESSDATA": sessdata},
            headers=HEADERS,
            timeout=10,
        )
        j = r.json()
        if j.get("code") == 0 and (j.get("data") or {}).get("isLogin"):
            return int((j.get("data") or {}).get("mid") or 0) or None
    except Exception:
        pass
    return None


def parse_credential(cred_url):
    """从登录成功后的跳转 URL 解析 SESSDATA / bili_jct / DedeUserID（旧格式）

    注意：SESSDATA 值里的 %2C 等编码必须保留字面，不能二次解码，
    所以按 & 拆分取原始子串（与官方 bilibili-api 处理一致）。
    """
    if not cred_url or "?" not in cred_url:
        return "", "", ""
    query = cred_url.split("?", 1)[1]
    sessdata = ""
    bili_jct = ""
    dedeuserid = ""
    for kv in query.split("&"):
        k, _, v = kv.partition("=")
        kl = k.lower()
        if kl == "sessdata":
            sessdata = v
        elif kl == "bili_jct":
            bili_jct = v
        elif kl == "dedeuserid":
            dedeuserid = v
    return sessdata, bili_jct, dedeuserid


def parse_ticket(cred_url):
    """从 crossDomain 跳转 URL 解析 ticket 与 gourl（新扫码登录流程）

    例：
      https://passport.biligame.com/x/passport-login/web/crossDomain?ticket=xxx&gourl=https%3A%2F%2F...
    返回 (ticket, gourl)；无 ticket 返回 ("", "")。
    """
    if not cred_url or "?" not in cred_url:
        return "", ""
    query = cred_url.split("?", 1)[1]
    ticket = ""
    gourl = ""
    for kv in query.split("&"):
        k, _, v = kv.partition("=")
        kl = k.lower()
        if kl == "ticket":
            ticket = v
        elif kl == "gourl":
            gourl = v
    return ticket, gourl


def fetch_cookies_via_crossdomain(cred_url):
    """暴力模拟浏览器：直接 GET crossDomain 跳转 URL，跟随重定向抓取最终 cookie。

    B站扫码登录成功后的 crossDomain URL 会在跳转链中通过 Set-Cookie
    写入 SESSDATA / bili_jct / DedeUserID 等登录态（域名 .bilibili.com）。
    这里用 Session 跟随所有 302 跳转，最后从 cookie jar 里捞出来。

    做法：
      1. 先访问 bilibili 主页建立基础 cookie 环境；
      2. GET crossDomain URL（带 ticket），allow_redirects=True 跟到底；
      3. 从 session.cookies 读取目标 cookie。
    """
    session = requests.Session()

    # 先访问主页，建立 buvid 等基础 cookie，部分跳转链依赖
    try:
        session.get("https://www.bilibili.com/", headers=BROWSER_HEADERS, timeout=10)
    except Exception:
        pass

    # 直接访问 crossDomain 跳转链
    session.get(cred_url, headers=BROWSER_HEADERS, timeout=15, allow_redirects=True)

    sessdata = _pick_cookie(session, "SESSDATA")
    bili_jct = _pick_cookie(session, "bili_jct")
    dedeuserid = _pick_cookie(session, "DedeUserID")
    return sessdata, bili_jct, dedeuserid


def _pick_cookie(session, name):
    """从 session.cookies 里安全取出指定名字的 cookie 值。

    跳转链可能对多个域名（.bilibili.com / www.bilibili.com）各写一次同名 cookie，
    甚至先写空值删除、再写真实值，导致 requests 的 get() 抛「multiple cookies」异常。
    这里遍历 jar，优先返回「域名含 bilibili.com 且值非空」的最后一条。
    """
    candidates = []
    for c in session.cookies:
        if c.name != name:
            continue
        domain = c.domain or ""
        value = c.value or ""
        candidates.append((domain, value))

    if not candidates:
        return ""

    # 优先：bilibili.com 域 + 非空值（取最后一个，通常是最新的真实值）
    for domain, value in reversed(candidates):
        if "bilibili.com" in domain and value:
            return value
    # 次选：任意非空值
    for domain, value in reversed(candidates):
        if value:
            return value
    # 兜底：最后一条的值（可能为空）
    return candidates[-1][1]


def update_config(sessdata, bili_jct, target="danmaku", mid=None):
    """把 SESSDATA / bili_jct / mid 写回 config.yml。

    target=danmaku      → danmaku.blivedm.sessdata / bili_jct（弹幕兜底通道）
    target=web_browse   → llm_active.web_browse.sessdata / bili_jct / mid（主动回复 B站浏览）
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if target == "web_browse":
        cfg.setdefault("llm_active", {}).setdefault("web_browse", {})
        cfg["llm_active"]["web_browse"]["sessdata"] = sessdata
        cfg["llm_active"]["web_browse"]["bili_jct"] = bili_jct
        if mid:
            cfg["llm_active"]["web_browse"]["mid"] = int(mid)
    else:
        cfg.setdefault("danmaku", {}).setdefault("blivedm", {})
        cfg["danmaku"]["blivedm"]["sessdata"] = sessdata
        cfg["danmaku"]["blivedm"]["bili_jct"] = bili_jct

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
