# -*- coding: utf-8 -*-
# func/toolbox/meowvision/watching/start_tool.py
# Watching 启动决策：深度思考判断是否长期观察 → 强制工具调用收集配置 → 启动循环

import json
import re
from typing import Dict, Optional

from func.log.default_log import DefaultLog
from func.toolbox.meowvision.watching.config import TBWatchingConfig
from func.toolbox.meowvision.watching.window import TBWindowList


class TBWatchingStart:
    """Watching 启动器：AI 决策是否开启长期观察屏幕，并收集配置后启动循环。

    流程：
    1. 阶段1（深度思考开启，无工具）：判断用户是否有「陪打游戏 / 长期观察屏幕」意图；
    2. 若需要 watching：获取当前窗口列表；
    3. 阶段2（强制 tool_choice，关闭思考）：收集截屏间隔/区域/变化检测/时长/窗口/前置词；
    4. 不确定或关键参数缺失 → 发起 excuse 追问；
    5. 确定后校验窗口绑定，启动 TBWatchingLoop。
    """

    TOOL_NAME = "start_watching"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBWatchingConfig()
        self.window_list = TBWindowList()

    # ==================== 主入口 ====================
    def decide_and_start(self, username: str, user_instruction: str) -> Optional[dict]:
        """判断是否需要 watching，需要则收集配置并启动循环。返回配置 dict 或 None（不 watching）。"""
        instruction = (user_instruction or "").strip()
        if not instruction:
            return None

        # 阶段1：深度思考判断
        need = self._decide_watching(username, instruction)
        if not need:
            return None

        # 阶段2：收集配置（可能 excuse 追问一轮）
        config = self._collect_with_excuse(username, instruction)
        if not config:
            return None

        # 最终校验：关键参数仍缺失（如 duration 仍为0）则放弃，避免启动即超时
        missing = self._missing_keys(config)
        if missing:
            self.log.warning(f"[Watching] 兜底路径仍缺失参数: {missing}，放弃启动")
            return None

        return self._launch(config, username, instruction)

    # ==================== 参数直启（use_vision 合并 watching 后的主入口） ====================
    def start_with_params(self, args: dict, username: str, instruction: str) -> Optional[dict]:
        """用 AI 填写的循环参数直接启动 watching（跳过阶段1深度思考）。

        - 参数齐全：直接校验并启动；
        - 缺 duration/window_title 等关键参数：强制追问用户补齐（最多2轮）；
        - 参数几乎全空（无窗口、无时长）：回退 decide_and_start（深度思考兜底）。
        """
        config = self._normalize(args or {})

        # 参数几乎全空 → 回退旧深度思考路径兜底
        if not config.get("window_title") and int(config.get("duration") or 0) <= 0:
            self.log.info("[Watching] watching=true 但循环参数为空，回退深度思考兜底")
            return self.decide_and_start(username, instruction)

        windows = self.window_list.list_windows()
        # 强制补齐缺失项（最多2轮追问）
        for _ in range(2):
            missing = self._missing_keys(config)
            if not missing:
                break
            question = self._build_question(missing)
            self.log.info(f"[Watching] 参数缺失，追问用户: {question}")
            from func.toolbox.excuse import TBExcuse
            answer = TBExcuse().ask(question, username=username)
            if not answer:
                self.log.warning("[Watching] 追问无应答，无法补齐缺失参数")
                break
            config = self._merge_answer(config, answer, windows)

        # 仍有缺失 → 放弃启动
        missing = self._missing_keys(config)
        if missing:
            self.log.warning(f"[Watching] 追问后仍缺失参数: {missing}，放弃启动")
            return None

        return self._launch(config, username, instruction)

    def _launch(self, config: dict, username: str, instruction: str) -> Optional[dict]:
        """公共启动流程：窗口绑定 → 落盘 → 启动循环（参数直启与深度思考兜底两个入口共用）"""
        # 窗口绑定
        hwnd = self._resolve_hwnd(config)
        if not hwnd:
            self.log.warning("[Watching] 窗口绑定失败，走 LLM 告知用户")
            self._notify_window_bind_fail(username, config)
            return None

        config["hwnd"] = hwnd
        config["username"] = username
        config["user_instruction"] = instruction

        # 落盘会话配置
        self.config.save_session(config)

        # 启动循环
        from func.toolbox.meowvision.watching.vision_loop import TBWatchingLoop
        loop = TBWatchingLoop()
        if loop.is_running():
            self.log.warning("[Watching] 已有观察循环在运行，先停止旧的")
            loop.stop()
        ok = loop.start(config)
        if not ok:
            self.config.clear_session()
            return None

        self.log.info(f"[Watching] 已启动：{config.get('window_title')}，"
                      f"间隔 {config.get('interval')}s，时长 {config.get('duration')}s")
        return config

    @staticmethod
    def _build_question(missing: list) -> str:
        """把缺失参数转成对用户的中文追问"""
        parts = []
        if "window_title" in missing:
            parts.append("你想让我观察哪个窗口/游戏？")
        if "duration" in missing:
            parts.append("你想让我持续观察多久（如 30分钟 / 1小时）？")
        if "bbox" in missing:
            parts.append("你想让我观察屏幕的哪个区域（坐标）？")
        return "；".join(parts) if parts else ""

    def _merge_answer(self, config: dict, answer: str, windows: list) -> dict:
        """从用户回答中解析并补全缺失参数（不重新调 LLM）"""
        answer = (answer or "").strip()
        # 时长解析
        if int(config.get("duration") or 0) <= 0:
            secs = self._parse_duration(answer)
            if secs:
                config["duration"] = self.config.clamp_duration(secs)
        # 窗口解析（从窗口列表标题匹配回答中的关键词）
        if not config.get("window_title"):
            title = self._match_window(answer, windows)
            if title:
                config["window_title"] = title
        # bbox 解析：能解析则补全，解析失败回退全屏（避免 bbox 缺失死路）
        if config.get("region_type") == "bbox" and not config.get("bbox"):
            bbox = self._parse_bbox_answer(answer)
            if bbox:
                config["bbox"] = bbox
            else:
                config["region_type"] = "fullscreen"
                config["bbox"] = None
        return config

    @staticmethod
    def _parse_bbox_answer(text: str) -> Optional[list]:
        """从回答解析屏幕坐标 bbox [left, top, right, bottom]；解析失败返回 None"""
        nums = re.findall(r"\d+", text or "")
        if len(nums) >= 4:
            try:
                return [int(v) for v in nums[:4]]
            except (TypeError, ValueError):
                return None
        return None

    # 中文数字 → 数值（用于时长解析）
    _CN_NUM = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
               '六': 6, '七': 7, '八': 8, '九': 9, '半': 0.5, '十': 10}

    @classmethod
    def _parse_duration(cls, text: str) -> int:
        """从文本解析时长（秒），支持阿拉伯/中文数字 + 小时/分钟/秒"""
        text = (text or "").strip()
        if not text:
            return 0
        # 特判：一个半小时 / 半小时
        if "一个半小时" in text:
            return 5400
        if "半小时" in text:
            return 1800
        # 阿拉伯数字 + 单位
        m = re.search(r"(\d+)\s*(小时|分钟|分|秒|h|m|s)", text)
        if m:
            num = int(m.group(1))
            unit = m.group(2)
            if unit in ("小时", "h"):
                return num * 3600
            if unit in ("分钟", "分", "m"):
                return num * 60
            return num
        # 中文数字 + 单位
        m = re.search(r"([一两二三四五六七八九十半])\s*(小时|分钟|分|秒)", text)
        if m:
            num = cls._CN_NUM.get(m.group(1), 1)
            unit = m.group(2)
            if unit == "小时":
                return int(num * 3600)
            if unit in ("分钟", "分"):
                return int(num * 60)
            return int(num)
        # 纯数字（默认秒）
        m = re.search(r"(\d+)", text)
        if m:
            return int(m.group(1))
        return 0

    @classmethod
    def _match_window(cls, text: str, windows: list) -> str:
        """在窗口列表里找与回答文本匹配的窗口标题

        - 回答包含窗口标题（子串）优先；
        - 再按回答中的词（2字以上片段）匹配标题，英文/数字片段不区分大小写。
        """
        text = (text or "").strip()
        if not text or not windows:
            return ""
        # 1) 回答包含窗口标题（子串）
        for w in windows:
            title = w.get("title") or ""
            if title and title in text:
                return title
        # 2) 标题包含回答中的词（按空白/标点切分，取2字以上片段）
        tokens = [t for t in re.split(r"[\s，。！？、,.!?；;：:\"'（）()\[\]【】]+", text)
                  if len(t.strip()) >= 2]
        for t in tokens:
            tl = t.lower()
            for w in windows:
                title = w.get("title") or ""
                if not title:
                    continue
                # 整体子串（英文忽略大小写）
                if tl in title.lower():
                    return title
                # token 内嵌英文/数字片段（如 "mC的窗口" 提取 "mc"）与标题匹配
                for sub in re.findall(r"[a-zA-Z0-9]+", t):
                    if sub.lower() in title.lower():
                        return title
        return ""

    # ==================== 阶段1：深度思考判断 ====================
    def _decide_watching(self, username: str, instruction: str) -> bool:
        """深度思考判断是否需要长期观察（开启 thinking，无工具）"""
        llm = self._llm()
        if llm is None or not llm.client:
            self.log.warning("[Watching] LLM 不可用，无法判断，默认不开启")
            return False

        persona = self._persona(username, instruction)
        messages = [
            {"role": "system", "content": (
                f"{persona}\n\n"
                f"你需要判断用户当前消息的意图。"
            )},
            {"role": "user", "content": (
                f"用户说：{instruction}\n\n"
                f"请深度思考：用户是否有「让你陪他打游戏」或「让你陪他看屏幕、长期观察屏幕」的需求？\n"
                f"注意区分：如果只是让你「看一眼屏幕 / 截个图」（一次性），则不需要长期观察。\n"
                f"最终只输出一个 JSON，不要输出其他内容："
                f'{{"need_watching": true或false, "reason": "简短理由"}}'
            )},
        ]
        resp = llm.chat(messages, enable_thinking=True)
        data = self._extract_json(resp)
        if not data:
            self.log.warning("[Watching] 阶段1 未解析出 JSON，默认不开启")
            return False
        need = bool(data.get("need_watching"))
        self.log.info(f"[Watching] 阶段1 判断 need_watching={need}, reason={data.get('reason', '')}")
        return need

    # ==================== 阶段2：收集配置 ====================
    def _collect_with_excuse(self, username: str, instruction: str) -> Optional[dict]:
        """收集配置，不确定则 excuse 追问一轮后重新收集"""
        windows = self.window_list.list_windows()
        config = self._collect(username, instruction, windows)
        if not config:
            return None

        # 检查不确定/缺失项
        question = self._confirm_question(config)
        if not question:
            return config

        # 发起 excuse 追问
        from func.toolbox.excuse import TBExcuse
        answer = TBExcuse().ask(question, username=username)
        if not answer:
            self.log.warning("[Watching] excuse 未获回答，按现有配置继续或终止")
            if self._missing_keys(config):
                return None
            return config

        # 合并回答后重新收集一轮
        new_instruction = f"{instruction}；用户补充：{answer}"
        windows = self.window_list.list_windows()
        config2 = self._collect(username, new_instruction, windows)
        return config2 if config2 else config

    def _collect(self, username: str, instruction: str, windows: list) -> Optional[dict]:
        """强制 tool_choice 收集配置（关闭思考）"""
        llm = self._llm()
        if llm is None or not llm.client:
            self.log.warning("[Watching] LLM 不可用，无法收集配置")
            return None

        persona = self._persona(username, instruction)
        window_lines = self._format_windows(windows)
        messages = [
            {"role": "system", "content": (
                f"{persona}\n\n"
                f"用户希望开启「长期观察屏幕」功能，你需要调用 start_watching 工具填写配置。"
            )},
            {"role": "user", "content": (
                f"用户指令：{instruction}\n\n"
                f"当前可见窗口列表（用于绑定游戏窗口）：\n{window_lines}\n\n"
                f"请调用 start_watching 工具。参数约束：\n"
                f"- interval：截屏间隔秒数，范围 20~300；\n"
                f"- region_type：截屏区域，fullscreen(全屏) 或 bbox(坐标)；\n"
                f"- bbox：region_type=bbox 时必填，屏幕绝对坐标 [left, top, right, bottom]；\n"
                f"- need_change_check：是否开启前后画面变化检测。仅当判断游戏界面变化大"
                f"（如第一人称射击、赛车、动作游戏）时填 true，否则 false；\n"
                f"- duration：持续时间秒数，范围 300~18000（5分钟~5小时），必须从用户指令里提取，"
                f"无法确定则留空（系统会追问用户）；\n"
                f"- window_title：从窗口列表里选择要绑定的游戏窗口标题；\n"
                f"- front_note：游戏场景说明（谁在玩什么、第一/第三人称、画面特征），用于提示词；\n"
                f"- uncertain：如果你对某项配置不确定、需要向用户确认，把要问的问题写在这里，否则留空。"
            )},
        ]
        resp = llm.chat(
            messages,
            tools=self.build_tools(),
            tool_choice=self.build_tool_choice(),
            enable_thinking=False,
        )
        if not resp or not resp.choices:
            return None
        msg = resp.choices[0].message
        for tc in (msg.tool_calls or []):
            if tc.function.name == self.TOOL_NAME:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    self.log.exception("[Watching] 解析 start_watching 参数失败")
                    return None
                return self._normalize(args)
        return None

    # ==================== 工具 schema ====================
    def build_tools(self) -> list:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "启动长期观察屏幕的配置（截屏频率、区域、变化检测、时长、窗口绑定、游戏场景说明）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interval": {"type": "integer", "description": "截屏间隔秒数，20~120"},
                        "region_type": {"type": "string", "enum": ["fullscreen", "bbox"]},
                        "bbox": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "屏幕绝对坐标 [left, top, right, bottom]，region_type=bbox 时必填",
                        },
                        "need_change_check": {"type": "boolean", "description": "是否开启前后画面变化检测"},
                        "duration": {"type": "integer", "description": "持续时间秒数，300~18000，不确定填0"},
                        "window_title": {"type": "string", "description": "绑定的游戏窗口标题"},
                        "front_note": {"type": "string", "description": "游戏场景说明"},
                        "uncertain": {"type": "string", "description": "不确定需询问用户的问题，无则留空"},
                    },
                    "required": ["interval", "region_type", "need_change_check", "duration", "window_title"],
                },
            },
        }]

    def build_tool_choice(self) -> dict:
        return {"type": "function", "function": {"name": self.TOOL_NAME}}

    # ==================== 内部工具 ====================
    def _normalize(self, args: dict) -> dict:
        """归一化 AI 输出，钳制参数边界（duration=0 表示不确定，保持 0）"""
        raw_duration = args.get("duration")
        try:
            duration = int(raw_duration) if raw_duration is not None else 0
        except (TypeError, ValueError):
            duration = 0
        if duration > 0:
            duration = self.config.clamp_duration(duration)
        return {
            "interval": self.config.clamp_interval(args.get("interval")),
            "region_type": str(args.get("region_type") or "fullscreen").strip(),
            "bbox": self._parse_bbox(args.get("bbox")),
            "need_change_check": str(args.get("need_change_check", "")).strip().lower() in ("true", "1"),
            "duration": duration,
            "window_title": str(args.get("window_title") or "").strip(),
            "front_note": str(args.get("front_note") or "").strip(),
            "uncertain": str(args.get("uncertain") or "").strip(),
        }

    @staticmethod
    def _parse_bbox(bbox) -> Optional[list]:
        """解析 bbox 为 [l,t,r,b] 整数列表，非法返回 None"""
        if not isinstance(bbox, (list, tuple)):
            return None
        try:
            vals = [int(v) for v in bbox]
        except (TypeError, ValueError):
            return None
        if len(vals) < 4:
            return None
        return vals[:4]

    @staticmethod
    def _missing_keys(config: dict) -> list:
        """返回缺失的关键参数名列表（duration 缺失或为0视为缺失，需强制追问时长）"""
        missing = []
        if not config.get("window_title"):
            missing.append("window_title")
        if int(config.get("duration") or 0) <= 0:
            missing.append("duration")
        if config.get("region_type") == "bbox" and not config.get("bbox"):
            missing.append("bbox")
        return missing

    @classmethod
    def _confirm_question(cls, config: dict) -> str:
        """判断是否需要向用户追问，返回要问的问题（无需追问返回空串）"""
        uncertain = str(config.get("uncertain") or "").strip()
        if uncertain:
            return uncertain
        if not config.get("window_title"):
            return "你想让我观察哪个游戏窗口？"
        if config.get("region_type") == "bbox" and not config.get("bbox"):
            return "你想让我观察屏幕的哪个区域？"
        if int(config.get("duration") or 0) <= 0:
            return "你想让我陪你观察多久呢？"
        return ""

    def _resolve_hwnd(self, config: dict) -> Optional[int]:
        """按标题解析窗口句柄；失败返回 None"""
        title = config.get("window_title", "")
        if not title:
            return None
        return self.window_list.find_hwnd(title)

    def _notify_window_bind_fail(self, username: str, config: dict):
        """窗口绑定失败：走 LLM 告知用户（不静默失败）"""
        try:
            from func.pipeline.toolbox_llm import ToolboxLLMBridge
            title = config.get("window_title", "")
            text = f"你想看的游戏窗口「{title}」没有找到，可能游戏还没打开"
            ToolboxLLMBridge().send_to_llm(text, username or "用户")
        except Exception:
            self.log.exception("[Watching] 窗口绑定失败通知异常")

    def _format_windows(self, windows: list) -> str:
        if not windows:
            return "（未获取到可见窗口）"
        lines = []
        for i, w in enumerate(windows, 1):
            proc = w.get("process") or "?"
            lines.append(f"{i}. 标题「{w.get('title', '')}」 进程「{proc}」")
        return "\n".join(lines)

    @staticmethod
    def _extract_json(resp) -> Optional[dict]:
        """从 LLM 响应 content 提取 JSON"""
        if not resp or not resp.choices:
            return None
        try:
            content = resp.choices[0].message.content or ""
        except Exception:
            return None
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    @staticmethod
    def _persona(username: str, current_message: str) -> str:
        """角色人设提示词（决策场景，不含用户记忆/摘要）"""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            return TBoxGetPrompt().get_tool_prompt(username, current_message) or ""
        except Exception:
            return ""

    @staticmethod
    def _llm():
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(cfg)
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
