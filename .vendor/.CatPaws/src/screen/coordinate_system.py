"""
CatPaws 坐标系统

iOS 设备存在两套坐标系：
  1. 物理像素（Screenshot Pixels）— 截图的原始分辨率
  2. 逻辑点（Logical Points）     — WDA / iOS UIKit 使用的坐标系

两者关系：
  screenshot_pixel = logical_point × scale

  例如 iPhone 14 Pro:
    截图尺寸  = 1170 × 2532  (物理像素)
    逻辑尺寸  = 390  × 844   (逻辑点)
    scale     = 3

本模块提供双向转换工具，确保：
  · 截图分析（CV / OCR）在像素空间进行
  · 发送给 WDA 的手势指令使用逻辑点空间
"""


class CoordinateSystem:
    """
    坐标系管理器。

    用法::

        cs = CoordinateSystem(screenshot_width=1170, screenshot_height=2532, scale=3)
        pt_x, pt_y = cs.to_point(585, 1266)   # 像素 → 逻辑点
        px_x, px_y = cs.to_pixel(195, 422)    # 逻辑点 → 像素
    """

    def __init__(self, screenshot_width: int = 0, screenshot_height: int = 0, scale: float = 1.0):
        self._sw = screenshot_width
        self._sh = screenshot_height
        self._scale = scale

    # ---- 属性 ----

    @property
    def screenshot_size(self) -> tuple:
        """截图尺寸 (width, height)，单位：物理像素"""
        return self._sw, self._sh

    @property
    def logical_size(self) -> tuple:
        """逻辑尺寸 (width, height)，单位：点（points）"""
        if self._scale <= 0:
            return 0, 0
        return int(self._sw / self._scale), int(self._sh / self._scale)

    @property
    def scale(self) -> float:
        """缩放因子（Retina 倍率）"""
        return self._scale

    # ---- 设置 ----

    def set_screenshot_size(self, width: int, height: int):
        """更新截图尺寸（每次收到新截图时自动调用）"""
        self._sw = width
        self._sh = height

    def set_scale(self, scale: float):
        """设置缩放因子"""
        self._scale = scale

    def update(self, screenshot_width: int, screenshot_height: int, scale: float = None):
        """一次性更新截图尺寸和（可选）缩放因子"""
        self._sw = screenshot_width
        self._sh = screenshot_height
        if scale is not None:
            self._scale = scale

    # ---- 转换 ----

    def to_point(self, pixel_x: float, pixel_y: float) -> tuple:
        """
        物理像素 → 逻辑点（发送给 WDA 前必须调用）

        Returns:
            (point_x, point_y) 四舍五入为整数
        """
        if self._scale <= 0:
            return int(pixel_x), int(pixel_y)
        return int(round(pixel_x / self._scale)), int(round(pixel_y / self._scale))

    def to_pixel(self, point_x: float, point_y: float) -> tuple:
        """
        逻辑点 → 物理像素

        Returns:
            (pixel_x, pixel_y) 四舍五入为整数
        """
        return int(round(point_x * self._scale)), int(round(point_y * self._scale))

    # ---- 便捷方法 ----

    def is_ready(self) -> bool:
        """坐标系是否已就绪（有截图尺寸且 scale > 0）"""
        return self._sw > 0 and self._sh > 0 and self._scale > 0

    def __repr__(self):
        return (
            f"CoordinateSystem("
            f"screenshot={self._sw}x{self._sh}, "
            f"logical={self.logical_size[0]}x{self.logical_size[1]}, "
            f"scale={self._scale})"
        )


# ---- 全局单例 ----
coord_system = CoordinateSystem()
