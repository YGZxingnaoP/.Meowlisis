# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/img2img/ref_focus.py
# 屏幕参考聚焦：截图 → 让绘画模型点出画框的两个对角点 → 裁切 → 复查，循环到框住为止
# 只依赖绘画自己的模型端口（与写提示词同一个模型），不引入其它模块。

import json
import os
import time
import uuid

from PIL import Image, ImageGrab

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.flux_painter.config import TBFluxPainterConfig
from func.toolbox.flux_painter.img2img.ref_source import image_data_url
from func.toolbox.flux_painter.port.base import create_painter_llm


SYSTEM = (
    "你是插图绘制的取景助手。用户要画的东西出现在他电脑屏幕的截图里，"
    "你的任务是像摄影师一样，在截图上框出「应该画进画面」的那一块。\n"
    "规则：\n"
    "1. 只框用户要画的内容本体，尽量避开任务栏、窗口标题栏、聊天框等界面元素；\n"
    "2. **必须完整包住主体**：从头到身体、手、道具（杯子/武器/宠物等）都要在框内，"
    "四周再留约 5%~10% 余量；宁可框大一点，也不要切掉身体或道具；\n"
    "3. 框长宽比尽量贴近目标画布，避免后续裁掉主体；\n"
    "4. 坐标相对整张截图，归一化到 0~1000 的整数（左上角 0,0，右下角 1000,1000）；\n"
    "5. 用 focus_rect 工具回答：第一轮把 ok 设为 false 并给出 x1,y1,x2,y2（左上/右下两个对角点）；"
    "复查时**只有确实切掉了主体才给一组更大的对角点**；已经完整包住就只把 ok 设为 true、不要再给坐标；\n"
    "6. **截图里没有用户要画的主体、或者你看不确定时**：把 found 设为 false、ok 设为 false，"
    "在 problem 里说清缺什么（例如「屏幕上没看到小狐娘，只有聊天窗口」），不要硬框一块区域凑数；"
    "同时用 fallback 给出你的处置建议：只靠文字也能画得像 → text；文字信息也不够、必须先问清楚 → end；\n"
    "7. note 用一句话说明这一块画的是什么。"
)

FOCUS_TOOL = {
    "type": "function",
    "function": {
        "name": "focus_rect",
        "description": "给出（或调整）截图上的取景画框：左上角与右下角两个对角点，坐标 0~1000 归一化",
        "parameters": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean",
                          "description": "截图里是否找到了用户要画的主体；为 false 时不要再给坐标，"
                                         "在 problem 里说明缺什么"},
                "ok": {"type": "boolean", "description": "画框是否已经完整包住主体；为 true 时不要再给坐标"},
                "x1": {"type": "integer", "description": "左上角 x，0~1000"},
                "y1": {"type": "integer", "description": "左上角 y，0~1000"},
                "x2": {"type": "integer", "description": "右下角 x，0~1000"},
                "y2": {"type": "integer", "description": "右下角 y，0~1000"},
                "note": {"type": "string", "description": "这一块画的是什么，一句话"},
                "problem": {"type": "string", "description": "found 为 false 时说明缺什么"},
                "fallback": {"type": "string", "enum": ["text", "end"],
                             "description": "found 为 false 时的处置：text=不用参考图、按文字直接画；"
                                            "end=这次不画，先问用户"},
            },
            "required": ["ok"],
        },
    },
}

MIN_SIDE = 100          # 归一化最小边长（1/10 整图）


