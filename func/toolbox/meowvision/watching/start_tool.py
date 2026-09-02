# -*- coding: utf-8 -*-
# func/toolbox/meowvision/watching/start_tool.py
# Watching 启动决策：深度思考判断是否长期观察 → 强制工具调用收集配置 → 启动循环

import json
import re
from typing import Optional

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
    def decide_and_start(self, username: str, user_instruction: str,
                         front_window: Optional[dict] = None) -> Optional[dict]:
        """判断是否需要 watching，需要则收集配置并启动循环。返回配置 dict 或 None（不 watching）。

        :param front_window: 首帧截图时抓到的前台窗口候选 {hwnd,title,...}（可空）。
            仅作为高置信候选置顶展示，是否绑定仍由 LLM 结合用户指令语义确认。
        """
        instruction = (user_instruction or "").strip()
        if not instruction:
            return None

        # 阶段1：深度思考判断（语义确认①：用户是否真要长期观察）
        need = self._decide_watching(username, instruction)
        if not need:
            return None

        # 阶段2：收集配置（可能 excuse 追问一轮；前台候选置顶供语义选窗）
        config = self._collect_with_excuse(username, instruction, front_window=front_window)
        if not config:
            return None

        # 最终校验：关键参数仍缺失（如 duration 仍为0）则放弃，避免启动即超时
        missing = self._missing_keys(config)
        if missing:
            self.log.warning(f"[Watching] 兜底路径仍缺失参数: {missing}，放弃启动")
            return None

        return self._launch(config, username, instruction)

    def _launch(self, config: dict, username: str, instruction: str) -> Optional[dict]:
        """公共启动流程：窗口绑定 → 落盘 → 启动循环（由 decide_and_start 深度思考入口调用）"""
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
    def _build_windows(self, front_window: Optional[dict] = None) -> list:
        """构造供 LLM 选择的窗口列表：前台候选置顶并标注【当前前台】。

        前台窗口只是高置信候选——LLM 仍需结合用户指令语义判断它是否用户所指，
        语义明显不符时从完整列表中选择其它窗口，避免盲目绑定。
        """
        windows = self.window_list.list_windows()
        if front_window and front_window.get("title"):
            front = dict(front_window)
            front["is_foreground"] = True
            windows = [w for w in windows if w.get("hwnd") != front.get("hwnd")]
            windows.insert(0, front)
        return windows

    def _collect_with_excuse(self, username: str, instruction: str,
                             front_window: Optional[dict] = None) -> Optional[dict]:
        """收集配置，不确定则 excuse 追问一轮后重新收集"""
        windows = self._build_windows(front_window)
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
        windows = self._build_windows(front_window)
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
                f"请调用 start_watching 工具。窗口选择说明：\n"
                f"- 列表中标注【当前前台】的窗口是用户此刻正在操作的窗口，"
                f"通常就是用户希望观察的窗口，请优先选择它；\n"
                f"- 但如果它与用户指令语义明显不符（例如用户说要观察游戏，"
                f"前台却是聊天窗口），请从列表中选择符合语义的其它窗口。\n"
                f"参数约束：\n"
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
            tag = "【当前前台】" if w.get("is_foreground") else ""
            lines.append(f"{i}. {tag}标题「{w.get('title', '')}」 进程「{proc}」")
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
