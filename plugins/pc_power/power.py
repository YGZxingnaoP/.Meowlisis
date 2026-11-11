# -*- coding: utf-8 -*-
"""断电动作：进程体检（下载/上传）、服务收尾、系统关机。

安全约定：
- dry_run（配置或环境变量 MEOW_POWER_DRY_RUN）为真时，只记录不执行；
- 进程名单来自配置里的命令行关键字，匹配不到就绝不乱杀；
- 不结束当前进程与系统进程，主程序交给系统关机收尾。
"""

import os
import subprocess
import time

# 常见下载/上传客户端（进程名或命令行关键字，小写）
DEFAULT_TRANSFER_KEYWORDS = (
    "qbittorrent", "utorrent", "transmission", "aria2", "motrix",
    "thunder", "xunlei", "xldl", "idm", "internet download manager",
    "free download manager", "fdm", "baidunetdisk", "baidupan",
    "aliyunpan", "115", "steam", "epicgameslauncher", "battle.net",
)

# 本项目自己的常驻服务（命令行关键字；不含主程序与配置界面）
DEFAULT_SERVICE_KEYWORDS = (
    ".Sovits", ".SenseVoice", ".NeteaseMusic", ".RVC",
    ".desktopet", ".cam", ".CatPaws", ".ComfyNode", "NapCatWinBootMain",
)

def csv_list(raw, default=()):
    """逗号（中英文）分隔的文本 → 去重列表；空值用默认表"""
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        text = str(raw or "").replace("，", ",")
        items = [x.strip() for x in text.split(",")]
    out = []
    for item in items:
        item = str(item or "").strip()
        if item and item not in out:
            out.append(item)
    if out:
        return out
    return [str(x) for x in (default or ())]


def dry_run(cfg):
    """是否只走流程：环境变量优先于配置"""
    env = os.environ.get("MEOW_POWER_DRY_RUN")
    if env is not None:
        return str(env).strip().lower() not in ("0", "false", "no", "off", "")
    return bool((cfg or {}).get("dry_run", True))


def _psutil():
    try:
        import psutil
        return psutil
    except Exception:
        return None


def _cmdline(proc):
    try:
        parts = proc.cmdline() or []
        return " ".join(str(x) for x in parts)
    except Exception:
        return ""


def _label(proc):
    try:
        return str(proc.name() or "")
    except Exception:
        return ""


def _match(haystack, keywords):
    body = str(haystack or "").lower()
    for word in keywords:
        if word and str(word).lower() in body:
            return str(word)
    return ""


def find_transfer_processes(keywords, net_busy_mbps=0.0, sample_sec=2.0,
                            exclude_pids=(), log=None):
    """找出正在下载/上传的进程。

    判定两类：
    - 进程：进程名或命令行命中下载/上传客户端关键字；
    - 网络：整体吞吐超过阈值（可能是浏览器/系统在传，无法定位到单个进程）。
    返回 [{"pid","name","kind","detail"}]。
    """
    ps = _psutil()
    if ps is None:
        if log:
            log.warning("[pc_power] 没有 psutil，跳过下载/上传体检")
        return []
    words = [str(x) for x in (keywords or ())]
    skip = set(int(x) for x in (exclude_pids or ()))
    skip.add(os.getpid())
    found = []
    for proc in ps.process_iter(["pid", "name"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid <= 4 or pid in skip:
                continue
            name = _label(proc)
            cmd = _cmdline(proc)
            hit = _match(name + " " + cmd, words)
            if not hit:
                continue
            found.append({"pid": pid, "name": name or "?", "kind": "process",
                          "detail": "命中「%s」" % hit})
        except Exception:
            continue
    mbps = 0.0
    try:
        mbps = float(net_busy_mbps or 0)
    except (TypeError, ValueError):
        mbps = 0.0
    if mbps > 0:
        rate = _net_rate_mbps(ps, sample_sec)
        if rate is not None and rate >= mbps:
            found.append({"pid": 0, "name": "网络流量", "kind": "network",
                          "detail": "≈%.1f MB/s（阈值 %.1f）" % (rate, mbps)})
    return found


def _net_rate_mbps(ps, sample_sec=2.0):
    """采样整体网络吞吐（MB/s）；采样失败返回 None"""
    try:
        first = ps.net_io_counters()
        begin = time.time()
        time.sleep(max(0.2, float(sample_sec)))
        second = ps.net_io_counters()
        span = max(0.2, time.time() - begin)
        delta = (second.bytes_sent + second.bytes_recv) - \
                (first.bytes_sent + first.bytes_recv)
        return max(0.0, float(delta) / span / 1024.0 / 1024.0)
    except Exception:
        return None


def stop_services(keywords, dry_run=False, exclude_pids=(), log=None):
    """结束本项目自己的常驻服务进程；返回被结束的进程名列表"""
    if dry_run:
        if log:
            log.info("[pc_power] dry-run：跳过结束服务进程")
        return []
    ps = _psutil()
    if ps is None:
        return []
    words = [str(x) for x in (keywords or ())]
    skip = set(int(x) for x in (exclude_pids or ()))
    skip.add(os.getpid())
    killed = []
    for proc in ps.process_iter(["pid", "name"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid <= 4 or pid in skip:
                continue
            name = _label(proc)
            cmd = _cmdline(proc)
            if not _match(name + " " + cmd, words):
                continue
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    continue
            killed.append("%s(%d)" % (name or "?", pid))
            if log:
                log.info("[pc_power] 已结束服务进程 %s(%d)", name or "?", pid)
        except Exception:
            continue
    return killed


def schedule_shutdown(mode="shutdown", delay_sec=20, dry_run=False,
                      note="", log=None):
    """执行系统关机/休眠/睡眠；返回 (ok, message)"""
    mode = str(mode or "shutdown").lower()
    try:
        delay = max(0, min(600, int(delay_sec)))
    except (TypeError, ValueError):
        delay = 20
    note = str(note or "喵呜要睡了")
    if dry_run:
        if log:
            log.info("[pc_power] dry-run：本应执行 %s（延迟 %s 秒）", mode, delay)
        return False, "dry-run"
    if mode == "hibernate":
        cmd = ["shutdown", "/h"]
    elif mode == "sleep":
        cmd = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"]
    else:
        cmd = ["shutdown", "/s", "/t", str(delay), "/c", note]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              errors="replace", timeout=20)
        out = (proc.stdout or proc.stderr or "").strip()
        if log:
            log.info("[pc_power] 关机命令 %s → rc=%s %s", mode, proc.returncode, out[:200])
        return proc.returncode == 0, out or "rc=%s" % proc.returncode
    except Exception as e:
        if log:
            log.exception("[pc_power] 执行关机命令失败")
        return False, str(e)


def abort_shutdown(log=None):
    """撤销已排队的关机（shutdown /a）"""
    try:
        proc = subprocess.run(["shutdown", "/a"], capture_output=True, text=True,
                              errors="replace", timeout=15)
        ok = proc.returncode == 0
        if log:
            log.info("[pc_power] 撤销关机 rc=%s", proc.returncode)
        return ok
    except Exception:
        if log:
            log.exception("[pc_power] 撤销关机失败")
        return False