@singleton
class TBRefFocus:
    """屏幕取景：截图 + 两对角点定框 + 循环复查，产出干净的参考图（不带任何标尺/标记）"""

    def __init__(self):
        """初始化。"""
        self.log = DefaultLog().getLogger()
        self.config = TBFluxPainterConfig()

    # ==================== 截图 ====================
    def capture(self) -> str:
        """截主屏全屏 PNG，返回本地路径（失败返回空串）"""
        try:
            os.makedirs(self.config.ref_dir, exist_ok=True)
            img = ImageGrab.grab()
            path = os.path.join(
                self.config.ref_dir,
                f"screen_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png")
            img.save(path, "PNG")
            return os.path.abspath(path)
        except Exception:
            self.log.exception("[flux_painter] 屏幕截图失败")
            return ""

    # ==================== 取景 ====================
    def focus(self, screen_path, request: str, target_w: int, target_h: int, on_round=None):
        """在截图上循环定框

        返回 dict：
            crop      裁好的参考图路径（空表示没取到）
            note      这一块是什么的一句话说明
            found     截图上有没有用户要画的主体（模型判断"没看到/不确定"时为 False）
            problem   found=False 时缺什么（供上层拿来反问用户）
            confirmed 模型是否明确确认过画框

        on_round：可选回调（测试/排查用），每轮结束收到一次
        """
        result = {"crop": "", "note": "", "found": True, "problem": "",
                  "fallback": "end", "confirmed": False}
        if not screen_path or not os.path.isfile(screen_path):
            return result
        try:
            src = Image.open(screen_path).convert("RGB")
        except Exception:
            self.log.exception("[flux_painter] 读取截图失败")
            return result
        width, height = src.size
        view = self._view(screen_path)
        if not view:
            return result
        llm = create_painter_llm(self.config)
        if llm is None or not getattr(llm, "client", None):
            self.log.error("[flux_painter] 取景需要绘画模型，但客户端不可用")
            return result

        base_text = (
            "【截图画框】用户想画的东西在下面这张电脑截图里。\n"
            f"用户需求：{request}\n"
            f"目标画布长宽比约 {target_w}:{target_h}。\n"
            "请调用 focus_rect：x1,y1 是左上角、x2,y2 是右下角，坐标相对整张截图、归一化 0~1000；"
            "画框必须完整包住主体和它的道具（别切掉身体、手、杯子），四周留 5%~10% 余量；"
            "长宽比尽量贴近目标画布。第一轮把 ok 设为 false，只给出两个对角点。\n"
            "**如果截图里根本没有用户要画的东西（或你判断不确定），就不要框，"
            "把 found 设为 false、ok 设为 false，并在 problem 里说清缺什么。**"
        )
        crop_path, note = "", ""
        prev_box = None
        # 取景复查轮数：配置默认 3，硬上限 5（防止模型一直不给 ok 时反复调模型）
        rounds = min(5, max(1, int(getattr(self.config, "img2img_focus_rounds", 3) or 3)))
        for round_no in range(1, rounds + 1):
            content = [{"type": "text", "text": base_text},
                       {"type": "image_url", "image_url": {"url": self._data_url(view)}}]
            if crop_path:
                content.append({"type": "text",
                                "text": "上一轮你框出的区域见下；若裁掉了重要内容，请给一组新的对角点。"})
                content.append({"type": "image_url", "image_url": {"url": self._data_url(crop_path)}})
            data = self._call(llm, [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": content}])
            if not data:
                base_text = "（系统纠正）没有收到 focus_rect 调用，请重新调用并给出两个对角点。"
                continue
            note = str(data.get("note") or note or "")
            result["note"] = note
            # 模型说没看到（或不确定）：不硬框，直接把问题带回上层去问用户
            if data.get("found") is False:
                result["found"] = False
                result["problem"] = str(data.get("problem") or note or "").strip()
                choice = str(data.get("fallback") or "").strip().lower()
                result["fallback"] = choice if choice in ("text", "end") else "end"
                self.log.info(f"[flux_painter] 截图里没找到要画的主体"
                              f"（处置={result['fallback']}）：{result['problem'][:60]}")
                self._notify(on_round, {"round": round_no, "ok": False, "found": False,
                                       "data": data, "rect": None, "box": None,
                                       "crop": "", "note": result["problem"]})
                return result
            if data.get("ok") and crop_path:
                self.log.info(f"[flux_painter] 取景完成：{crop_path}")
                result["crop"], result["confirmed"] = crop_path, True
                self._notify(on_round, {"round": round_no, "ok": True, "found": True,
                                       "data": data, "rect": None, "box": None,
                                       "crop": crop_path, "note": note})
                return result
            box = self._to_box(data, width, height)
            if not box:
                base_text = ("（系统纠正）这组对角点无效（需要 x1<x2、y1<y2，宽高至少占整图 10%），"
                             "请重新给一组新的对角点。")
                continue
            fitted = self._fit_aspect(box, width, height, target_w, target_h)
            # 模型没给更大的框，说明不是在修补「被切掉」，视为已经框好：沿用上一轮，不再空转
            if prev_box and not self._is_larger(fitted, prev_box):
                self.log.info("[flux_painter] 取景已稳定，沿用上一轮画框")
                result["crop"], result["confirmed"] = crop_path, True
                self._notify(on_round, {"round": round_no, "ok": True, "found": True,
                                       "data": data,
                                       "rect": {k: data.get(k) for k in ("x1", "y1", "x2", "y2")},
                                       "box": prev_box, "crop": crop_path, "note": note})
                return result
            prev_box = fitted
            crop_path = self._crop(src, fitted)
            self._notify(on_round, {"round": round_no, "ok": False, "found": True,
                                   "data": data,
                                   "rect": {k: data.get(k) for k in ("x1", "y1", "x2", "y2")},
                                   "box": fitted, "crop": crop_path, "note": note})
            base_text = ("【继续复查】用户需求不变。请检查上一轮框出的区域：主体是否完整"
                         "（头、身体、手、道具是不是都在框内）？有没有被边缘切掉？"
                         "已经完整包住就只把 ok 设为 true、不要再给坐标；只有确实切掉了主体，"
                         "才给一组**更大**的对角点。")
        if crop_path:
            self.log.warning("[flux_painter] 取景未确认（轮次用尽），沿用最后一次画框")
            result["crop"] = crop_path
            return result
        self.log.warning("[flux_painter] 取景失败：没有拿到有效画框")
        return result

    # ==================== 内部工具 ====================
    def _notify(self, callback, payload):
        """回调异常不影响取景主流程"""
        if not callback:
            return
        try:
            callback(payload)
        except Exception:
            self.log.exception("[flux_painter] 取景回调异常")
    def _call(self, llm, messages):
        """一次 focus_rect 调用，返回参数字典；失败返回 None"""
        try:
            resp = llm.chat(
                messages, tools=[FOCUS_TOOL],
                tool_choice={"type": "function", "function": {"name": "focus_rect"}},
                enable_thinking=False,
                options={"temperature": 0.2, "max_tokens": 400},
            )
        except Exception:
            self.log.exception("[flux_painter] 取景模型调用异常")
            return None
        if not resp or not getattr(resp, "choices", None):
            return None
        for call in (getattr(resp.choices[0].message, "tool_calls", None) or []):
            if getattr(call.function, "name", "") != "focus_rect":
                continue
            try:
                return json.loads(call.function.arguments or "{}")
            except Exception:
                return None
        return None

    @staticmethod
    def _is_larger(new_box, old_box, factor: float = 1.05) -> bool:
        """新画框是否明显更大（模型在补「被切掉」时才应该给更大的框）"""
        try:
            new_area = max(0, new_box[2] - new_box[0]) * max(0, new_box[3] - new_box[1])
            old_area = max(0, old_box[2] - old_box[0]) * max(0, old_box[3] - old_box[1])
        except (TypeError, IndexError):
            return True
        if old_area <= 0:
            return True
        return new_area > old_area * factor

    @staticmethod
    def _fit_aspect(box, width: int, height: int, target_w: int, target_h: int):
        """把画框补成目标画布的长宽比（只扩不缩、贴边平移），避免后续固定画布把主体裁掉"""
        try:
            aspect = float(target_w) / float(target_h)
        except (TypeError, ValueError, ZeroDivisionError):
            return box
        left, top, right, bottom = box
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0 or aspect <= 0:
            return box
        if w / h < aspect:
            new_w, new_h = w, int(round(w / aspect))
        else:
            new_w, new_h = int(round(h * aspect)), h
        new_w, new_h = min(new_w, width), min(new_h, height)
        if new_w < 32 or new_h < 32:
            return box
        cx, cy = (left + right) // 2, (top + bottom) // 2
        left = min(max(0, cx - new_w // 2), width - new_w)
        top = min(max(0, cy - new_h // 2), height - new_h)
        return left, top, left + new_w, top + new_h

    @staticmethod
    def _to_box(data, width: int, height: int):
        """归一化对角点 → 原图像素框；无效或过小返回 None"""
        try:
            x1, y1 = int(data["x1"]), int(data["y1"])
            x2, y2 = int(data["x2"]), int(data["y2"])
        except (KeyError, TypeError, ValueError):
            return None
        x1, x2 = min(max(x1, 0), 1000), min(max(x2, 0), 1000)
        y1, y2 = min(max(y1, 0), 1000), min(max(y2, 0), 1000)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        if x2 - x1 < MIN_SIDE or y2 - y1 < MIN_SIDE:
            return None
        left, right = int(width * x1 / 1000), int(width * x2 / 1000)
        top, bottom = int(height * y1 / 1000), int(height * y2 / 1000)
        if right - left < 32 or bottom - top < 32:
            return None
        return left, top, right, bottom

    def _crop(self, src, box):
        """裁切并落盘（干净图，不叠加任何标记）"""
        try:
            os.makedirs(self.config.ref_dir, exist_ok=True)
            path = os.path.join(
                self.config.ref_dir,
                f"focus_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png")
            src.crop(box).save(path, "PNG")
            return os.path.abspath(path)
        except Exception:
            self.log.exception("[flux_painter] 参考图裁切失败")
            return ""

    def _view(self, path: str) -> str:
        """给模型看的缩略图：长边不超过配置上限，减少传输与 token"""
        try:
            img = Image.open(path).convert("RGB")
            limit = int(getattr(self.config, "img2img_screen_max_side", 1280) or 1280)
            side = max(img.size)
            if side > limit:
                ratio = limit / float(side)
                img = img.resize((max(1, int(img.width * ratio)),
                                  max(1, int(img.height * ratio))), Image.LANCZOS)
            os.makedirs(self.config.ref_dir, exist_ok=True)
            out = os.path.join(
                self.config.ref_dir,
                f"view_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png")
            img.save(out, "PNG")
            return os.path.abspath(out)
        except Exception:
            self.log.exception("[flux_painter] 生成取景缩略图失败")
            return ""

    @staticmethod
    def _data_url(path: str) -> str:
        """本地图片 → data url（供多模态消息使用）"""
        return image_data_url(path)
