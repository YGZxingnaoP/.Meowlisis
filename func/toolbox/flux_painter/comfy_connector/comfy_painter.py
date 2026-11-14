# -*- coding: utf-8 -*-
import json
import os
import subprocess
import threading
import time

from func.toolbox.flux_painter.comfy_connector.base import TBComfyBase
from func.toolbox.flux_painter.comfy_connector import _bootstrap

CREATE_NO_WINDOW = 0x08000000      # 静默后台（engine_window=False）
CREATE_NEW_CONSOLE = 0x00000010    # 独立控制台窗口（engine_window=True，默认）

class TBComfyPainter(TBComfyBase):
    """内置模式：引导 .ComfyNode/ComfyUI 精简内核，子进程启动/停止，提交任务并检测进度"""

    def __init__(self, config):
        """初始化。"""
        super().__init__(config)
        self._proc = None
        self._tail = []

    def _engine_log(self) -> str:
        """内核 stdout/stderr 落盘文件（logs/comfy_engine.log），父进程退出不打断引擎输出"""
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))))
        d = os.path.join(root, "logs")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return os.path.join(d, "comfy_engine.log")

    def builtin_main(self) -> str:
        """内置内核 main.py 绝对路径"""
        return os.path.join(self.config.comfy_node_dir, "ComfyUI", "main.py")

    def _cfg(self):
        """内置状态（junction 是否成功）"""
        return _bootstrap._load_cfg(self.config) or {}

    def ensure_builtin(self):
        """内核缺失则安装，返回 (ok, 说明)"""
        return _bootstrap.ensure_installed(self.config)

    def _cmd(self):
        """组装启动命令：junction 生效则免 extra/output 参数，否则回退带参。"""
        main_py = os.path.abspath(self.builtin_main())
        kernel_dir = os.path.dirname(main_py)
        prologue = (
            "import sys;"
            "sys.path.insert(0, r'%s');"
            "import os;"
            "os.chdir(r'%s');"
            "import runpy;"
            "runpy.run_path(r'%s', run_name='__main__')"
        ) % (kernel_dir, kernel_dir, main_py)
        base = [self.config.internal_python, "-s", "-c", prologue,
                "--listen", self.config.comfy_host, "--port", str(self.config.comfy_port),
                "--disable-auto-launch", "--disable-manager-ui"]
        if not bool((getattr(self.config, "pro", {}) or {}).get("allow_custom_nodes", True)):
            base.append("--disable-all-custom-nodes")
        base += ["--disable-assets", "--log-stdout"]
        if self._cfg().get("junction"):
            return base
        extra = self._cfg().get("extra_yaml") or self._fallback_yaml()
        return base + ["--extra-model-paths-config", extra,
                       "--output-directory", self.config.comfy_output_dir]

    def _fallback_yaml(self):
        """回退生成 extra yaml 并返回路径"""
        return _bootstrap._write_extra_yaml(self.config)

    def _pid_file(self) -> str:
        """引擎身份标记文件：主程序重启后据此识别"自家的常驻引擎"并复用"""
        return os.path.join(self.config.comfy_node_dir, "engine.pid")

    def _load_pid(self):
        """读取标记 (pid, started_at)；缺失/损坏返回 (0, '')"""
        try:
            with open(self._pid_file(), "r", encoding="utf-8") as f:
                d = json.load(f)
            return int(d.get("pid") or 0), str(d.get("started_at") or "")
        except Exception:
            return 0, ""

    def _write_pid(self, pid):
        """写入内核 PID 文件。"""
        try:
            with open(self._pid_file(), "w", encoding="utf-8") as f:
                json.dump({"pid": int(pid), "mode": "internal",
                           "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "port": int(self.config.comfy_port)}, f,
                          ensure_ascii=False, indent=1)
        except Exception as e:
            self.log.warning(f"[flux_painter] 写引擎 pid 标记失败: {e}")

    def _clear_pid(self):
        """删除内核 PID 文件。"""
        try:
            if os.path.exists(self._pid_file()):
                os.remove(self._pid_file())
        except Exception:
            pass

    def _pid_alive(self, pid) -> bool:
        """进程是否存活（tasklist 探测）"""
        if not pid:
            return False
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout or ""
            return str(pid) in out
        except Exception:
            return False

    def _find_port_pid(self, port):
        """netstat 找出监听指定端口的 PID（首个 LISTENING，无则 None）"""
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True,
                                 text=True, errors="replace", timeout=15).stdout or ""
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts and parts[-1].isdigit() and parts[-1] != "0":
                        return parts[-1]
        except Exception:
            pass
        return None

    def _cmdline_of(self, pid):
        """获取进程命令行（wmic 优先，powershell 回退）"""
        for cmd in (["wmic", "process", "where", f"ProcessId={pid}",
                     "get", "commandline", "/value"],
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True,
                                     timeout=15, errors="replace").stdout or ""
                if "=" in out or "comfy" in out.lower() or "main.py" in out.lower():
                    return out.strip()
            except Exception:
                continue
        return ""

    def _is_internal_process(self, pid) -> bool:
        """该 PID 是否是我们内置引擎命令（命令行含内置启动参数 --disable-auto-launch）"""
        cmd = self._cmdline_of(pid) or ""
        return "--disable-auto-launch" in cmd and "main.py" in cmd

    def _adopt_port_engine(self):
        """把监听本端口的自家内置引擎补写 pid 标记（旧版残留无标记，收编后 stop/status 可控）"""
        pid = self._find_port_pid(self.config.comfy_port)
        if not pid:
            return None
        try:
            pid = int(pid)
        except Exception:
            return None
        if self._is_internal_process(pid):
            self._write_pid(pid)
            return pid
        return None

    def start(self, timeout=180):
        """常驻引擎启动：优先复用自家内置引擎（pid 标记/命令行匹配），端口空闲才冷启动常驻内核。"""
        if self.health():
            pid, started = self._load_pid()
            self._proc = None
            if pid and self._pid_alive(pid):
                return True, f"复用常驻引擎 (pid={pid}，自 {started} 起运行)"
            adopted = self._adopt_port_engine()
            if adopted:
                self.log.info(f"[flux_painter] 收编端口上的内置引擎为常驻 pid={adopted}")
                return True, f"复用常驻引擎 (pid={adopted}，旧版残留已收编)"
            owner = self._find_port_pid(self.config.comfy_port)
            return False, (
                f"端口 {self.config.comfy_port} 已被非内置 ComfyUI 占用"
                + (f"（PID {owner}，疑似手动开启的外部完整版）" if owner else "")
                + "：内置引擎无法使用。请先关闭该实例重试；"
                  "若确要用外部引擎，请把 config.yml 的 flux_painter.comfy.mode 改为 external")
        self._clear_pid()
        ok, msg = self.ensure_builtin()
        if not ok:
            return False, msg
        python = self.config.internal_python
        if not python or not os.path.isfile(python):
            return False, f"未找到解释器: {python}（请配置 flux_painter.comfy.internal_python）"
        os.makedirs(self.config.comfy_output_dir, exist_ok=True)
        windowed = bool(getattr(self.config, "engine_window", True))
        try:
            if windowed:
                self._proc = subprocess.Popen(
                    self._cmd(), creationflags=CREATE_NEW_CONSOLE)
            else:
                logf = open(self._engine_log(), "ab")
                self._proc = subprocess.Popen(
                    self._cmd(), stdout=logf, stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            try:
                self._clear_pid()
            except Exception:
                pass
            return False, f"启动内核失败: {e}（详见引擎窗口/内核日志: {self._engine_log()}）"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc.poll() is not None:
                rc = self._proc.returncode
                self._proc = None
                tail = self._tail_text()
                hint = ("内核启动即退出，请查看弹出的引擎窗口报错。"
                        if windowed else f"内核已退出，详见内核日志: {self._engine_log()}")
                owner = self._find_port_pid(self.config.comfy_port)
                if owner:
                    hint += (f"（端口 {self.config.comfy_port} 正被 PID {owner} 占用"
                             "，疑似外部 ComfyUI/旧引擎，请先关闭后重试）")
                return False, f"内核已退出 rc={rc}：{hint}" + (f"（{tail}）" if tail else "")
            if self.health():
                owner = self._find_port_pid(self.config.comfy_port)
                if owner and str(owner) == str(self._proc.pid):
                    pid = self._proc.pid
                    self._write_pid(pid)
                    self.log.info(f"[flux_painter] 内置 ComfyUI 内核就绪（常驻 pid={pid}，"
                                  "独立窗口模式，不随主程序退出）")
                    return True, "内置 ComfyUI 已启动（常驻服务）"
                time.sleep(1.5)
                continue
            time.sleep(1.5)
        self._proc = None
        return False, "启动超时：" + self._tail_text()

    def stop(self):
        """停止常驻引擎：优先按 pid 标记；无标记时按端口找到自家内置引擎（命令行匹配）结束；"""
        pid, _ = self._load_pid()
        target = pid if (pid and self._pid_alive(pid)) else 0
        if not target:
            found = self._find_port_pid(self.config.comfy_port)
            try:
                found = int(found) if found else 0
            except Exception:
                found = 0
            if found and self._is_internal_process(found):
                target = found
        stopped = False
        if target and self._pid_alive(target):
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(target)],
                               capture_output=True, timeout=15)
                stopped = True
                self.log.info(f"[flux_painter] 已停止常驻引擎 pid={target}")
            except Exception as e:
                self.log.warning(f"[flux_painter] 停止常驻引擎 pid={target} 失败: {e}")
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=10)
                stopped = True
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._clear_pid()
        return stopped

    def _tail_text(self) -> str:
        """从引擎日志文件读取最近若干行内核输出"""
        try:
            with open(self._engine_log(), "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 6000))
                tail = f.read().decode("utf-8", errors="ignore")
            lines = [ln for ln in tail.splitlines() if ln.strip()][-6:]
            return " | ".join(lines)[:600]
        except Exception:
            return "（无法读取内核日志）"

_managed = None
_managed_lock = threading.Lock()

def get_managed_painter(config):
    """本进程内共享的内置引擎实例（多次绘画/面板启停复用同一句柄）"""
    global _managed
    with _managed_lock:
        if _managed is None:
            _managed = TBComfyPainter(config)
    return _managed
