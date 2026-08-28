# -*- coding: utf-8 -*-
# func/toolbox/danmaku/active_sender/active_sender.py
# 弹幕主动发送模块（触发型工具，注册进父级 analysis）
# 流程：开关+冷却检查 → toolbox LLM 拟稿（角色提示词）→ 发弹幕到直播间

import time
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.danmaku.config import TBDanmakuConfig


@singleton
class TBDanmakuActive:
    """弹幕主动发送工具：父级 toolcalls 暴露 danmaku_send 一个工具。

    - 直接发弹幕，不需要目标对象；
    - 内容由 toolbox LLM（内置模型）按角色提示词拟定；
    - 独立开关 + 冷却（类似 napcat active_sender）。
    """

    TOOL_NAME = "danmaku_send"

    # 主动发弹幕冷却时间戳（类变量，所有实例共享，运行时内存态）
    _last_active_send = 0.0

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBDanmakuConfig()
        self._username = ""

    def set_username(self, username: str):
        """注入当前用户（供提示词使用）"""
        self._username = username or ""

    # ==================== 工具 schema ====================
    def build_tools(self) -> List[Dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "在 B站直播间主动发送一条弹幕。适用于：角色想主动和直播间观众互动、"
                    "主动发言、回应弹幕氛围等。内容由角色自己拟定。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "发送弹幕的需求描述，例如：主动和直播间观众打个招呼 / 发一条关于当前游戏的想法",
                        },
                    },
                    "required": ["request"],
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        return self.execute((arguments or {}).get("request", ""), self._username)

    # ==================== 执行 ====================
    def execute(self, request: str, username: str = "") -> str:
        if not request:
            return "发送失败：缺少弹幕需求描述"
        # 开关 + 冷却
        err = self.check_active_send()
        if err:
            return err
        text = self._plan(request, username)
        if not text:
            return "AI 未能拟定弹幕内容"

        # 发弹幕
        try:
            from func.toolbox.danmaku.web.web_client import TBDanmakuWeb
            ok = TBDanmakuWeb().send_danmaku_sync(text)
        except Exception:
            self.log.exception("发弹幕异常")
            ok = False
        if ok:
            TBDanmakuActive.mark_active_send()
            return f"已发送弹幕：{text}"
        return "弹幕发送失败（可能未启用弹幕模块或未配置 bili_jct）"

    def check_active_send(self) -> str:
        """检查主动发弹幕是否允许（开关 + 冷却），返回错误信息（空串表示允许）"""
        if not self.config.active_send_enabled:
            return "主动发弹幕未启用（danmaku.active_send.enabled=false）"
        cooldown = int(self.config.active_send_cooldown or 0)
        if cooldown > 0:
            elapsed = time.time() - TBDanmakuActive._last_active_send
            if elapsed < cooldown:
                return f"主动发弹幕冷却中，还需 {int(cooldown - elapsed)} 秒"
        return ""

    @classmethod
    def mark_active_send(cls):
        """记录本次主动发弹幕时间（用于冷却）"""
        cls._last_active_send = time.time()

    # ==================== LLM 拟稿 ====================
    def _plan(self, request: str, username: str = "") -> str:
        llm = self._llm()
        if llm is None or not llm.client:
            self.log.error("[DanmakuActive] toolbox LLM 不可用")
            return ""
        system_prompt = self._system_prompt(username, request)
        resp = llm.chat([
            {"role": "system", "content": (
                f"{system_prompt}\n\n"
                f"请以你的角色身份，根据需求拟定一条发送到 B站直播间的弹幕。"
                f"弹幕要口语化、自然，控制在 30 字以内，直接输出弹幕内容本身。"
            )},
            {"role": "user", "content": f"需求：{request}"},
        ])
        content = ""
        try:
            if resp and resp.choices:
                content = (resp.choices[0].message.content or "").strip()
        except Exception:
            self.log.exception("[DanmakuActive] 解析 LLM 回复失败")
        return content

    def _system_prompt(self, username: str, current_message: str) -> str:
        """获取角色人设提示词（前置词+角色卡+价值观+后置词，无用户记忆）"""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            return TBoxGetPrompt().get_tool_prompt(username, current_message) or ""
        except Exception:
            return ""

    def _llm(self):
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
