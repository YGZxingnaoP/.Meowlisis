import json
import re

from cw.protocol import CWErrorCode, CWProtocolError, describe
from cw.wda import CWWDA, CWWDAError

CW_PHASE_RUNNING = "running"
CW_PHASE_REFLECTING = "reflecting"


def _schemas():
    single = {
        "type": "function",
        "function": {
            "name": "cw_single",
            "description": "单次原子操作：点一下、长按、滑动、放大缩小、输入、按 home、启动应用。坐标是截图像素。滑动用 direction+ratio，由 PC 按安全区算起止点并自动配时长。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["tap", "long_press", "swipe", "pinch",
                                                          "type_text", "paste_text", "press_key",
                                                          "launch_app", "activate_app",
                                                          "terminate_app", "wait"]},
                    "x": {"type": "integer", "description": "像素 x"},
                    "y": {"type": "integer", "description": "像素 y"},
                    "count": {"type": "integer", "minimum": 1, "maximum": 3},
                    "duration_ms": {"type": "integer"},
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"],
                                  "description": "仅 swipe：手指移动方向（up=手指上滑，看下面的内容）"},
                    "ratio": {"type": "number",
                              "description": "仅 swipe：滑动距离占可用宽/高的比例，0.3~0.6 约一屏以内"},
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
    sequence = {
        "type": "function",
        "function": {
            "name": "cw_sequence",
            "description": "连续操作：一次下发多步，设备端按顺序执行，每步间隔至少 90ms（默认 90ms）。适合打字、连招、进入→点击→返回。",
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
            "description": "把刚刚完成的操作沉淀成 action 脚本（只在反思阶段可用，新建即 unverified）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "snake_case"},
                    "title": {"type": "string"},
                    "scene": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "code": {"type": "string", "description": "完整 python 源码，只能用 cw_script"},
                    "params": {"type": "object"},
                },
                "required": ["id", "title", "scene", "code"],
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
    return {"cw_single": single, "cw_sequence": sequence, "cw_observe": observe,
            "cw_action": action, "cw_ask_user": ask, "cw_keys": keys, "cw_input": input_tool,
            "cw_paste": paste, "cw_write_action": write_action, "cw_update_action": update_action}


CW_TOOL_SCHEMAS = _schemas()
CW_RUNNING_TOOLS = ["cw_observe", "cw_single", "cw_sequence", "cw_input", "cw_keys", "cw_paste",
                    "cw_action", "cw_ask_user", "cw_update_action"]
CW_REFLECTING_TOOLS = ["cw_observe", "cw_write_action", "cw_update_action", "cw_ask_user"]


class CWAgentTools:
    def __init__(self, config, operator, store, session, journal, apps=None):
        self.config = config
        self.operator = operator
        self.store = store
        self.session = session
        self.journal = journal
        self.apps = apps
        self.wda = CWWDA(config)
    def schemas(self, phase):
        names = CW_RUNNING_TOOLS if phase == CW_PHASE_RUNNING else CW_REFLECTING_TOOLS
        return [CW_TOOL_SCHEMAS[name] for name in names if name in CW_TOOL_SCHEMAS]

    def dispatch(self, name, args):
        handler = getattr(self, "_do_" + str(name), None)
        if handler is None:
            return {"text": "未知工具：%s" % name}
        try:
            return handler(args or {})
        except CWProtocolError as exc:
            self.journal.record("tool_error", tool=name, code=exc.code, message=exc.message)
            return {"text": "操作失败（%s）：%s" % (exc.code, exc.message), "error": True}

    def _do_cw_observe(self, args):
        mode = args.get("mode") or "ocr"
        result = self.operator.observe(mode, None, args.get("max_edge"))
        if result.get("mode") == "image":
            screen = result.get("screen") or {}
            pixel = screen.get("pixel") or [0, 0]
            size = result.get("image_size") or []
            if size and size[0]:
                ratio = float(pixel[0]) / float(size[0]) if pixel and pixel[0] else 1.0
                text = ("已截图：发给你的是 %dx%d，坐标基准是原图 %dx%d。"
                        "返回坐标一律用原图像素；按图上位置估的要乘 %.2f。"
                        % (size[0], size[1], pixel[0], pixel[1], ratio))
            else:
                text = "已截图（%sx%s）。" % (pixel[0], pixel[1])
            return {"text": text, "image": result.get("image")}
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

    def _do_cw_keys(self, args):
        text = str(args.get("text") or "")
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
        self.operator.sequence(steps, 60)
        note = ""
        if missing:
            note = "；跳过了 %s" % "".join(sorted(set(missing)))[:20]
        return {"text": "敲了 %d 个键：%s%s" % (len(steps), text[:40], note)}

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

    def _do_cw_write_action(self, args):
        if self.session.phase != CW_PHASE_REFLECTING:
            raise CWProtocolError(CWErrorCode.GUARD, "只有反思阶段可以新建 action")
        manifest = self.store.create({
            "id": args.get("id"), "title": args.get("title"), "scene": args.get("scene"),
            "code": args.get("code"), "steps": args.get("steps") or [],
            "params": args.get("params") or {}, "author": "ai",
        }, self.session.phase)
        self.journal.record("action_created", action_id=manifest.get("id"),
                            title=manifest.get("title"))
        return {"text": "已登记 action %s（未验证）。" % manifest.get("id")}

    def _do_cw_update_action(self, args):
        if self.session.phase not in (CW_PHASE_RUNNING, CW_PHASE_REFLECTING):
            raise CWProtocolError(CWErrorCode.GUARD, "链路未激活")
        manifest = self.store.update(args.get("action_id"), args.get("code"),
                                     args.get("reason"), self.session.phase,
                                     args.get("target") or "main.py")
        self.journal.record("action_updated", action_id=manifest.get("id"),
                            version=manifest.get("version"))
        return {"text": "已更新 action %s，版本 %s，状态回到 unverified。"
                        % (manifest.get("id"), manifest.get("version"))}
