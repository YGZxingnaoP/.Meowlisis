# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/comfy_connector/base.py
import json
import os
import time
import urllib.request
import urllib.error
import uuid

from func.log.default_log import DefaultLog

from func.toolbox.flux_painter.dialects import get_dialect, resolve_family
from func.toolbox.flux_painter.dialects.anima import ANIMA_PRO_NODES

# 工作流全部下放到 dialects/：anima 与 moss 是两套完全不同的图，不能混用。
# 这里只保留传输层（提交/轮询/下载/取图）与兼容别名。


class TBComfyBase:
    """内置/外部 ComfyUI 连接公共层：健康检查/最小图构造/提交/轮询/取图"""

    def __init__(self, config):
        """初始化。"""
        self.config = config
        self.log = DefaultLog().getLogger()

    def base_url(self) -> str:
        """当前 ComfyUI http 根地址"""
        return self.config.comfy_base()

    def unet_name(self) -> str:
        """底模文件名：由方言决定（anima 读 flux_painter.unet_model，moss 读 moss.unet_model）"""
        return self.dialect().unet(self)

    @staticmethod
    def _align16(v):
        """像素尺寸对齐到 16 的倍数（Anima/Cosmos 的 latent 需被 spatial_patch_size=2 整除）"""
        v = int(v)
        return v - (v % 16)

    def _request(self, method, path, payload=None, timeout=15):
        """请求 ComfyUI REST，返回 (ok, json或None)"""
        url = self.base_url() + path
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", errors="ignore")
                return True, json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            try:
                return False, json.loads(e.read().decode("utf-8", errors="ignore"))
            except Exception:
                return False, {"error": f"http {e.code}"}
        except Exception as e:
            return False, {"error": str(e)}

    def health(self) -> bool:
        """GET /system_stats 探测服务存活"""
        ok, _ = self._request("GET", "/system_stats", timeout=5)
        return ok

    def upload_image(self, local_path) -> str:
        """把本地参考图上传到 ComfyUI 的 input 目录，返回 LoadImage 可用的文件名

        走官方 /upload/image（multipart），内置/外部引擎通用，不往内核目录写文件；
        失败返回空串，由调用方决定退化为文生图。
        """
        path = str(local_path or "")
        if not path or not os.path.isfile(path):
            return ""
        try:
            boundary = "----meow" + uuid.uuid4().hex
            name = "ref_" + uuid.uuid4().hex[:12] + (os.path.splitext(path)[1].lower() or ".png")
            with open(path, "rb") as f:
                data = f.read()
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8") + data + (
                f"\r\n--{boundary}\r\n"
                f'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
                f"true\r\n--{boundary}--\r\n"
            ).encode("utf-8")
            req = urllib.request.Request(
                self.base_url() + "/upload/image", data=body, method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                info = json.loads(r.read().decode("utf-8", errors="ignore") or "{}")
            sub = str((info or {}).get("subfolder") or "").strip("/")
            name = str((info or {}).get("name") or "").strip()
            if not name:
                return ""
            return f"{sub}/{name}" if sub else name
        except Exception:
            self.log.exception("[flux_painter] 参考图上传失败")
            return ""

    # ==================== 方言分发 ====================
    def dialect(self):
        """当前生效的工作流方言（按底模名/显式配置解析，结果缓存）"""
        family = resolve_family(getattr(self.config, "unet_model", ""),
                                getattr(self.config, "model_family", "auto"))
        cached = getattr(self, "_dialect", None)
        if cached is not None and cached.family == family:
            return cached
        self._dialect = get_dialect(family)
        return self._dialect

    def family(self) -> str:
        """当前家族名（anima / moss）。"""
        return self.dialect().family

    def clip_types(self):
        """本方言要试的 CLIPLoader type 列表（提交失败时按顺序换）"""
        return tuple(self.dialect().clip_types)

    def build_graph(self, positive, negative, width, height, seed=None,
                    prefix="flux", clip_type=None, steps=None,
                    cfg=None, sampler=None, scheduler=None, model_sampling_shift=None):
        """织快速档图（具体节点由方言决定）"""
        return self.dialect().build_graph(
            self, positive, negative, width, height, seed=seed, prefix=prefix,
            clip_type=clip_type, steps=steps, cfg=cfg, sampler=sampler,
            scheduler=scheduler, model_sampling_shift=model_sampling_shift)

    def build_pro_graph(self, positive, negative, width, height, prefix="flux",
                        clip_type=None, seed=None, params=None):
        """织清晰档图（anima=四段全流程 / moss=50步跳层）"""
        return self.dialect().build_pro_graph(
            self, positive, negative, width, height, prefix=prefix,
            clip_type=clip_type, seed=seed, params=params)

    def with_init_image(self, graph, image_name, denoise, width, height):
        """把已织好的图原地改成图生图：只替换 latent 来源与 denoise，其余节点一律不动

        - 节点 6（EmptyLatentImage）→ LoadImage，新增 ImageScale/VAEEncode（高位 id 避开 pro 占用）；
        - 基础采样节点 7 的 latent_image 指向编码结果，denoise 用参考强度；
        - 找不到基础采样节点时原图返回（宁可退化成文生图，也不拼坏图）。
        """
        if not image_name or not isinstance(graph, dict):
            return graph
        ks = graph.get("7")
        if not isinstance(ks, dict) or ks.get("class_type") != "KSampler":
            self.log.warning("[flux_painter] 未找到基础采样节点，参考图未生效")
            return graph
        w, h = self._align16(width), self._align16(height)
        graph["6"] = {"class_type": "LoadImage", "inputs": {"image": str(image_name)}}
        graph["90"] = {"class_type": "ImageScale",
                       "inputs": {"image": ["6", 0], "upscale_method": "lanczos",
                                  "width": int(w), "height": int(h), "crop": "center"}}
        graph["91"] = {"class_type": "VAEEncode",
                       "inputs": {"pixels": ["90", 0], "vae": ["3", 0]}}
        ks["inputs"]["latent_image"] = ["91", 0]
        ks["inputs"]["denoise"] = float(denoise)
        # 交给方言做图生图的附加处理（MOSS 会在这里挂编辑 LoRA、收敛 denoise）
        hook = getattr(self.dialect(), "after_img2img", None)
        if callable(hook):
            try:
                graph = hook(self, graph) or graph
            except Exception:
                self.log.exception("[flux_painter] 图生图方言附加处理失败（忽略）")
        return graph

    # ==================== Pro 档位节点检查 ====================
    # pro 所需节点由方言声明；anima 依赖第三方插件，缺失则自动降级快速档
    PRO_REQUIRED_NODES = ANIMA_PRO_NODES

    def object_info(self, timeout=20):
        """GET /object_info（进程内缓存）；失败返回 {}"""
        cached = getattr(self, "_obj_info", None)
        if cached:
            return cached
        ok, data = self._request("GET", "/object_info", timeout=timeout)
        info = data if (ok and isinstance(data, dict)) else {}
        if info:
            self._obj_info = info
        return info

    def missing_pro_nodes(self):
        """pro 档位所需节点中，引擎未注册的清单（返回 [] 表示就绪）"""
        need = tuple(self.dialect().pro_nodes or ())
        if not need:
            return []
        info = self.object_info()
        missing = ([n for n in need if n not in info] if info else list(need))
        if missing and info:
            # 缓存可能过期（引擎刚重启/刚加载插件）：强制刷新一次再判定
            self._obj_info = None
            info2 = self.object_info()
            if info2:
                missing = [n for n in need if n not in info2]
        return missing

    def conform_inputs(self, class_type, inputs):
        """按引擎 /object_info 的真实定义对齐输入：

        - 剔除该节点不认识的键（跨插件版本重命名/新增参数时避免 validation 失败）
        - 为缺失且带默认值的 required 参数补齐默认值（如 USDU 的 batch_size）
        - object_info 不可用时原样返回（不破坏离线构造）
        """
        info = self.object_info()
        if not info:
            return inputs
        spec = (info.get(class_type) or {}).get("input") or {}
        req = spec.get("required") or {}
        opt = spec.get("optional") or {}
        if not req and not opt:
            return inputs
        known = set(req) | set(opt)
        out = {k: v for k, v in (inputs or {}).items() if k in known}
        for k, v in req.items():
            if k in out:
                continue
            meta = (v[1] if isinstance(v, (list, tuple)) and len(v) > 1
                    and isinstance(v[1], dict) else {})
            if "default" in meta:
                out[k] = meta["default"]
        return out

    def submit(self, graph, client_id=None):
        """POST /prompt 提交，返回 (ok, prompt_id, 说明)"""
        payload = {"prompt": graph}
        if client_id:
            payload["client_id"] = client_id
        ok, data = self._request("POST", "/prompt", payload=payload, timeout=30)
        if ok and isinstance(data, dict) and data.get("prompt_id"):
            return True, data["prompt_id"], ""
        detail = data if isinstance(data, dict) else {"error": "no data"}
        err = detail.get("error")
        return False, "", (err.get("message") if isinstance(err, dict) else str(detail))[:500]

    def get_history(self, prompt_id):
        """GET /history/{pid}，返回 (存在, entry)"""
        ok, data = self._request("GET", f"/history/{prompt_id}", timeout=10)
        if ok and isinstance(data, dict):
            entry = data.get(prompt_id)
            if entry:
                return True, entry
        return False, None

    # ==================== 实时进度（WebSocket） ====================
    # 按 class_type 映射阶段与权重（不依赖节点 id，fast / pro 通用）
    STAGE_WEIGHTS = {
        "KSampler": (25, "基础采样"),
        "ImageUpscaleWithModel": (5, "高清放大"),
        "UltimateSDUpscale": (40, "分块重绘"),
        "UltimateSDUpscaleNoUpscale": (40, "分块重绘"),
        "FaceDetailer": (24, "局部细化"),
        "VAEDecode": (2, "解码"),
        "SaveImage": (2, "保存"),
    }
    _DEFAULT_STAGE_WEIGHT = 1

    def stage_plan(self, graph):
        """按图统计各阶段权重与执行次数（用于进度百分比 / k/n 文案）"""
        plan = {}
        total = 0
        for node in (graph or {}).values():
            ct = node.get("class_type") if isinstance(node, dict) else None
            if not ct:
                continue
            w, name = self.STAGE_WEIGHTS.get(ct, (self._DEFAULT_STAGE_WEIGHT, ct))
            item = plan.setdefault(name, {"weight": w, "count": 0})
            item["count"] += 1
            total += w
        return plan, max(total, 1)

    def watch(self, prompt_id, graph=None, timeout=900, on_progress=None, client_id=None):
        """订阅引擎 WebSocket 实时进度并等待完成；连接失败自动回退 wait() 轮询。

        on_progress(dict) 字段：
            stage   阶段文案（多次执行的阶段带 k/n，如「分块重绘 6/16」「局部细化 2/3」）
            percent 0~100
            step    当前节点的采样步进（如 "12/20"）
            blocks  [已完成, 总数]（多次执行的阶段才有）
            elapsed 已用秒数 / eta 预计总秒数（外部补充）
        返回 (ok, images, 说明) —— 与 wait() 同签名
        """
        try:
            import websocket  # websocket-client
        except Exception:
            self.log.warning("[flux_painter] 未安装 websocket-client，回退轮询进度")
            websocket = None

        t0 = time.time()
        plan, total_w = self.stage_plan(graph)
        id2class = {str(k): (v.get("class_type") if isinstance(v, dict) else "")
                    for k, v in (graph or {}).items()}
        counts, done_w, cur_node, cur_step = {}, 0, None, ""
        cur_frac = 0.0            # 当前节点内部步进比例 0~1（阶段内平滑推进用）
        err_detail, last_emit = "", 0.0

        def _cur_weight():
            """当前正在执行的节点的权重"""
            ct = id2class.get(cur_node or "") or ""
            return self.STAGE_WEIGHTS.get(ct, (self._DEFAULT_STAGE_WEIGHT, "运行中"))[0]

        def _percent():
            # 已完成阶段权重 + 当前阶段按步进插值：采样/分块途中也能连续走动，
            # 否则一次长采样期间恒为 0，画板看起来只有 0 和 100
            """把原始进度换算成百分比。"""
            return min(99, int((done_w + _cur_weight() * cur_frac) * 100 / total_w))

        def emit(force=False):
            """回调进度或状态。"""
            nonlocal last_emit
            if not on_progress:
                return
            now = time.time()
            if not force and (now - last_emit) < 0.4:
                return
            last_emit = now
            ct = id2class.get(cur_node or "") or ""
            _w, stage = self.STAGE_WEIGHTS.get(ct, (self._DEFAULT_STAGE_WEIGHT, "运行中"))
            total_cnt = int((plan.get(stage) or {}).get("count", 1) or 1)
            cnt = int(counts.get(stage, 0))
            ev = {"stage": (f"{stage} {cnt + 1}/{total_cnt}" if total_cnt > 1 and cnt < total_cnt
                            else stage),
                  "percent": _percent(), "step": cur_step or "",
                  "elapsed": int(now - t0)}
            if total_cnt > 1:
                ev["blocks"] = [cnt, total_cnt]
            on_progress(ev)

        if websocket is not None:
            cid = client_id or f"fluxpaint_{int(t0)}"
            url = f"ws://{self.config.comfy_host}:{self.config.comfy_port}/ws?clientId={cid}"
            ws = None
            try:
                ws = websocket.create_connection(url, timeout=15)
                ws.settimeout(5)
            except Exception as e:
                self.log.warning(f"[flux_painter] WS 连接失败({e})，回退轮询进度")
                ws = None
            if ws is not None:
                if on_progress:
                    on_progress({"stage": "已入队", "percent": 0, "step": "", "elapsed": 0})
                deadline = t0 + timeout
                try:
                    while time.time() < deadline:
                        try:
                            raw = ws.recv()
                        except Exception as e:
                            if "Timeout" in type(e).__name__:
                                emit()          # 心跳：长任务期间也持续刷新
                                continue
                            self.log.warning(f"[flux_painter] WS 断开({type(e).__name__})，转轮询")
                            break
                        if not raw:
                            continue
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        mtype = msg.get("type")
                        data = msg.get("data") or {}
                        pid = data.get("prompt_id")
                        if pid and pid != prompt_id:
                            continue
                        if mtype == "progress":
                            v, mx = data.get("value"), data.get("max")
                            cur_step = f"{v}/{mx}" if v is not None else ""
                            try:
                                cur_frac = (max(0.0, min(1.0, float(v) / float(mx)))
                                            if mx else 0.0)
                            except Exception:
                                cur_frac = 0.0
                            emit()
                        elif mtype == "executing":
                            node = data.get("node")
                            if node is None:
                                break                    # 队列执行结束
                            cur_node = str(node)
                            cur_step = ""
                            cur_frac = 0.0
                            emit(force=True)
                        elif mtype == "executed":
                            node = str(data.get("node") or "")
                            ct = id2class.get(node) or ""
                            _w, stage = self.STAGE_WEIGHTS.get(ct, (self._DEFAULT_STAGE_WEIGHT, ct))
                            counts[stage] = counts.get(stage, 0) + 1
                            done_w += _w
                            cur_frac = 0.0
                            emit(force=True)
                        elif mtype == "execution_error":
                            err_detail = str(data.get("exception_message") or "execution_error")[:400]
                        elif mtype == "execution_success":
                            break
                finally:
                    try:
                        ws.close()
                    except Exception:
                        pass

        # 取结果（WS 结束或回退后，统一从 history 取，保证与 wait() 结果一致）
        exists, entry = self.get_history(prompt_id)
        if exists and entry:
            status_raw = entry.get("status") or {}
            if isinstance(status_raw, dict):
                status_str = str(status_raw.get("status_str") or "").lower()
                messages = status_raw.get("messages") or []
            else:
                status_str = str(status_raw).lower()
                messages = entry.get("messages") or []
            images = []
            for node_out in (entry.get("outputs") or {}).values():
                if isinstance(node_out, dict):
                    images.extend(node_out.get("images") or [])
            if status_str == "error":
                detail = err_detail
                for m in messages or []:
                    if isinstance(m, (list, tuple)) and m and m[0] == "execution_error" and len(m) > 1:
                        info = m[1] or {}
                        detail = str(info.get("exception_message") or detail)[:400]
                        break
                return False, [], detail or "生成失败"
            if images:
                if on_progress:
                    on_progress({"stage": "生成完成", "percent": 100, "step": "",
                                 "elapsed": int(time.time() - t0)})
                return True, images, ""
        # 结果还没落库/WS 提前断开：交给轮询兜底（与旧逻辑一致）
        if on_progress:
            on_progress({"stage": "解码中", "percent": 99, "elapsed": int(time.time() - t0)})
        return self.wait(prompt_id, timeout=180)

    def wait(self, prompt_id, timeout=900, on_event=None):
        """轮询直到完成/出错，返回 (ok, images列表, 说明)；兼容 ComfyUI 0.11 status=dict"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            exists, entry = self.get_history(prompt_id)
            if exists and entry:
                status_raw = entry.get("status") or {}
                if isinstance(status_raw, dict):
                    status_str = str(status_raw.get("status_str") or "").lower()
                    messages = status_raw.get("messages") or []
                else:
                    status_str = str(status_raw).lower()
                    messages = entry.get("messages") or []
                outputs = entry.get("outputs") or {}
                images = []
                for node_out in outputs.values():
                    if isinstance(node_out, dict):
                        images.extend(node_out.get("images") or [])
                if status_str == "error":
                    detail = ""
                    for m in messages or []:
                        if isinstance(m, (list, tuple)) and m and m[0] == "execution_error" and len(m) > 1:
                            info = m[1] or {}
                            detail = (str(info.get("exception_message") or "")[:400]
                                      if isinstance(info, dict) else str(info)[:400])
                            break
                    return False, [], detail or "生成失败"
                if images:
                    if on_event:
                        on_event("生成完成")
                    return True, images, ""
                if on_event:
                    on_event("解码中")
            else:
                if on_event:
                    on_event("排队中")
            time.sleep(1.0)
        return False, [], "等待超时"

    def image_path(self, image_entry):
        """把 ComfyUI 图片条目解析为本地绝对路径（output 目录）"""
        filename = image_entry.get("filename", "")
        subfolder = image_entry.get("subfolder", "") or ""
        out_dir = self.config.comfy_output_dir
        return os.path.join(out_dir, subfolder, filename)

    def _download_image(self, image_entry):
        """经 ComfyUI /view 下载图片到 comfy_output_dir（不依赖引擎磁盘布局猜测），
        成功返回本地绝对路径，失败返回 None"""
        filename = str(image_entry.get("filename", "") or "")
        subfolder = str(image_entry.get("subfolder", "") or "")
        typ = str(image_entry.get("type", "") or "output")
        if not filename:
            return None
        import urllib.parse
        import urllib.request
        q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": typ})
        url = self.base_url() + f"/view?{q}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=30) as r:
                blob = r.read()
        except Exception as e:
            self.log.error(f"[flux_painter] 下载图片失败 {filename}: {e}")
            return None
        if not blob or len(blob) < 1000:
            return None
        out_dir = self.config.comfy_output_dir
        if subfolder:
            out_dir = os.path.join(out_dir, subfolder)
        try:
            os.makedirs(out_dir, exist_ok=True)
            dest = os.path.join(out_dir, filename)
            with open(dest, "wb") as f:
                f.write(blob)
            return dest if os.path.isfile(dest) else None
        except Exception:
            return None

    def images_local(self, images):
        """返回图片条目对应的本地绝对路径：优先已有文件，缺失则经 /view 下载"""
        paths = []
        for entry in images or []:
            if not isinstance(entry, dict):
                continue
            p = self.image_path(entry)
            if p and os.path.isfile(p):
                paths.append(p)
                continue
            got = self._download_image(entry)
            if got:
                paths.append(got)
        return paths
