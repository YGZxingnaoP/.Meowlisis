# -*- coding: utf-8 -*-
# func/toolbox/meowvision/vision_core.py
# MeowVision 核心：视觉模块对外汇总入口（触发型工具）
# 职责：传输图片与消息 → 获取图片描述与角色回复 → 记录短期/长期记忆 → 回传 toolbox_core 转发 TTS

import uuid
from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.pipeline.short_memory import ShortMemory
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.toolbox.meowvision.config import TBVisionConfig
from func.toolbox.meowvision.get_response import TBVisionGetResponse


@singleton
class TBVisionCore:
    """MeowVision 核心入口：同时作为父级 toolcalls 的触发型工具对象

    - 父级 AI 决策调用 use_vision 后，此处读取图片并完成视觉回复全链路。
    - image_handle 工具（截图/裁切/编码）执行后把图片缓存到本实例，供 use_vision 使用。
    - process()：看图 + 写记忆（短期/长期），返回 {description, reply}，不做 TTS/发送。
    - run()：主链路专用，在 process 后回传 TTS 并清空缓存（reply 不含描述）。
    - napcat 链路复用 process()，自行决定如何发送 reply（发 QQ）。
    """

    TOOL_NAME = "use_vision"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBVisionConfig()
        self.get_response = TBVisionGetResponse()
        self.short_memory = ShortMemory()
        self.ltmem = MeowLLMLtMemBridge()
        # 当前用户（由 analysis.dispatch 注入）
        self._username = ""
        # image_handle 工具产生的待发送图片缓存
        self._images: List[str] = []
        # 回传 toolbox_core 的转发回调（由 toolbox_core 注入）
        self._reply_callback = None

    # ==================== 上下文与缓存 ====================
    def set_reply_callback(self, callback):
        """注入回传回调（由 toolbox_core 注入，视觉回复经 toolbox_core 转发 TTS）"""
        self._reply_callback = callback

    def set_username(self, username: str):
        """注入当前用户（供记忆记录使用，由 analysis.dispatch 调用）"""
        self._username = username or ""

    def add_image(self, path: str, replace: bool = False):
        """缓存一张图片（replace=True 时清空旧缓存，作为新的唯一待发送图片）"""
        if replace:
            self._images = []
        if path and path not in self._images:
            self._images.append(path)

    def clear_images(self):
        """清空图片缓存"""
        self._images = []

    def get_images(self) -> List[str]:
        """获取当前缓存的图片列表"""
        return list(self._images)

    # ==================== 工具 schema ====================
    def build_tools(self) -> List[Dict]:
        """构建 use_vision 触发工具 schema（供父级 toolcalls 展开注册）

        统一「先看第一眼」：调用后先截图/看图并回复一次；
        若用户要求长期盯屏（陪打游戏/长期观察/定期汇报），由工具内部自动升级持续观察，
        ——调用方无需填写任何循环参数。
        """
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "看屏幕/看图片并回复。只要用户表达看屏幕/看画面/看图片/截图意图，"
                    "或你正在关注当前屏幕内容即可调用；无需任何参数。"
                    "若用户希望长期盯屏（陪我打游戏/长期观察/定期汇报画面等），"
                    "工具内部会自动启动持续观察，调用方无需填写任何循环参数。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "一次性查看的图片路径或 url 列表（可空，空则使用缓存图片或自动截图）",
                        },
                        "user_message": {
                            "type": "string",
                            "description": "用户当前消息/看图指令（可空）",
                        },
                    },
                },
            },
        }]

    # 持续观察意图弱信号（命中只是"尝试升级"的提示，是否真启动由 watching 内部深度思考最终确认）
    SUSTAIN_HINT = (
        "长期", "持续", "一直", "盯着", "盯屏幕", "盯着我", "守着", "监视",
        "观察我", "观察屏幕", "观察画面", "陪我打", "陪我玩", "陪我看", "陪打",
        "看着我打", "看着我玩", "看我打", "看我玩", "看我一会", "等我打完",
        "定期汇报", "汇报我", "全程", "帮我看着",
    )

    def _has_sustain_intent(self, text: str) -> bool:
        """用户消息是否含持续观察意图的弱信号（子串匹配，零成本）"""
        return any(k in (text or "") for k in self.SUSTAIN_HINT)

    # ==================== 执行分发 ====================
    def dispatch(self, name: str, arguments: Dict) -> str:
        """按工具名执行（父级 toolcalls 调用入口）

        统一「先看第一眼」：
        1. 先做一次普通看屏（截图→评述→回复），无论最终是否长期，都先给用户即时反馈；
        2. 若本次是盯屏场景（无外部图片）且用户消息含持续观察意图弱信号，
           再尝试升级为长期观察(watching)——由 watching 内部结合【前台窗口候选】
           与用户指令做语义确认后启动；确认不通过则保持一次性，不影响已完成的看屏。
        """
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        arguments = arguments or {}
        image_paths = arguments.get("image_paths") or []
        user_message = arguments.get("user_message") or ""
        username = self._username or "用户"

        # 第1步：先看第一眼（watching 也先看一次再决定是否长期）
        # 传了外部图片路径 → 需要图片描述；用缓存（角色自己截图）→ 不需要描述
        need_description = bool(image_paths)
        reply = self.run(image_paths, user_message, username, need_description)

        # 第2步：盯屏场景 + 持续意图弱信号 + watching 开启 → 尝试升级长期观察
        if not image_paths and self._has_sustain_intent(user_message):
            try:
                from func.toolbox.meowvision.watching.config import TBWatchingConfig
                if TBWatchingConfig().enabled:
                    from func.toolbox.meowvision.watching.start_tool import TBWatchingStart
                    from func.toolbox.meowvision.watching.window import TBWindowList
                    # 首帧前台窗口作为高置信候选（是否绑定由 watching 内部语义确认）
                    front = TBWindowList().get_foreground()
                    watching_config = TBWatchingStart().decide_and_start(
                        username, user_message, front_window=front
                    )
                    if watching_config:
                        title = watching_config.get("window_title", "")
                        self.log.info(f"[MeowVision] 已启动长期观察: 窗口={title}")
                        return (reply or "") + f"（已启动长期观察：{title}）"
            except Exception:
                self.log.exception("[MeowVision] watching 升级异常，保持一次性看屏")

        return reply

    # ==================== 核心流程 ====================
    def run(self, image_paths: List[str], user_message: str, username: str,
            need_description: bool = True) -> str:
        """主链路：看图 → 写记忆 → 回传 TTS（只用 reply）→ 清空缓存，返回角色回复

        无外部图片、无缓存图片时，自动截屏兜底（如「看我打游戏」场景）。
        """
        images = [p for p in (image_paths or []) if p]
        if not images:
            images = self.get_images()
        if not images:
            # 自动截图兜底
            self.log.info("MeowVision 无缓存图片，自动截屏")
            from func.toolbox.meowvision.image_handle.capture import TBScreenCapture
            cap_result = TBScreenCapture().capture()
            images = self.get_images()
            if not images:
                self.log.warning("MeowVision 自动截屏失败")
                return "错误：没有可查看的图片"

        result = self.process(images, user_message, username, need_description)
        reply = (result.get("reply") or "").strip()
        if not reply:
            self.log.warning("MeowVision 视觉回复为空")
            return "错误：视觉模型无回复"

        # 回传 toolbox_core，由其通过 pipeline 转发 TTS 合成（只用 reply，整段，不分段）
        traceid = str(uuid.uuid4())
        if self._reply_callback:
            try:
                self._reply_callback(reply)
            except Exception:
                self.log.exception("MeowVision 回传 toolbox_core 转发 TTS 失败")
        else:
            self.log.warning("MeowVision 未设置 toolbox_core 转发回调，回复未送 TTS")

        # 清空本次图片缓存
        self.clear_images()

        self.log.info(f"[{traceid}][MeowVision视觉回复]{reply[:50]}...")
        return reply

    def process(self, images: List[str], user_message: str, username: str,
                need_description: bool = True, write_memory: bool = True,
                history_messages: Optional[List[dict]] = None) -> Dict[str, str]:
        """看图 + 写记忆（短期/长期），返回 {description, reply}。

        - 不 TTS、不清缓存、不发送（由调用方决定：主链路 run 回传 TTS，napcat 链路发 QQ）。
        - history_messages：短期记忆上下文（[{role, content}]），传给视觉模型作为对话背景。
        - 用户发的图（need_description=True）：短期记忆 user=【图片】+描述 + assistant=回复；
          长期记忆图片描述 user 身份（无具体用户名）+ 回复 AI 身份。
        - 角色自己截图（need_description=False）：只存 assistant=回复。
        - write_memory=False：只看图，不写任何记忆（如幻梦机器人发的图）。
        """
        result = self.get_response.analyze(
            images, user_message, username, need_description, history_messages
        )
        description = (result.get("description") or "").strip()
        reply = (result.get("reply") or "").strip()
        if not reply:
            return {"description": "", "reply": ""}

        if write_memory:
            max_rounds = self._max_rounds()

            # 1. 短期记忆（type=vision_response）
            if need_description and description:
                self.short_memory.save(
                    {"role": "user", "content": f"【图片】{description}", "type": "vision_response"},
                    max_rounds,
                )
            self.short_memory.save(
                {"role": "assistant", "content": reply, "type": "vision_response"},
                max_rounds,
            )

            # 2. 长期记忆（【图片】前缀由 pipeline 桥接统一补丁，这里传纯描述）
            if need_description and description:
                try:
                    self.ltmem.record_image_message(description)
                except Exception:
                    self.log.exception("MeowVision 记录图片描述长期记忆失败")
            try:
                from func.config.app_config import AppConfig
                self.ltmem.record_ai_message(username, AppConfig().ai_name, reply)
            except Exception:
                self.log.exception("MeowVision 记录长期记忆失败")

        return {"description": description, "reply": reply}

    @staticmethod
    def _max_rounds() -> int:
        """vision_response 复用 llm 短期记忆轮数（与主动回复一致，无独立配置）"""
        from func.llm.config import LLMConfig
        return LLMConfig().short_term_rounds
