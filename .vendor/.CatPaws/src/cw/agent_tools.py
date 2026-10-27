import io
import json
import re

from cw.protocol import CWErrorCode, CWProtocolError, describe
from cw.wda import CWWDA, CWWDAError

CW_PHASE_CONTROL = "control"
CW_PHASE_RECORDING = "recording"
GRID_COLOR = (255, 0, 128)
BACK_LABELS = ("返回", "back", "Back", "BACK", "‹", "<", "chevron.left")
APP_PAGES = 4


def _schemas():
    single = {
        "type": "function",
        "function": {
            "name": "cw_single",
            "description": "单次原子操作：点一下、长按、滑动、放大缩小、输入、按 home、启动应用。坐标是截图像素。"
                           "滑动用 direction+ratio，由 PC 按安全区算起止点并自动配时长（默认 ≈150ms 的快滑，"
                           "能翻页；想要慢慢拖就在 steps 里自己带 duration_ms）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["tap", "long_press", "swipe", "pinch",
                                                          "type_text", "paste_text", "press_key",
                                                          "launch_app", "activate_app",
                                                          "terminate_app", "wait"],
                               "description": "优先 tap/swipe/输入；launch_app/activate_app 只在没有图标可点时用"},
                    "x": {"type": "integer", "description": "像素 x"},
                    "y": {"type": "integer", "description": "像素 y"},
                    "count": {"type": "integer", "minimum": 1, "maximum": 3},
                    "duration_ms": {"type": "integer"},
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"],
                                  "description": "仅 swipe：手指移动方向（up=手指上滑，看下面的内容）"},
                    "ratio": {"type": "number",
                              "description": "仅 swipe：滑动距离占可用宽/高的比例，0.3~0.6 约一屏以内"},
                    "edge": {"type": "string", "enum": ["left", "right", "top", "bottom"],
                             "description": "仅 swipe：从屏幕哪条边起手。iOS 返回上一级 = edge=left + direction=right"},
                    "scale": {"type": "number", "description": "捏合倍数，>1 放大 <1 缩小"},
                    "text": {"type": "string"},
                    "key": {"type": "string", "enum": ["home", "volume_up", "volume_down",
                                                       "delete", "return"]},
                    "bundle_id": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    }
    tap_text = {
        "type": "function",
        "function": {
            "name": "cw_tap_text",
            "description": "按文字点：自动 OCR 找到目标文字并点它的中心，一次调用完成（比「先观察再点」少一轮，快得多）。"
                           "同名有多个时用 index 选（从上到下、从左到右，0 是第一个）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "界面上的文字，例如「搜索」「确定」"},
                    "index": {"type": "integer", "minimum": 0, "maximum": 9, "default": 0},
                },
                "required": ["text"],
            },
        },
    }
    back = {
        "type": "function",
        "function": {
            "name": "cw_back",
            "description": "返回上一级：先找「返回/back/‹」按钮点，找不到就用 iOS 左缘右滑手势（一次调用搞定）。",
            "parameters": {"type": "object", "properties": {
                "ratio": {"type": "number", "default": 0.3, "description": "手势滑动距离占屏宽比例"},
            }},
        },
    }
    open_app = {
        "type": "function",
        "function": {
            "name": "cw_open_app",
            "description": "打开 App：自动回桌面、按名字找图标（找不到就翻页找），然后点开——一次调用完成，"
                           "比手动 home→观察→翻页→点省 4~6 轮。",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "App 名字，例如「美团」「微信」「设置」"},
            }, "required": ["name"]},
        },
    }
    sequence = {
        "type": "function",
        "function": {
            "name": "cw_sequence",
            "description": "连续操作：一次下发多步，设备端按顺序执行，步间隔默认 90ms、最小 90ms。"
                           "适合游戏连招、输入文字后的连续点击、以及「进入→点击→返回」这种"
                           "已经确定路径、要一步做完的场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {"type": "array", "minItems": 1, "maxItems": 20,
                              "items": {"type": "object"}},
                    "delay_ms": {"type": "integer", "minimum": 90, "maximum": 2000, "default": 90},
                },
                "required": ["steps"],
            },
        },
    }
    observe = {
        "type": "function",
        "function": {
            "name": "cw_observe",
            "description": "看屏幕。mode=ocr 返回文本与像素框（省 token，推荐先用）；mode=image 返回截图给多模态模型。任何操作前先看一次。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["ocr", "image"]},
                    "max_edge": {"type": "integer", "description": "仅 image 模式，长边像素"},
                },
                "required": ["mode"],
            },
        },
    }
    action = {
        "type": "function",
        "function": {
            "name": "cw_action",
            "description": "执行已登记的 action 脚本。先确认它的 scene 与当前界面匹配再用。",
            "parameters": {
                "type": "object",
                "properties": {"action_id": {"type": "string"}, "params": {"type": "object"}},
                "required": ["action_id"],
            },
        },
    }
    ask = {
        "type": "function",
        "function": {
            "name": "cw_ask_user",
            "description": "不确定时问用户（60 秒超时按取消处理）。比如不知道点哪个按钮、需要用户输入内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question"],
            },
        },
    }
    write_action = {
        "type": "function",
        "function": {
            "name": "cw_write_action",
            "description": "把刚刚完成的操作沉淀成 action 脚本（只在反思阶段可用，新建即 unverified）。"
                           "一个 action 一个文件夹，可以有多个 .py 文件，必须包含 main.py。",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "snake_case，2~41 字符"},
                    "title": {"type": "string", "description": "给人看的标题"},
                    "scene": {"type": "string", "description": "什么时候该用它（界面/前置条件）"},
                    "steps": {"type": "array", "items": {"type": "string"},
                              "description": "执行逻辑分步描述"},
                    "code": {"type": "string", "description": "单文件源码（等价于 files 只给 main.py）"},
                    "files": {"type": "object",
                              "description": "多文件：{\"main.py\": \"源码\", \"helper.py\": \"源码\"}，必须含 main.py"},
                    "params": {"type": "object", "description": "可调参数默认值"},
                },
                "required": ["id", "title", "scene"],
            },
        },
    }
    update_action = {
        "type": "function",
        "function": {
            "name": "cw_update_action",
            "description": "小规模修改已有 action 的脚本（仅 unverified 或 updatable 可用，改动不超过 60 行）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_id": {"type": "string"},
                    "code": {"type": "string"},
                    "reason": {"type": "string"},
                    "target": {"type": "string", "description": "默认 main.py"},
                },
                "required": ["action_id", "code", "reason"],
            },
        },
    }
    keys = {
        "type": "function",
        "function": {
            "name": "cw_keys",
            "description": "键盘可见时逐字点虚拟键盘，用来打拼音/英文（只支持 a-z 0-9）。先点输入框让键盘出现，键盘看不到会报错。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要敲的字母数字，例如 woshimiaowu"},
                },
                "required": ["text"],
            },
        },
    }
    input_tool = {
        "type": "function",
        "function": {
            "name": "cw_input",
            "description": "直接把文字写进当前界面的输入框，支持中文；不经过剪贴板、不点键盘。界面上没有可写输入框时会明确报错。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要写入的文字"},
                },
                "required": ["text"],
            },
        },
    }
    paste = {
        "type": "function",
        "function": {
            "name": "cw_paste",
            "description": "长按输入框弹出菜单，再点「粘贴」把剪贴板内容贴进去（paste_text 失败时用它兜底）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要粘贴的文字（会先写进剪贴板）"},
                    "x": {"type": "integer", "description": "长按的位置：输入框中心的像素 x"},
                    "y": {"type": "integer", "description": "长按的位置：输入框中心的像素 y"},
                },
                "required": ["text", "x", "y"],
            },
        },
    }
    type_cn = {
        "type": "function",
        "function": {
            "name": "cw_type_cn",
            "description": "把一段文字输进当前输入框（中文也行）：先试粘贴，不行就自动转拼音点键盘、"
                           "点候选词，都失败会自己回退并请主人代打。打字前先点一下输入框让键盘弹出。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要输入的文字"},
                },
                "required": ["text"],
            },
        },
    }
    task_done = {
        "type": "function",
        "function": {
            "name": "cw_task_done",
            "description": "本次任务全部办完时调用。会先把结果告诉主人并问一句还有没有别的事，主人确认后才真正结束。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "用一句人话说清楚办成了什么"},
                },
                "required": ["summary"],
            },
        },
    }
    return {"cw_single": single, "cw_sequence": sequence, "cw_tap_text": tap_text, "cw_back": back,
            "cw_open_app": open_app, "cw_observe": observe, "cw_action": action,
            "cw_ask_user": ask, "cw_keys": keys, "cw_input": input_tool, "cw_paste": paste,
            "cw_type_cn": type_cn, "cw_write_action": write_action,
            "cw_update_action": update_action, "cw_task_done": task_done}


