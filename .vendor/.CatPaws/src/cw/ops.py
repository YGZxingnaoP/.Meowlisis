import io
import threading
import time

from cw.geometry import CWScreen
from cw.guard import CWGuardError
from cw.protocol import (CWErrorCode, CWProtocolError, describe, distance, normalize_delay,
                         normalize_step)


def image_size(png):
    try:
        from PIL import Image
        with Image.open(io.BytesIO(png)) as image:
            return [int(image.size[0]), int(image.size[1])]
    except Exception:
        return []


class CWOperator:
    def __init__(self, config, device, guard, journal, session):
        self.config = config
        self.device = device
        self.guard = guard
        self.journal = journal
        self.session = session
        self.confirmer = None
        self.action_runner = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last_texts = []
        self._last_image = b""
        self._last_step = None
        self._screen = None

    def set_action_runner(self, runner):
        self.action_runner = runner

    def stop(self, reason="user"):
        self._stop.set()
        self.session.request_stop(reason)
        try:
            self.device.stop()
        except Exception:
            pass

    def clear_stop(self):
        self._stop.clear()

    def stopping(self):
        return self._stop.is_set() or self.session.is_stopping()

    def screen(self, refresh=False):
        if refresh or self._screen is None:
            self._screen = self.device.screen()
        return self._screen or CWScreen.fallback()

    def observe(self, mode="ocr", region=None, max_edge=None):
        self._check_session()
        if mode == "image":
            edge = int(max_edge or self.config.screenshot_max_edge)
            png = self.device.screenshot(max_edge=edge)
            self._last_image = png
            screen = self.screen()
            size = image_size(png)
            self.journal.record("observe", mode="image", size=len(png),
                                screen=screen.as_dict(), max_edge=edge, image_size=size)
            return {"mode": "image", "image": png, "screen": screen.as_dict(),
                    "image_size": size, "max_edge": edge}
        if mode != "ocr":
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "mode 只能是 ocr 或 image")
        if not self.config.allow_ocr:
            raise CWProtocolError(CWErrorCode.UNSUPPORTED, "OCR 已在配置中关闭")
        region = self._check_region(region)
        result = self.device.ocr(region=region)
        texts = list(result.get("texts") or [])
        self._last_texts = texts
        word = self.guard.find_sensitive([item.get("text", "") for item in texts])
        if word:
            self.guard.note_sensitive(word)
        self.journal.record("observe", mode="ocr", region=list(region or []),
                            texts=[item.get("text", "") for item in texts][:40],
                            image_size=result.get("image_size") or [],
                            sensitive=word)
        return {"mode": "ocr", "texts": texts, "image_size": result.get("image_size") or [],
                "sensitive": word}

    def _check_region(self, region):
        if not region:
            return None
        try:
            values = [int(round(float(item))) for item in region]
        except (TypeError, ValueError):
            raise CWProtocolError(CWErrorCode.BAD_REQUEST,
                                  "region 必须是 4 个整数 [x, y, 宽, 高]")
        if len(values) != 4:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST,
                                  "region 必须是 4 个整数 [x, y, 宽, 高]")
        screen = self.screen()
        x, y, w, h = values
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > screen.pixel_w or y + h > screen.pixel_h:
            raise CWProtocolError(
                CWErrorCode.OUT_OF_RANGE,
                "region 超出屏幕 %dx%d：宽高是区域大小，不是右下角坐标"
                % (screen.pixel_w, screen.pixel_h))
        return values

    def prepare(self, steps):
        screen = self.screen()
        prepared = []
        for step in steps:
            step = dict(step)
            name = step.get("action")
            if name == "swipe":
                margin = self.config.swipe_margin_px
                if step.get("direction"):
                    start, end = screen.swipe(step["direction"], step.get("ratio", 0.5), margin)
                else:
                    start = list(screen.clamp(step["from"][0], step["from"][1], margin))
                    end = list(screen.clamp(step["to"][0], step["to"][1], margin))
                span = int(distance(start, end))
                if span < self.config.swipe_min_px:
                    raise CWProtocolError(
                        CWErrorCode.BAD_REQUEST,
                        "滑动距离 %dpx 低于下限 %dpx：请用 direction+ratio，或加大 from/to 间距"
                        % (span, self.config.swipe_min_px))
                if not step.get("duration_ms"):
                    speed = max(0.2, float(self.config.swipe_speed_px_ms))
                    step["duration_ms"] = int(max(200, min(1600, round(span / speed))))
                step["from"] = start
                step["to"] = end
            elif name in ("tap", "long_press", "pinch"):
                x, y = screen.clamp(step.get("x"), step.get("y"), self.config.tap_margin_px)
                step["x"] = x
                step["y"] = y
            prepared.append(step)
        return prepared

    def single(self, step):
        prepared = self.prepare([normalize_step(step)])[0]
        self._last_step = prepared
        return self._execute([prepared], None, "single")

    def sequence(self, steps, delay_ms=None):
        normalized = [normalize_step(step) for step in (steps or [])]
        if not normalized:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "steps 不能为空")
        if len(normalized) > self.config.sequence_steps:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST,
                                  "连续操作最多 %d 步" % self.config.sequence_steps)
        prepared = self.prepare(normalized)
        return self._execute(prepared, normalize_delay(delay_ms), "sequence")

    def action(self, action_id, params=None):
        if self.action_runner is None:
            raise CWProtocolError(CWErrorCode.UNAVAILABLE, "action 执行器未就绪")
        return self.action_runner.run(action_id, params or {})

    def _check_session(self):
        self.guard.check_session_window()
        if self.session.phase == self.session.IDLE:
            raise CWProtocolError(CWErrorCode.UNAVAILABLE, "链路未激活")
        if self.stopping():
            raise CWProtocolError(CWErrorCode.CANCELLED, "已请求停止")

    def _confirm_sensitive(self, steps):
        if not self.config.sensitive_confirm:
            while self.guard.take_sensitive():
                pass
            return True
        word = self.guard.take_sensitive()
        if not word:
            return True
        if self.confirmer is None:
            raise CWGuardError("界面出现敏感词「%s」，但没有可用的确认通道" % word)
        question = "界面出现敏感内容「%s」，确认继续执行 %s 吗？" % (word, self.guard.describe_steps(steps))
        if not self.confirmer(question):
            raise CWGuardError("用户否决了敏感操作（%s）" % word)
        return True

    def _execute(self, steps, delay_ms, kind, action_id=None):
        self._check_session()
        self.guard.check_batch(steps)
        self.guard.check_rate()
        self.guard.check_app_steps(steps)
        screen = self.screen(refresh=False)
        self.guard.check_bounds(screen, steps)
        self._confirm_sensitive(steps)
        started = time.time()
        try:
            result = self.device.run_steps(steps, delay_ms)
        except CWProtocolError as exc:
            self.guard.commit(len(steps))
            self.journal.record(kind, action=describe(steps[0]) if len(steps) == 1 else "",
                                steps=[describe(step) for step in steps],
                                ok=False, code=exc.code, message=exc.message,
                                elapsed_ms=int((time.time() - started) * 1000),
                                action_id=action_id)
            raise
        self.guard.commit(len(steps))
        elapsed = int((time.time() - started) * 1000)
        entry = self.journal.record(kind,
                                    action=describe(steps[0]) if len(steps) == 1 else "",
                                    steps=[describe(step) for step in steps],
                                    params=steps[0] if len(steps) == 1 else None,
                                    delay_ms=delay_ms, ok=True, code=CWErrorCode.OK,
                                    elapsed_ms=elapsed, screen=screen.as_dict(),
                                    action_id=action_id)
        self._snapshot_thumb(kind)
        return {"ok": True, "executed": result.get("executed", len(steps)),
                "elapsed_ms": elapsed, "entry": entry}

    def _snapshot_thumb(self, tag):
        if not self.config.thumb_enabled:
            return
        try:
            png = self.device.screenshot(max_edge=self.config.thumb_long_edge)
        except Exception:
            return
        rel = self.journal.save_thumb(png, tag=tag)
        if rel:
            self.journal.record("thumb", path=rel)

    def last_texts(self):
        with self._lock:
            return list(self._last_texts)

    def last_step(self):
        return dict(self._last_step or {"action": "?"})

    def last_image(self):
        return self._last_image
