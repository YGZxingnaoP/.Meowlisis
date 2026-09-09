# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/nsfw_judge.py
"""群聊裸露审查：NudeNet v3.4 ONNX（onnxruntime CPU 推理，PIL 预处理，无需 cv2）

模型：nudenet.onnx（约 11.6MB，vladmandic/nudenet，NudeNet v3.4 导出）
下载源（config.yml flux_painter.nsfw_check.model_url，默认 HF）：
    https://huggingface.co/vladmandic/nudenet/resolve/main/nudenet.onnx
首次使用自动下载到 .ComfyNode/nsfw/；失败时可手动放置同路径。

输出 output0[1, 22, 2100]：YOLO 式（每列 = cx,cy,w,h + 18 类得分）。
类别顺序按 NudeNet v3.4（0-4 为暴露敏感器官：女性生殖器/男性生殖器/肛门/胸/臀）。
"""
import os
import threading
import urllib.request

from func.log.default_log import DefaultLog

# 敏感暴露类索引（NudeNet v3.4 顺序，与 vladmandic/nudenet onnx 一致）
SENSITIVE_CLASSES = {
    0: "female_genitalia_exposed",
    1: "male_genitalia_exposed",
    2: "anus_exposed",
    3: "breast_exposed",
    4: "buttocks_exposed",
}
# 检出门槛（低于此分不视为检出）
DETECT_FLOOR = 0.12

_lock = threading.Lock()
_sessions = {}


def _get_session(path):
    """onnx session 进程内缓存（加载约 0.5~1s，避免每次推理重载）"""
    import onnxruntime as ort
    key = path
    with _lock:
        s = _sessions.get(key)
        if s is None:
            s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
            _sessions[key] = s
        return s


class TBNsfwJudge:
    """裸露检测器：ensure_model() 保证模型就绪；judge(image) -> (nsfw, detail)"""

    def __init__(self, config):
        self.config = config
        self.log = DefaultLog().getLogger()

    # ==================== 模型就绪 ====================
    def ensure_model(self):
        """返回 (ok, 说明)；缺失时自动从 model_url 下载"""
        path = self.config.nsfw_model_path
        if path and os.path.isfile(path) and os.path.getsize(path) > 10_000_000:
            return True, "模型就绪"
        url = self.config.nsfw_model_url or ""
        if not path or not url:
            return False, f"未配置模型路径/下载源（手动放置: {path}）"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".download"
            self.log.info(f"[flux_painter] 下载 NudeNet 模型… {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
                while True:
                    b = r.read(1 << 16)
                    if not b:
                        break
                    f.write(b)
            if os.path.getsize(tmp) > 10_000_000:
                os.replace(tmp, path)
                return True, "模型已下载"
            os.remove(tmp)
            return False, "模型下载不完整"
        except Exception as e:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return False, f"模型下载失败: {e}（可手动下载放置到 {path}）"

    # ==================== 推理 ====================
    def _preprocess(self, pil_img):
        """RGB → 320×320 → /255 → NCHW float32"""
        import numpy as np
        from PIL import Image
        img = pil_img.convert("RGB").resize((320, 320), Image.BILINEAR)
        arr = np.asarray(img, dtype=np.float32) / 255.0          # HWC
        return np.transpose(arr, (2, 0, 1))[None, ...]           # NCHW

    def _decode(self, out):
        """output0[1,22,2100] → [(score, cls_name, box01)]"""
        import numpy as np
        pred = out[0]                                            # 22 x 2100
        boxes = pred[:4]                                         # cx,cy,w,h（0-1 比例）
        scores = pred[4:]                                        # 18 x 2100
        cx, cy, w, h = boxes
        x1 = np.clip(cx - w / 2, 0, 1)
        y1 = np.clip(cy - h / 2, 0, 1)
        x2 = np.clip(cx + w / 2, 0, 1)
        y2 = np.clip(cy + h / 2, 0, 1)
        results = []
        idx = np.argmax(scores, axis=0)
        for i in range(pred.shape[1]):
            s = float(scores[idx[i], i])
            if s < DETECT_FLOOR:
                continue
            results.append((s, int(idx[i]), (float(x1[i]), float(y1[i]),
                                             float(x2[i]), float(y2[i]))))
        results.sort(key=lambda r: r[0], reverse=True)
        return results

    def judge(self, image_path):
        """判定裸露。返回 (nsfw: bool, detail: str)。
        detail 形如 'breast_exposed 0.72@[0.30,0.20,0.70,0.60]'；nsfw 由阈值与敏感类决定"""
        from PIL import Image
        threshold = self.config.nsfw_threshold
        try:
            with Image.open(image_path) as im:
                arr = self._preprocess(im)
            sess = _get_session(self.config.nsfw_model_path)
            out = sess.run(None, {"images": arr})[0]
            dets = self._decode(out)
        except Exception as e:
            self.log.exception("[flux_painter] NudeNet 推理异常")
            return False, f"judge_error:{e}"
        # 敏感暴露类且达到阈值 → nsfw
        nsfw = False
        parts = []
        for s, c, box in dets:
            name = SENSITIVE_CLASSES.get(c)
            if name is None:
                continue
            parts.append(f"{name} {s:.2f}")
            if s >= threshold:
                nsfw = True
        if not parts:
            return False, "safe"
        detail = " | ".join(parts[:5])
        return nsfw, ("nsfw " + detail if nsfw else "safe " + detail)
