# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/comfy_connector/comfy_painter.py
import os
import subprocess
import threading
import time

from func.log.default_log import DefaultLog
from func.toolbox.flux_painter.comfy_connector.base import TBComfyBase
from func.toolbox.flux_painter.comfy_connector import _bootstrap

CREATE_NO_WINDOW = 0x08000000


class TBComfyPainter(TBComfyBase):
    """内置模式：引导 .ComfyNode/ComfyUI 精简内核，子进程启动/停止，提交任务并检测进度"""

    def __init__(self, config):
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

    # ==================== 内核引导 ====================
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
        """组装启动命令：junction 生效则免 extra/output 参数，否则回退带参"""
        main_py = self.builtin_main()
        cfg = self._cfg()
        base = [self.config.internal_python, "-s", main_py,
                "--listen", self.config.comfy_host, "--port", str(self.config.comfy_port),
                "--disable-auto-launch", "--disable-manager-ui", "--disable-all-custom-nodes",
                "--disable-assets-autoscan", "--log-stdout"]
        if cfg.get("junction"):
            return base
        extra = cfg.get("extra_yaml") or self._fallback_yaml()
        return base + ["--extra-model-paths-config", extra,
                       "--output-directory", self.config.comfy_output_dir]

    def _fallback_yaml(self):
        """回退生成 extra yaml 并返回路径"""
        return _bootstrap._write_extra_yaml(self.config)

    # ==================== 进程管理 ====================
    def _find_port_pid(self, port):
        """netstat 找出占用端口的 PID（返回首个 LISTENING 的 PID，无则 None）"""
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True,
                                 text=True, errors="replace", timeout=15).stdout or ""
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        if pid.isdigit() and pid != "0":
                            return pid
        except Exception:
            pass
        return None

    def _kill_port_owner(self, port):
        """结束占用端口的孤儿/外部进程（taskkill），返回是否执行了结束"""
        pid = self._find_port_pid(port)
        if not pid:
            return False
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           capture_output=True, timeout=15)
            self.log.warning(f"[flux_painter] 已结束孤儿/外部 ComfyUI 进程 PID={pid}（stdout 管道断裂的执行会 Errno22）")
            return True
        except Exception as e:
            self.log.warning(f"[flux_painter] 结束进程 {pid} 失败: {e}")
            return False

    def start(self, timeout=180):
        """启动 headless 内核并等待健康，返回 (ok, 说明)

        只信任本进程拉起的引擎：若端口被占用但非本进程句柄，说明是上次残留的孤儿
        （其 stdout 管道已断裂，提交能通过但执行必报 Errno22），先清掉再自启。
        """
        if self.health():
            if self._proc and self._proc.poll() is None:
                return True, "ComfyUI 已在运行"
            self.log.warning("[flux_painter] 检测到端口被非本进程的 ComfyUI 占用，"
                             "判定为残留孤儿进程，结束并重新启动内核")
            self._kill_port_owner(self.config.comfy_port)
        ok, msg = self.ensure_builtin()
        if not ok:
            return False, msg
        python = self.config.internal_python
        if not python or not os.path.isfile(python):
            return False, f"未找到解释器: {python}（请配置 flux_painter.comfy.internal_python）"
        os.makedirs(self.config.comfy_output_dir, exist_ok=True)
        logf = open(self._engine_log(), "ab")
        try:
            self._proc = subprocess.Popen(
                self._cmd(), stdout=logf, stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            try:
                logf.close()
            except Exception:
                pass
            return False, f"启动内核失败: {e}（内核日志: {self._engine_log()}）"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc.poll() is not None:
                return False, f"内核已退出 rc={self._proc.returncode}：" + self._tail_text()
            if self.health():
                self.log.info("[flux_painter] 内置 ComfyUI 内核就绪")
                return True, "内置 ComfyUI 已启动"
            time.sleep(1.5)
        return False, "启动超时：" + self._tail_text()

    def stop(self):
        """停止内核子进程"""
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=10)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        return True

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
