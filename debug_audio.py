# -*- coding: utf-8 -*-
"""
debug_audio.py — 播放链路实时监控（独立于项目，不 import 任何项目模块）

默认进入【实时监控模式】：一边跑项目，一边轮询所有声音相关内容，
只在「有变化」时才记录（mpv 进程启停 / 日志新增播放行 / 设备切换 / 临时文件增删 / 线程数变化），
输出到控制台，并追加写入日志文件 debug_audio_monitor_*.txt，用于排查极难复现的 bug。

监控项（声音相关）：
  1. mpv 进程启停 —— PID / 完整命令行（区分流式 rawaudio 还是文件播放）/ 存活时长
  2. 项目日志增量 —— 实时 tail logs 目录，过滤播放关键词，记录每条播放相关日志
  3. 默认扬声器 / 默认麦克风切换
  4. .temp 临时音频文件增删（唱歌/哼唱播放产物）
  5. Python 项目进程线程数变化（播放线程泄漏 / 卡死）

用法：
  python debug_audio.py                  # 实时监控（默认），Ctrl+C 退出
  python debug_audio.py --interval 0.4   # 自定义轮询间隔(秒)
  python debug_audio.py --once           # 一次性快照（旧模式）
"""

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 防 Windows 控制台 GBK 编码遇到特殊字符（音频设备名等）时崩溃
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent

# 播放相关日志关键词（用于过滤项目日志）
LOG_KEYWORDS = [
    "mpv", "播放", "打断", "流式", "合成", "队列", "音频", "声音",
    "tts", "sing", "singer", "audio", "pyaudio", "麦克风", "sensevoice",
    "嘴型", "vts", "桌宠", "哼唱", "点歌", "翻唱", "cover", "stream",
    "stream", "player", "interrupt",
]


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def sh(cmd, timeout=20):
    """执行 cmd 命令，返回去空白的 stdout 文本；失败返回空串"""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, errors="replace",
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def now_ms():
    """毫秒级时间戳"""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def parse_tasklist_csv(text):
    """解析 tasklist /FO CSV 输出，返回 [{name, pid, mem}, ...]"""
    result = []
    for line in text.splitlines():
        line = line.strip().strip('"')
        if not line:
            continue
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2:
            result.append({
                "name": parts[0],
                "pid": parts[1],
                "mem": parts[4] if len(parts) > 4 else "",
            })
    return result


