# -*- coding: utf-8 -*-
# func/toolbox/meowvision/image_handle/diff.py
# 图片变化检测：比较两帧相似度，判断画面是否发生明显变化

from typing import Optional

from PIL import Image

from func.log.default_log import DefaultLog


class TBImageDiff:
    """图片变化检测：两帧灰度化缩放到统一尺寸后计算相似度。

    - 相似度 >= threshold 判定为「无变化」（画面基本静止）；
    - 相似度 < threshold 判定为「有变化」（需要传给视觉模型分析）。
    """

    # 统一比较尺寸
    SIM_SIZE = (48, 48)
    # 默认阈值：0.85
    DEFAULT_THRESHOLD = 0.85

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def has_change(self, prev_path: str, curr_path: str,
                   threshold: Optional[float] = None) -> bool:
        """判断当前帧相对上一帧是否有明显变化。任一路径缺失视为「有变化」（不阻断分析）。"""
        if not prev_path or not curr_path:
            return True
        thr = threshold if threshold is not None else self._threshold()
        try:
            sim = self.similarity(prev_path, curr_path)
            self.log.info(f"[Watching变化检测] 相似度 {sim:.2%}，阈值 {thr:.0%}")
            return sim < thr
        except Exception:
            self.log.exception("[Watching] 变化检测失败，按有变化处理")
            return True

    @classmethod
    def similarity(cls, path_a: str, path_b: str) -> float:
        """两图相似度（0~1）：灰度化缩放到统一尺寸后 1 - 平均像素差/255"""
        with Image.open(path_a) as ia, Image.open(path_b) as ib:
            ga = ia.convert("L").resize(cls.SIM_SIZE)
            gb = ib.convert("L").resize(cls.SIM_SIZE)
            pa = list(ga.getdata())
            pb = list(gb.getdata())
            total = sum(abs(x - y) for x, y in zip(pa, pb))
            max_diff = 255 * cls.SIM_SIZE[0] * cls.SIM_SIZE[1]
            return 1.0 - (total / max_diff)

    @staticmethod
    def _threshold() -> float:
        try:
            from func.toolbox.meowvision.watching.config import TBWatchingConfig
            return float(TBWatchingConfig().change_similarity_threshold)
        except Exception:
            return TBImageDiff.DEFAULT_THRESHOLD
