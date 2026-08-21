# -*- coding: utf-8 -*-
# func/toolbox/napcat/image/gif_frame.py
# 动图(GIF)检测与抽帧：判断是否动图，抽取代表帧并做相似度去重

import os
import uuid
from typing import List, Optional

from PIL import Image

from func.log.default_log import DefaultLog


class TBGifFrame:
    """动图处理：本地 GIF 检测、中间帧±偏移抽帧、相似度比对。

    策略：
    - 判断本地图片是否为动图（n_frames > 1）；
    - 动图则取「中间帧 - offset」与「中间帧 + offset」两帧；
    - 两帧相似度 >= 阈值（默认 80%）→ 只取前者（变化不大，取一帧即可）；
    - 否则两帧都取，交给视觉模块综合理解。
    """

    # 默认阈值：0.8 = 80%
    DEFAULT_SIMILARITY_THRESHOLD = 0.8
    # 默认帧偏移量
    DEFAULT_FRAME_OFFSET = 2
    # 相似度计算的统一缩放尺寸
    SIM_SIZE = (32, 32)

    def __init__(self):
        self.log = DefaultLog().getLogger()

    @staticmethod
    def is_animated(path: str) -> bool:
        """判断本地图片是否为动图（多帧）。非本地文件或打开失败一律返回 False。"""
        if not path or not os.path.exists(path):
            return False
        try:
            with Image.open(path) as img:
                return bool(getattr(img, "is_animated", False)
                            and getattr(img, "n_frames", 1) > 1)
        except Exception:
            return False

    def select_frames(self, path: str, cache_dir: str,
                      threshold: Optional[float] = None) -> List[str]:
        """动图抽帧：返回最终应交给视觉模块的本地帧路径列表。

        - 非动图：直接返回原图路径；
        - 动图：抽中间帧±offset 两帧做相似度比对，达标取前者，否则取两帧。
        """
        thr = threshold if threshold is not None else self._threshold()
        offset = self._offset()
        if not self.is_animated(path):
            return [os.path.abspath(path)]

        os.makedirs(cache_dir, exist_ok=True)
        try:
            with Image.open(path) as img:
                n = int(getattr(img, "n_frames", 1) or 1)
                if n <= 1:
                    return [os.path.abspath(path)]

                middle = n // 2
                i1 = max(0, middle - offset)
                i2 = min(n - 1, middle + offset)

                frame_a = self._frame_image(img, i1)
                if i1 == i2:
                    return [self._save_frame(frame_a, cache_dir)]

                frame_b = self._frame_image(img, i2)
                sim = self._similarity(frame_a, frame_b)
                self.log.info(
                    f"[动图] {os.path.basename(path)} 共 {n} 帧，"
                    f"抽帧 #{i1} 与 #{i2}，相似度 {sim:.2%}"
                )

                path_a = self._save_frame(frame_a, cache_dir)
                if sim >= thr:
                    self.log.info(f"[动图] 两帧相似度 >= {thr:.0%}，仅取前者 #{i1}")
                    return [path_a]
                path_b = self._save_frame(frame_b, cache_dir)
                self.log.info(f"[动图] 两帧相似度 < {thr:.0%}，取两帧 #{i1}/#{i2}")
                return [path_a, path_b]
        except Exception:
            self.log.exception(f"动图抽帧失败，回退原图: {path}")
            return [os.path.abspath(path)]

    # ==================== 内部 ====================
    @staticmethod
    def _frame_image(img, index: int) -> Image.Image:
        """取出第 index 帧并铺白底（处理透明帧）"""
        img.seek(index)
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[3])
        return bg

    def _save_frame(self, frame: Image.Image, cache_dir: str) -> str:
        """保存帧为 PNG 到缓存目录，返回绝对路径"""
        name = f"napcat_gif_{uuid.uuid4().hex[:10]}.png"
        path = os.path.join(cache_dir, name)
        frame.save(path, "PNG")
        return os.path.abspath(path)

    @classmethod
    def _similarity(cls, a: Image.Image, b: Image.Image) -> float:
        """两帧相似度（0~1）：灰度化缩放到统一尺寸后，1 - 平均像素差/255"""
        ga = a.convert("L").resize(cls.SIM_SIZE)
        gb = b.convert("L").resize(cls.SIM_SIZE)
        pa = list(ga.getdata())
        pb = list(gb.getdata())
        total = sum(abs(x - y) for x, y in zip(pa, pb))
        max_diff = 255 * cls.SIM_SIZE[0] * cls.SIM_SIZE[1]
        return 1.0 - (total / max_diff)

    @staticmethod
    def _threshold() -> float:
        """读取配置的相似度阈值（默认 0.8）"""
        try:
            from func.toolbox.napcat.config import TBNapCatConfig
            val = TBNapCatConfig().gif_similarity_threshold
            return float(val)
        except Exception:
            return TBGifFrame.DEFAULT_SIMILARITY_THRESHOLD

    @staticmethod
    def _offset() -> int:
        """读取配置的帧偏移量（默认 2）"""
        try:
            from func.toolbox.napcat.config import TBNapCatConfig
            val = TBNapCatConfig().gif_frame_offset
            return int(val)
        except Exception:
            return TBGifFrame.DEFAULT_FRAME_OFFSET
