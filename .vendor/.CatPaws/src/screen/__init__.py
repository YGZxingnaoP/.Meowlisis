from .screen_receiver import ScreenReceiver
from .coordinate_system import coord_system, CoordinateSystem
import io
receiver = ScreenReceiver()
from .ocr import ocr_text
import numpy as np
from PIL import Image

# 截图提供者（可由 WDA 或其他源注入）
_screenshot_provider = None


def set_screenshot_provider(provider):
    """注入截图函数，provider 为 callable，返回 PIL Image"""
    global _screenshot_provider
    _screenshot_provider = provider


def get_screenshot() -> Image.Image:
    """
    获取当前截图（PIL Image）。
    优先使用注入的 provider（如 WDA），否则从 receiver 获取手机上传的截图。
    成功获取后同步截图到 receiver，以便 /screen 页面和坐标系统可用。
    """
    if _screenshot_provider:
        img = _screenshot_provider()
        if img:
            _sync_to_receiver(img)
        return img
    # 从手机端上传的截图获取
    raw = receiver.get_latest_image()
    if raw:
        return Image.open(io.BytesIO(raw))
    return None


def _sync_to_receiver(img: Image.Image):
    """将截图同步到 receiver，更新截图尺寸和 scale"""
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    receiver._latest_image = buf.getvalue()
    receiver._width, receiver._height = img.size
    coord_system.set_screenshot_size(img.width, img.height)
    # 如果 scale 还未设置，尝试从 WDA 逻辑尺寸计算
    if coord_system.scale == 1.0:
        from server.wda_native_client import get_wda_client
        client = get_wda_client()
        if client:
            logical_w, _ = client.get_screen_size()
            if logical_w and logical_w > 0:
                scale = round(img.width / logical_w, 1)
                receiver.set_scale(scale)


def to_cv2_image(pil_image: Image.Image):
    import cv2
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def distance(p1, p2):
    return np.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)