def parse_wmic_list(text):
    """解析 wmic /FORMAT:LIST 输出，返回 [{key: value}, ...]"""
    result = []
    rec = {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            if rec:
                result.append(rec)
                rec = {}
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            rec[k.strip()] = v.strip()
    if rec:
        result.append(rec)
    return result


# ---------------------------------------------------------------------------
# 数据采集函数（供监控轮询）
# ---------------------------------------------------------------------------
def get_mpv_pids():
    """快速获取 mpv 进程 PID 集合（tasklist）"""
    raw = sh('tasklist /FI "IMAGENAME eq mpv.exe" /FO CSV /NH', timeout=10)
    return {r["pid"] for r in parse_tasklist_csv(raw) if r["name"].lower() == "mpv.exe"}


def get_mpv_detail():
    """获取 mpv 进程 PID -> CommandLine（wmic，较慢）"""
    raw = sh(
        "wmic process where \"name='mpv.exe'\" get ProcessId,CommandLine /FORMAT:LIST",
        timeout=15,
    )
    detail = {}
    for rec in parse_wmic_list(raw):
        pid = rec.get("ProcessId", "")
        cmd = rec.get("CommandLine", "")
        if pid:
            detail[pid] = cmd
    return detail


def get_default_devices():
    """获取默认扬声器(Playback) / 默认麦克风(Record)"""
    raw = sh(
        "powershell -NoProfile -Command "
        "\"$p=Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Multimedia\\Sound Mapper';"
        " Write-Output ('Playback=' + $p.Playback);"
        " Write-Output ('Record=' + $p.Record)\"",
        timeout=20,
    )
    dev = {}
    for line in raw.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            dev[k.strip()] = v.strip()
    return dev


def get_python_threads():
    """获取 python 进程 PID -> 线程数（wmic，较慢）"""
    raw = sh(
        "wmic process where \"name='python.exe'\" get ProcessId,ThreadCount /FORMAT:LIST",
        timeout=15,
    )
    result = {}
    for rec in parse_wmic_list(raw):
        pid = rec.get("ProcessId", "")
        try:
            tc = int(rec.get("ThreadCount", "0") or "0")
        except ValueError:
            tc = 0
        if pid:
            result[pid] = tc
    return result


def scan_temp_files():
    """扫描 .temp 下临时音频文件集合（wav）"""
    tmp = BASE_DIR / ".temp"
    if not tmp.exists():
        return set()
    try:
        return {str(p) for p in tmp.rglob("*.wav")}
    except Exception:
        return set()


def find_log_files():
    """返回 logs 目录下日志文件列表（按修改时间排序）"""
    logdir = BASE_DIR / "logs"
    if not logdir.exists():
        return []
    logs = []
    for pat in ("*.log", "*.txt"):
        logs.extend(logdir.rglob(pat))
    logs.sort(key=lambda p: p.stat().st_mtime)
    return logs


# ---------------------------------------------------------------------------
# 实时监控器
# ---------------------------------------------------------------------------
class AudioMonitor:
    """轮询监控：只在状态变化时记录"""

    FAST_INTERVAL = 0.4   # 快任务间隔（mpv 启停 / 日志增量 / 临时文件）
    SLOW_INTERVAL = 2.0   # 慢任务间隔（设备 / 线程数）

    def __init__(self, interval=0.4):
        self.interval = max(0.2, interval)
        self.log_path = BASE_DIR / (
            "debug_audio_monitor_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
        )
        self._mpv_pids = get_mpv_pids()
        self._mpv_start = {pid: time.monotonic() for pid in self._mpv_pids}
        self._mpv_cmd = {}      # pid -> 命令行
        self._devices = None
        self._threads = {}
        self._files = scan_temp_files()
        self._log_offsets = {}  # 日志文件路径 -> 已读字节偏移
        self._last_slow = 0.0
        self._start_wall = time.time()

        self.record(f"[启动] 播放链路监控开始，日志文件: {self.log_path.name}")
        self.record(f"[启动] 轮询间隔: 快={self.interval}s 慢={self.SLOW_INTERVAL}s")
        if self._mpv_pids:
            self.record(f"[mpv] 启动时已存在 {len(self._mpv_pids)} 个进程 PID={sorted(self._mpv_pids)}")
        if self._files:
            self.record(f"[文件] 启动时已有 {len(self._files)} 个临时音频文件")

    def record(self, msg):
        """记录一条事件到控制台 + 日志文件（UTF-8 完整保存）"""
        line = f"[{now_ms()}] {msg}"
        try:
            print(line, flush=True)
        except Exception:
            pass
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    # ---- 快任务 ----
    def poll_mpv(self):
        current = get_mpv_pids()
        # 新增
        for pid in sorted(current - self._mpv_pids):
            self._mpv_pids.add(pid)
            self._mpv_start[pid] = time.monotonic()
            self.record(f"[mpv] 进程出现 PID={pid}")
        # 消失
        for pid in sorted(self._mpv_pids - current):
            dur = time.monotonic() - self._mpv_start.get(pid, time.monotonic())
            cmd = self._mpv_cmd.get(pid, "")
            self.record(f"[mpv] 进程退出 PID={pid} 存活={dur:.2f}s {cmd[:120]}")
            self._mpv_pids.discard(pid)
            self._mpv_start.pop(pid, None)
            self._mpv_cmd.pop(pid, None)

        # 有新进程时，立即补查完整命令行（wmic 较慢，只在出现时查）
        if current:
            detail = get_mpv_detail()
            for pid, cmd in detail.items():
                if pid in current and pid not in self._mpv_cmd:
                    self._mpv_cmd[pid] = cmd
                    self.record(f"[mpv] 命令行 PID={pid}: {cmd}")

    def poll_project_logs(self):
        for log in find_log_files():
            key = str(log)
            try:
                size = log.stat().st_size
            except Exception:
                continue
            if key not in self._log_offsets:
                # 首次发现：从当前末尾开始（不回溯历史）
                self._log_offsets[key] = size
                continue
            if size < self._log_offsets[key]:
                # 文件被截断/轮转
                self._log_offsets[key] = 0
            if size == self._log_offsets[key]:
                continue
            try:
                with open(log, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._log_offsets[key])
                    new_text = f.read()
                    self._log_offsets[key] = size
            except Exception:
                continue
            for line in new_text.splitlines():
                low = line.lower()
                if any(k in low for k in LOG_KEYWORDS):
                    self.record(f"[日志] {line[:200]}")

    def poll_temp_files(self):
        current = scan_temp_files()
        for p in sorted(current - self._files):
            self.record(f"[文件] 新增临时音频: {p}")
        for p in sorted(self._files - current):
            self.record(f"[文件] 删除临时音频: {p}")
        self._files = current

    # ---- 慢任务 ----
    def poll_devices(self):
        cur = get_default_devices()
        if not cur:
            return
        if self._devices is None:
            self.record(
                f"[设备] 初始默认 扬声器={cur.get('Playback', '?')} 麦克风={cur.get('Record', '?')}"
            )
        elif cur != self._devices:
            self.record(
                f"[设备] 默认设备切换 扬声器={self._devices.get('Playback', '?')}->"
                f"{cur.get('Playback', '?')} 麦克风={self._devices.get('Record', '?')}->"
                f"{cur.get('Record', '?')}"
            )
        self._devices = cur

    def poll_threads(self):
        cur = get_python_threads()
        for pid, tc in cur.items():
            old = self._threads.get(pid)
            if old is not None and old != tc:
                self.record(f"[线程] python PID={pid} 线程数 {old} -> {tc}")
        # 进程消失
        for pid in sorted(set(self._threads) - set(cur)):
            self.record(f"[线程] python 进程退出 PID={pid}")
        self._threads = cur

    # ---- 主循环 ----
    def run(self):
        self.record("[运行] 开始轮询（Ctrl+C 退出）。请同时运行项目，本脚本持续记录。")
        try:
            while True:
                loop_start = time.monotonic()
                # 快任务
                self.poll_mpv()
                self.poll_project_logs()
                self.poll_temp_files()
                # 慢任务
                if loop_start - self._last_slow >= self.SLOW_INTERVAL:
                    self.poll_devices()
                    self.poll_threads()
                    self._last_slow = loop_start
                time.sleep(self.interval)
        except KeyboardInterrupt:
            self.record(f"[结束] 监控停止，共运行 {time.time() - self._start_wall:.1f}s")
            print(f"\n日志已保存到: {self.log_path}")


# ---------------------------------------------------------------------------
# 一次性快照（旧模式，保留）
# ---------------------------------------------------------------------------
def section(title):
    print("")
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def check_mpv_file():
    section("mpv.exe 文件")
    mpv = BASE_DIR / "mpv.exe"
    if not mpv.exists():
        print("  [X] 未找到 mpv.exe")
        return
    print(f"  路径: {mpv}")
    print(f"  大小: {mpv.stat().st_size / 1024 / 1024:.2f} MB")
    ver = sh(f'"{mpv}" --version', timeout=10)
    if ver:
        print(f"  版本: {ver.splitlines()[0][:120]}")


def check_mpv_procs():
    section("mpv 进程")
    raw = sh('tasklist /FI "IMAGENAME eq mpv.exe" /FO CSV /NH', timeout=15)
    procs = [r for r in parse_tasklist_csv(raw) if r["name"].lower() == "mpv.exe"]
    if not procs:
        print("  [OK] 无 mpv 进程")
        return
    for p in procs:
        print(f"    PID={p['pid']} 内存={p['mem']}")
    detail = get_mpv_detail()
    for pid, cmd in detail.items():
        print(f"    PID={pid} 命令行: {cmd}")


def check_python_procs():
    section("Python 进程（线程数）")
    threads = get_python_threads()
    raw = sh('tasklist /FI "IMAGENAME eq python.exe" /FO CSV /NH', timeout=15)
    for p in parse_tasklist_csv(raw):
        if p["name"].lower() == "python.exe":
            tc = threads.get(p["pid"], "?")
            print(f"    PID={p['pid']} 线程数={tc} 内存={p['mem']}")


def check_audio_devices():
    section("音频设备")
    dev = get_default_devices()
    if dev:
        print(f"  默认扬声器: {dev.get('Playback', '?')}")
        print(f"  默认麦克风: {dev.get('Record', '?')}")
    out = sh(
        "powershell -NoProfile -Command "
        "\"Get-CimInstance Win32_SoundDevice | Select-Object Name,Status | "
        "Format-Table -AutoSize\"",
        timeout=20,
    )
    if out:
        print(out)


def check_audio_files():
    section("播放相关音频文件")
    files = scan_temp_files()
    if files:
        print(f"  .temp 临时音频（{len(files)} 个）:")
        for p in sorted(files):
            print(f"    - {p}")
    else:
        print("  .temp 无临时音频")


def check_logs():
    section("最新播放日志")
    logs = find_log_files()
    if not logs:
        print("  [!] logs 目录无日志文件")
        return
    latest = logs[-1]
    print(f"  最新日志: {latest.name}")
    try:
        with open(latest, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-200:]
    except Exception:
        return
    hits = [ln.rstrip() for ln in lines
            if any(k in ln.lower() for k in LOG_KEYWORDS)]
    print(f"  最近 200 行内播放相关 {len(hits)} 行:")
    for ln in hits[-60:]:
        print(f"    {ln[:160]}")


def once():
    print("")
    print("#" * 72)
    print(f"#  播放链路快照  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#" * 72)
    check_mpv_file()
    check_mpv_procs()
    check_python_procs()
    check_audio_devices()
    check_audio_files()
    check_logs()
    print("")
    print("#" * 72)
    print("#  快照完成")
    print("#" * 72)


# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if "--once" in args:
        once()
        return

    interval = 0.4
    if "--interval" in args:
        try:
            i = args.index("--interval")
            interval = float(args[i + 1])
        except (ValueError, IndexError):
            interval = 0.4

    print(__doc__)
    AudioMonitor(interval=interval).run()


if __name__ == "__main__":
    main()
