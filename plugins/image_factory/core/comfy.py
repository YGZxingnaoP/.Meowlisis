# -*- coding: utf-8 -*-
"""ComfyUI 内核对接（插件版，只服务 MOSS 8 步 DMD）。

图结构与官方 `node/MOSS-Image-SFT.json`（开关开启档）一致：
    UNETLoader → ModelSamplingAuraFlow(shift 5, flow) → LoraLoaderModelOnly(DMD 0.7)
    → KSampler(8 步 / cfg 1 / euler / sgm_uniform / denoise 1) → VAEDecode → SaveImage
"""

import json
import os
import random
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def _align16(v):
    """把画布尺寸对齐到 16 的倍数。"""
    n = int(v)
    return max(256, (n + 15) // 16 * 16)


class MossClient:
    """ComfyUI 内核对接：自启、织图、提交、等待、下载。"""
    def __init__(self, cfg, log):
        """保存配置与日志引用。"""
        self.cfg = cfg
        self.log = log
        self._proc = None

    # ==================== 内核 ====================
    def health(self, timeout=3):
        """内核是否可用。"""
        try:
            with urllib.request.urlopen(self.cfg.base_url + "/system_stats",
                                        timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def _port_open(self):
        """端口上是否已有监听（可能在启动中）。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.8)
        try:
            return s.connect_ex((self.cfg.host, int(self.cfg.port))) == 0
        except Exception:
            return False
        finally:
            s.close()

    def _wait_health(self, timeout):
        """轮询等待内核就绪。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.health(timeout=2):
                self.log.info("[image_factory] 内核就绪，用时 %.0f 秒" % (time.time() - t0))
                return True
            time.sleep(1.5)
        return False

    def ensure_engine(self):
        """返回 (ok, message)：已有人在启动就等，绝不重复拉内核"""
        if self.health():
            return True, "复用已运行的内核"
        if self._port_open():
            self.log.info("[image_factory] 端口 %d 被占用，等待其加载" % self.cfg.port)
            return ((True, "复用正在加载的内核") if self._wait_health(self.cfg.boot_timeout)
                    else (False, "端口被占用但迟迟不健康"))
        if not self.cfg.autostart:
            return False, "画图内核未运行（engine.autostart 已关）"

        python, kernel = self.cfg.python, self.cfg.kernel
        if not python or not os.path.isfile(python):
            return False, "找不到解释器: %s" % python
        if not kernel or not os.path.isdir(kernel):
            return False, "找不到内核目录: %s" % kernel
        main_py = os.path.join(kernel, "main.py")
        # 嵌入式 python 的 ._pth 固定了 sys.path，必须 -c 先插路径再 runpy
        prologue = ("import sys;sys.path.insert(0, r'%s');import os;os.chdir(r'%s');"
                    "import runpy;runpy.run_path(r'%s', run_name='__main__')"
                    % (kernel, kernel, main_py))
        args = [python, "-s", "-c", prologue,
                "--listen", self.cfg.host, "--port", str(self.cfg.port),
                "--disable-auto-launch", "--disable-manager-ui",
                "--disable-all-custom-nodes"]
        if self.cfg.output_dir:
            try:
                os.makedirs(self.cfg.output_dir, exist_ok=True)
                args += ["--output-directory", self.cfg.output_dir]
            except Exception:
                pass
        try:
            self.log.info("[image_factory] 启动 MOSS 内核（约 15~30 秒）")
            flags = 0x08000000 if os.name == "nt" else 0
            self._proc = subprocess.Popen(args, cwd=kernel, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, creationflags=flags)
        except Exception as e:
            return False, "启动内核失败: %s" % e
        if self._wait_health(self.cfg.boot_timeout):
            return True, "内核已就绪"
        if self._proc is not None and self._proc.poll() is not None:
            return False, "内核进程已退出（多半是端口被别的 ComfyUI 占着）"
        return False, "内核启动超时（%d 秒）" % self.cfg.boot_timeout

    def teardown(self):
        """停止自己拉起的那个内核进程。"""
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=15)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    # ==================== 织图（官方 8 步 DMD 档）====================
    def _lora_names(self):
        """models/loras 下的文件名集合；拿不到返回空集合（表示不校验）"""
        try:
            base = os.path.join(self.cfg.kernel, "models", "loras")
            if os.path.isdir(base):
                return {n for n in os.listdir(base) if n.lower().endswith(".safetensors")}
        except Exception:
            pass
        return set()

    def build_graph(self, positive, negative, seed=None):
        """按官方 8 步 DMD 结构织图。"""
        cfg = self.cfg
        seed = (seed if seed is not None
                else (cfg.seed if cfg.seed >= 0 else random.randint(0, 2 ** 63 - 1)))
        w, h = _align16(cfg.width), _align16(cfg.height)
        g = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": cfg.unet, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": cfg.clip, "type": "moss_image",
                             "device": "cpu" if cfg.clip_device == "cpu" else "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": cfg.vae}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
            "6": {"class_type": "EmptyFlux2LatentImage",
                  "inputs": {"width": w, "height": h, "batch_size": 1}},
            "10": {"class_type": "ModelSamplingAuraFlow",
                   "inputs": {"model": ["1", 0], "shift": float(cfg.shift),
                              "sampling": "flow"}},
        }
        model_src = ["10", 0]
        if cfg.dmd_lora:
            g["11"] = {"class_type": "LoraLoaderModelOnly",
                       "inputs": {"lora_name": cfg.dmd_lora,
                                  "strength_model": float(cfg.dmd_strength),
                                  "model": model_src}}
            model_src = ["11", 0]
        # 额外 LoRA（风格件/滑块件）：串在 DMD 之后；文件不在就跳过
        existing = self._lora_names()
        for i, lora in enumerate(getattr(cfg, "loras", []) or [], start=21):
            name = str(lora["name"])
            if existing and name not in existing:
                self.log.info("[image_factory] 额外 LoRA 未就位，已跳过：%s" % name)
                continue
            g[str(i)] = {"class_type": "LoraLoaderModelOnly",
                         "inputs": {"lora_name": name,
                                    "strength_model": float(lora.get("strength", 0.8)),
                                    "model": model_src}}
            model_src = [str(i), 0]
        g["7"] = {"class_type": "KSampler",
                  "inputs": {"model": model_src, "positive": ["4", 0], "negative": ["5", 0],
                             "latent_image": ["6", 0], "seed": int(seed),
                             "steps": int(cfg.steps), "cfg": float(cfg.cfg),
                             "sampler_name": cfg.sampler, "scheduler": cfg.scheduler,
                             "denoise": 1.0}}
        g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}}
        g["9"] = {"class_type": "SaveImage",
                  "inputs": {"images": ["8", 0], "filename_prefix": "imgfactory"}}
        return g

    # ==================== 提交 / 等待 / 取图 ====================
    def submit(self, graph, client_id=None):
        """提交 prompt，返回 (ok, prompt_id, error)。"""
        try:
            data = json.dumps({"prompt": graph,
                               "client_id": client_id or uuid.uuid4().hex}).encode()
            req = urllib.request.Request(self.cfg.base_url + "/prompt", data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                info = json.loads(r.read().decode("utf-8", "ignore") or "{}")
            pid = info.get("prompt_id")
            if not pid:
                return False, "", str(info.get("error") or info)[:200]
            return True, pid, ""
        except Exception as e:
            return False, "", "%s: %s" % (type(e).__name__, str(e)[:160])

    def wait(self, pid, timeout=None):
        """轮询 /history；返回 (ok, images, message)"""
        deadline = time.time() + (timeout or self.cfg.stall_timeout)
        last = 0
        while time.time() < deadline:
            time.sleep(2)
            try:
                with urllib.request.urlopen(self.cfg.base_url + "/history/" + pid,
                                            timeout=20) as r:
                    h = json.loads(r.read().decode("utf-8", "ignore") or "{}")
            except Exception:
                continue
            item = h.get(pid)
            if not item:
                continue
            status = (item.get("status") or {}).get("status_str")
            images = []
            for out in (item.get("outputs") or {}).values():
                images += out.get("images") or []
            if status == "error":
                msg = ""
                for m in ((item.get("status") or {}).get("messages") or []):
                    if m and m[0] == "execution_error":
                        msg = str((m[1] or {}).get("exception_message") or "")[:200]
                return False, [], msg or "执行出错"
            if images:
                return True, images, ""
            last += 1
            if last % 30 == 0:
                self.log.info("[image_factory] 等待出图…（%d 秒）" % int(time.time() - (deadline - (timeout or self.cfg.stall_timeout))))
        return False, [], "等待超时"

    def download(self, image, out_dir, index=0):
        """把 /view 返回的图下载到 out_dir，返回本地路径"""
        os.makedirs(out_dir, exist_ok=True)
        q = urllib.parse.urlencode({
            "filename": image.get("filename") or "",
            "subfolder": image.get("subfolder") or "",
            "type": image.get("type") or "output"})
        try:
            with urllib.request.urlopen(self.cfg.base_url + "/view?" + q, timeout=120) as r:
                data = r.read()
        except Exception:
            return ""
        name = "factory_%s_%02d.png" % (time.strftime("%H%M%S"), index)
        path = os.path.join(out_dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path