CW_TOOL_SCHEMAS = _schemas()
CW_CONTROL_TOOLS = ["cw_observe", "cw_open_app", "cw_tap_text", "cw_back", "cw_single",
                    "cw_sequence", "cw_type_cn", "cw_input", "cw_keys", "cw_paste", "cw_action",
                    "cw_ask_user", "cw_update_action", "cw_task_done"]
CW_RECORDING_TOOLS = ["cw_observe", "cw_open_app", "cw_tap_text", "cw_back", "cw_single",
                      "cw_sequence", "cw_type_cn", "cw_input", "cw_keys", "cw_paste", "cw_action",
                      "cw_ask_user", "cw_write_action", "cw_update_action"]


class CWAgentTools:
    def __init__(self, config, operator, store, session, journal, apps=None):
        self.config = config
        self.operator = operator
        self.store = store
        self.session = session
        self.journal = journal
        self.apps = apps
        self.wda = CWWDA(config)
        self.on_task_done = None
        self.confirm_write = None

    def schemas(self, phase):
        names = CW_CONTROL_TOOLS if phase == CW_PHASE_CONTROL else CW_RECORDING_TOOLS
        return [CW_TOOL_SCHEMAS[name] for name in names if name in CW_TOOL_SCHEMAS]

    def names(self, phase):
        """当前阶段可用的工具名（正文兜底解析用）"""
        names = CW_CONTROL_TOOLS if phase == CW_PHASE_CONTROL else CW_RECORDING_TOOLS
        return [name for name in names if name in CW_TOOL_SCHEMAS]

    def dispatch(self, name, args):
        handler = getattr(self, "_do_" + str(name), None)
        if handler is None:
            return {"text": "未知工具：%s" % name}
        try:
            return handler(args or {})
        except CWProtocolError as exc:
            self.journal.record("tool_error", tool=name, code=exc.code, message=exc.message)
            return {"text": "操作失败（%s）：%s" % (exc.code, exc.message), "error": True,
                    "code": exc.code}

    def _do_cw_observe(self, args):
        mode = args.get("mode") or "ocr"
        result = self.operator.observe(mode, None, args.get("max_edge"))
        if result.get("mode") == "image":
            screen = result.get("screen") or {}
            pixel = screen.get("pixel") or [0, 0]
            size = result.get("image_size") or []
            ratio = 1.0
            if size and size[0] and pixel and pixel[0]:
                ratio = float(pixel[0]) / float(size[0])
            image = self._grid(result.get("image"), ratio)
            if size and size[0]:
                text = ("已截图 %dx%d。图上的粉线标注的是**原图像素**坐标（每格 %d 像素），"
                        "直接照线读数去点，不用自己换算。"
                        % (size[0], size[1], self._grid_step(size[0], ratio)))
            else:
                text = "已截图（%sx%s），坐标用原图像素。" % (pixel[0], pixel[1])
            return {"text": text, "image": image}
        texts = result.get("texts") or []
        lines = []
        for item in texts[:40]:
            box = item.get("box") or [0, 0, 0, 0]
            try:
                center_x = int(box[0] + box[2] / 2)
                center_y = int(box[1] + box[3] / 2)
            except (TypeError, IndexError):
                center_x, center_y = 0, 0
            lines.append("%s 中心(%d,%d)" % (item.get("text", ""), center_x, center_y))
        head = "OCR 识别到 %d 条文本：" % len(texts)
        if result.get("sensitive") and self.config.sensitive_confirm:
            head += "（注意：界面出现敏感词「%s」）" % result.get("sensitive")
        return {"text": head + "\n" + "\n".join(lines)}

    @staticmethod
    def _grid_step(width, ratio):
        """网格步长（换算回原图像素）"""
        return max(50, int(round(max(100, int(width / 6)) * ratio)))

    @staticmethod
    def _grid(png, ratio):
        """在截图上画坐标网格并标注原图像素，省掉模型自己换算"""
        if not png:
            return png
        try:
            from PIL import Image, ImageDraw
        except Exception:
            return png
        try:
            image = Image.open(io.BytesIO(png)).convert("RGB")
        except Exception:
            return png
        draw = ImageDraw.Draw(image)
        step_x = max(100, int(image.width / 6))
        step_y = max(100, int(image.height / 8))
        for x in range(step_x, image.width, step_x):
            draw.line([(x, 0), (x, image.height)], fill=GRID_COLOR, width=1)
            draw.text((x + 3, 2), str(int(x * ratio)), fill=GRID_COLOR)
        for y in range(step_y, image.height, step_y):
            draw.line([(0, y), (image.width, y)], fill=GRID_COLOR, width=1)
            draw.text((2, y + 1), str(int(y * ratio)), fill=GRID_COLOR)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    def _text_center(self, needle, index=0):
        """OCR 里找文字并返回（标签, 中心点）；index 用于同名多个时选第几个"""
        needle = str(needle or "").strip()
        if not needle:
            return None
        try:
            texts = self.operator.observe("ocr").get("texts") or []
        except Exception:
            return None
        exact = []
        loose = []
        for item in texts:
            label = str(item.get("text") or "").strip()
            if not label:
                continue
            box = item.get("box") or [0, 0, 0, 0]
            try:
                center = (int(box[0] + box[2] / 2), int(box[1] + box[3] / 2))
            except (TypeError, IndexError):
                continue
            if label == needle:
                exact.append((label, center))
            elif needle in label:
                loose.append((label, center))
        found = exact or loose
        if not found:
            return None
        found.sort(key=lambda pair: (pair[1][1], pair[1][0]))
        pos = max(0, min(int(index), len(found) - 1))
        return found[pos]

    def _do_cw_tap_text(self, args):
        """按文字点：OCR 找目标文字并点中心（一次调用替代「观察→点」两轮）"""
        target = str(args.get("text") or "").strip()
        if not target:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "text 不能为空")
        found = self._text_center(target, args.get("index") or 0)
        if not found:
            return {"text": "屏幕上没看到「%s」" % target, "error": True}
        label, (x, y) = found
        self.operator.single({"action": "tap", "x": x, "y": y})
        return {"text": "点了「%s」(%d,%d)" % (label, x, y)}

    def _do_cw_back(self, args):
        """返回上一级：先点返回按钮，没有就用左缘右滑手势（只 OCR 一次）"""
        try:
            texts = self.operator.observe("ocr").get("texts") or []
        except Exception:
            texts = []
        best = None
        for item in texts:
            label = str(item.get("text") or "").strip()
            if label in BACK_LABELS:
                box = item.get("box") or [0, 0, 0, 0]
                try:
                    center = (int(box[0] + box[2] / 2), int(box[1] + box[3] / 2))
                except (TypeError, IndexError):
                    continue
                if best is None or center[0] < best[1][0]:
                    best = (label, center)
        if best is not None:
            self.operator.single({"action": "tap", "x": best[1][0], "y": best[1][1]})
            return {"text": "点了返回「%s」(%d,%d)" % (best[0], best[1][0], best[1][1])}
        screen = self.operator.screen(refresh=False)
        ratio = float(args.get("ratio") or 0.3)
        start, end = screen.edge_swipe("left", "right", ratio, self.config.swipe_margin_px)
        self.operator.single({"action": "swipe", "from": start, "to": end})
        return {"text": "没找到返回按钮，用了左缘返回手势"}

    def _do_cw_open_app(self, args):
        """打开 App：回桌面 → 找图标文字 → 翻页找 → 点开"""
        name = str(args.get("name") or "").strip()
        if not name:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "name 不能为空")
        self.operator.single({"action": "press_key", "key": "home"})
        for page in range(APP_PAGES):
            found = self._text_center(name)
            if found:
                label, (x, y) = found
                self.operator.single({"action": "tap", "x": x, "y": y})
                return {"text": "在第 %d 屏点了「%s」(%d,%d)" % (page + 1, label, x, y)}
            self.operator.single({"action": "swipe", "direction": "left", "ratio": 0.5})
        return {"text": "翻了 %d 屏没找到「%s」" % (APP_PAGES, name), "error": True}

    def _do_cw_single(self, args):
        args = dict(args or {})
        if self.apps is not None and args.get("action") in ("launch_app", "activate_app",
                                                            "terminate_app"):
            args["bundle_id"] = self.apps.resolve(args.get("bundle_id"))
        result = self.operator.single(args)
        text = "已执行 %s（%sms）。" % (describe(self.operator.last_step()),
                                       result.get("elapsed_ms", 0))
        if (args or {}).get("action") in ("paste_text", "type_text"):
            text += self._verify_text(str((args or {}).get("text") or ""))
        return {"text": text}

    def _verify_text(self, body):
        probe = re.sub(r"\s+", "", str(body or ""))
        if not probe:
            return ""
        try:
            texts = self.operator.observe("ocr").get("texts") or []
        except Exception as exc:
            return "（无法确认有没有输入进去：%s）" % exc
        seen = re.sub(r"\s+", "", "".join(str(item.get("text") or "") for item in texts))
        for size in (len(probe), max(1, len(probe) // 2), 6):
            if size and probe[:size] in seen:
                return "屏幕上已经出现这段文字，输入成功。"
        return "但屏幕上看不到这段文字，可能没进入输入框。"

    def _do_cw_sequence(self, args):
        result = self.operator.sequence(args.get("steps") or [], args.get("delay_ms"))
        return {"text": "已执行 %d 步（%sms）。" % (result.get("executed", 0),
                                                   result.get("elapsed_ms", 0))}

    def _do_cw_action(self, args):
        action_id = args.get("action_id")
        manifest = self.store.get(action_id)
        result = self.operator.action(action_id, args.get("params") or {})
        state = "成功" if result.get("ok") else "失败"
        return {"text": "action %s（%s）%s，%sms。%s" % (
            action_id, manifest.get("title", ""), state, result.get("elapsed_ms", 0),
            result.get("message", ""))}

    def _do_cw_input(self, args):
        text = str(args.get("text") or "")
        if not text:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "text 不能为空")
        try:
            ok, info = self.wda.set_text(text)
        except CWWDAError as exc:
            return {"text": "没写进去：%s" % exc, "error": True}
        rect = info.get("rect") or {}
        return {"text": "已写入输入框（y=%s，%sx%s）：%s"
                        % (rect.get("y"), rect.get("width"), rect.get("height"),
                           str(info.get("value"))[:40])}

    def _key_map(self):
        """OCR 出虚拟键盘的字母键位置（只认 a-z 0-9）"""
        result = self.operator.observe("ocr")
        keys = {}
        for item in result.get("texts") or []:
            char = str(item.get("text") or "").strip()
            if len(char) == 1 and char.isascii() and (char.isalpha() or char.isdigit()):
                box = item.get("box") or [0, 0, 0, 0]
                try:
                    keys[char.lower()] = [int(box[0] + box[2] / 2),
                                          int(box[1] + box[3] / 2)]
                except (TypeError, IndexError):
                    continue
        return keys

    def _do_cw_keys(self, args):
        text = str(args.get("text") or "")
        keys = self._key_map()
        if len(keys) < 10:
            return {"text": "键盘看不到（只认出 %d 个按键）：先点一下输入框让键盘弹出，再调用我。"
                            % len(keys), "error": True}
        steps = []
        missing = []
        for char in text:
            low = char.lower()
            if low in keys:
                steps.append({"action": "tap", "x": keys[low][0], "y": keys[low][1]})
            else:
                missing.append(char)
        if not steps:
            return {"text": "没有可敲的键：%s" % "".join(missing)[:20], "error": True}
        self.operator.sequence(steps, 90)
        note = ""
        if missing:
            note = "；跳过了 %s" % "".join(sorted(set(missing)))[:20]
        return {"text": "敲了 %d 个键：%s%s" % (len(steps), text[:40], note)}

    @staticmethod
    def _to_pinyin(text):
        """中文转无声调拼音字母串（只保留 a-z 0-9）"""
        try:
            from pypinyin import lazy_pinyin
        except Exception:
            return ""
        parts = []
        for char in str(text or ""):
            if char.isascii() and char.isalnum():
                parts.append(char.lower())
                continue
            if not ("\u4e00" <= char <= "\u9fff"):
                continue
            parts.append("".join(lazy_pinyin(char)).lower())
        return "".join(ch for ch in "".join(parts) if ch.isascii() and ch.isalnum())

    def _candidate_center(self, text):
        """在候选词栏里找目标文字，返回点击中心"""
        target = str(text or "").strip()
        if not target:
            return None
        try:
            texts = self.operator.observe("ocr").get("texts") or []
        except Exception:
            return None
        for item in texts:
            label = str(item.get("text") or "").strip()
            if not label:
                continue
            if label == target or (len(target) >= 2 and target in label):
                box = item.get("box") or [0, 0, 0, 0]
                try:
                    return [int(box[0] + box[2] / 2), int(box[1] + box[3] / 2)]
                except (TypeError, IndexError):
                    continue
        return None

    def _clear_input(self, count):
        """回退：把刚才打进去的拼音逐字删掉（最多 40 个）"""
        steps = [{"action": "press_key", "key": "delete"} for _ in range(min(int(count), 40))]
        if not steps:
            return
        try:
            self.operator.sequence(steps, 90)
        except CWProtocolError:
            pass

    def _do_cw_type_cn(self, args):
        """中文输入：粘贴优先，不行转拼音点候选，再不行回退并请主人代打"""
        text = str(args.get("text") or "")
        if not text:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "text 不能为空")
        if text.isascii():
            self.operator.single({"action": "type_text", "text": text})
            return {"text": "已用键盘输入 ASCII：%s%s" % (text[:30], self._verify_text(text))}
        tried = []
        try:
            self.operator.single({"action": "paste_text", "text": text})
            check = self._verify_text(text)
            if "出现这段文字" in check:
                return {"text": "已粘贴输入：%s（%s）" % (text[:30], check)}
            tried.append("粘贴没确认到")
        except CWProtocolError as exc:
            tried.append("粘贴失败 %s" % exc.code)
        pinyin = self._to_pinyin(text)
        keys = self._key_map() if pinyin else {}
        missing = [ch for ch in pinyin if ch not in keys]
        if len(keys) >= 10 and pinyin and not missing:
            steps = [{"action": "tap", "x": keys[ch][0], "y": keys[ch][1]} for ch in pinyin]
            self.operator.sequence(steps, 90)
            candidate = self._candidate_center(text)
            if candidate:
                self.operator.single({"action": "tap", "x": candidate[0], "y": candidate[1]})
                check = self._verify_text(text)
                if "出现这段文字" in check:
                    return {"text": "拼音输入成功：%s（按 %s）" % (text[:30], pinyin)}
                tried.append("拼音候选点完没确认")
            else:
                tried.append("没看到候选词")
        elif pinyin:
            tried.append("键盘不可用或缺字母")
        else:
            tried.append("没有拼音转换器")
        self._clear_input(len(pinyin))
        answer = self.session.ask("这句我打不进去（%s），主人帮我打一下好吗？" % text,
                                  ["打好了", "不用了"])
        if answer and "打好" in str(answer):
            return {"text": "主人帮忙打好了：%s" % text[:30]}
        return {"text": "没打进去：%s" % "；".join(tried), "error": True}

    def _do_cw_paste(self, args):
        text = str(args.get("text") or "")
        if not text:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "text 不能为空")
        x = int(args.get("x") or 0)
        y = int(args.get("y") or 0)
        copied = True
        try:
            self.operator.single({"action": "paste_text", "text": text})
        except CWProtocolError:
            copied = False
        self.operator.single({"action": "long_press", "x": x, "y": y, "duration_ms": 800})
        texts = self.operator.observe("ocr").get("texts") or []
        target = None
        for item in texts:
            label = str(item.get("text") or "").strip()
            if "粘贴" in label or "Paste" in label or "貼上" in label:
                box = item.get("box") or [0, 0, 0, 0]
                target = [int(box[0] + box[2] / 2), int(box[1] + box[3] / 2)]
                break
        if target is None:
            return {"text": "剪贴板%s，但屏幕上没出现「粘贴」菜单项。"
                            % ("已写入" if copied else "没写入"), "error": True}
        self.operator.single({"action": "tap", "x": target[0], "y": target[1]})
        return {"text": "已点「粘贴」菜单，内容应该进去了。"}

    def _do_cw_ask_user(self, args):
        question = str(args.get("question") or "")
        answer = self.session.ask(question, args.get("options"))
        if not answer:
            return {"text": "用户没有回答（超时或取消）。", "error": True}
        return {"text": "用户回答：%s" % answer}

    def _do_cw_task_done(self, args):
        summary = str(args.get("summary") or "").strip()
        if self.on_task_done is None:
            return {"text": "收尾通道未就绪，继续操作。"}
        finished, extra = self.on_task_done(summary)
        if not finished:
            if extra:
                return {"text": "主人还有别的要求：%s。继续按这个要求操作。" % extra}
            return {"text": "主人还没有确认结束，继续操作。"}
        return {"text": "主人确认没有别的事了，任务结束。"}

    def _do_cw_write_action(self, args):
        if self.session.phase != CW_PHASE_RECORDING:
            raise CWProtocolError(CWErrorCode.GUARD, "只有反思阶段可以新建 action")
        title = str(args.get("title") or args.get("id") or "")
        scene = str(args.get("scene") or "")
        if self.confirm_write is not None:
            approved, feedback = self.confirm_write(title, scene)
            if not approved:
                note = ("主人没有同意写作脚本，回复是：%s。按主人的意思调整，或直接结束。"
                        % feedback) if feedback else "主人没有回应，不要写脚本，直接结束。"
                return {"text": note, "error": True}
        manifest = self.store.create({
            "id": args.get("id"), "title": args.get("title"), "scene": args.get("scene"),
            "code": args.get("code"), "files": args.get("files"),
            "steps": args.get("steps") or [],
            "params": args.get("params") or {}, "author": "ai",
        }, self.session.phase)
        self.journal.record("action_created", action_id=manifest.get("id"),
                            title=manifest.get("title"))
        return {"text": "已登记 action %s（未验证）。" % manifest.get("id")}

    def _do_cw_update_action(self, args):
        if self.session.phase not in (CW_PHASE_CONTROL, CW_PHASE_RECORDING):
            raise CWProtocolError(CWErrorCode.GUARD, "链路未激活")
        if self.session.phase == CW_PHASE_RECORDING and self.confirm_write is not None:
            approved, feedback = self.confirm_write(args.get("action_id"), "修改已有 action")
            if not approved:
                note = ("主人没有同意改脚本，回复是：%s。" % feedback) if feedback else "主人没有回应，不要改脚本。"
                return {"text": note, "error": True}
        manifest = self.store.update(args.get("action_id"), args.get("code"),
                                     args.get("reason"), self.session.phase,
                                     args.get("target") or "main.py")
        self.journal.record("action_updated", action_id=manifest.get("id"),
                            version=manifest.get("version"))
        return {"text": "已更新 action %s，版本 %s，状态回到 unverified。"
                        % (manifest.get("id"), manifest.get("version"))}
