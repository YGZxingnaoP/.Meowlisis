import base64
import io
from PIL import Image
from .coordinate_system import coord_system


class ScreenReceiver:
    def __init__(self):
        self._latest_image: bytes = None  # 原始 PNG 字节
        self._width = 0
        self._height = 0

    def save_screenshot(self, base64_data: str):
        """手机端上传的截图（base64 编码的 PNG）"""
        try:
            # 去除可能的前缀 "data:image/png;base64,"
            if ',' in base64_data:
                base64_data = base64_data.split(',', 1)[1]
            raw = base64.b64decode(base64_data)
            # 验证图片并获取尺寸
            img = Image.open(io.BytesIO(raw))
            self._width, self._height = img.size
            self._latest_image = raw
            # 同步到全局坐标系统
            coord_system.set_screenshot_size(self._width, self._height)
            print(f"📸 收到手机截图 {self._width}x{self._height}  {coord_system}")
        except Exception as e:
            print(f"❌ 截图保存失败：{e}")

    def get_latest_image(self) -> bytes:
        """获取最新截图的原始字节（PNG）"""
        return self._latest_image

    def get_dimensions(self) -> tuple:
        """返回 (width, height)"""
        return self._width, self._height

    def set_scale(self, scale: float):
        """设置设备缩放因子（由 WDA 桥接自动注入）"""
        coord_system.set_scale(scale)
        print(f"📐 坐标缩放因子已设置: {scale}x  {coord_system}")

    def get_scale(self) -> float:
        """获取当前缩放因子"""
        return coord_system.scale
