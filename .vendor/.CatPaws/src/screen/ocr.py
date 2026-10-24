"""
OCR 文字识别模块，基于 PaddleOCR
"""
import logging
from typing import List, Tuple, Optional

# 全局单例，避免多次初始化（首次会自动下载模型）
_ocr_instance = None

def get_ocr():
    """按需加载 PaddleOCR：没装也不影响截图/手势，只在真正调用 OCR 时提醒"""
    global _ocr_instance
    if _ocr_instance is None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise RuntimeError(
                "OCR 不可用：当前解释器没有 paddleocr。"
                "需要文字识别时执行 runtime\\311\\python.exe -m pip install paddlepaddle paddleocr"
            ) from e
        # 抑制 PaddleOCR 过多的调试输出
        logging.getLogger("ppocr").setLevel(logging.WARNING)
        # use_angle_cls=True 能提升方向检测准确率
        _ocr_instance = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
    return _ocr_instance

class OCRResult:
    """识别结果"""
    def __init__(self, text: str, confidence: float, box: List[Tuple[int, int]]):
        self.text = text
        self.confidence = confidence
        # box 是四个顶点坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        self.box = box

    @property
    def center(self) -> Tuple[float, float]:
        """返回包围框的中心点 (x, y)"""
        xs = [p[0] for p in self.box]
        ys = [p[1] for p in self.box]
        return sum(xs)/4.0, sum(ys)/4.0

    def __repr__(self):
        return f"OCRResult(text='{self.text}', conf={self.confidence:.2f}, center={self.center})"

def ocr_text(image=None) -> List[OCRResult]:
    """
    对图片进行 OCR 识别，返回结果列表。
    若 image 为 None，则自动截图。
    """
    ocr = get_ocr()
    # 如果未传入图片，则用已有的截图功能（需确保已注入 screenshot_provider）
    if image is None:
        from . import get_screenshot
        image = get_screenshot()

    # PaddleOCR 接受 numpy array (RGB) 或图片路径，这里将 PIL Image 转为 numpy
    import numpy as np
    img_array = np.array(image.convert('RGB'))

    results = ocr.ocr(img_array, cls=True)
    if not results or not results[0]:
        return []

    result_list = []
    for line in results[0]:
        box = [(int(pt[0]), int(pt[1])) for pt in line[0]]
        text = line[1][0]
        confidence = line[1][1]
        result_list.append(OCRResult(text, confidence, box))
    return result_list