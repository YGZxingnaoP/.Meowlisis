# -*- coding: utf-8 -*-
# func/catpaws/prompt.py
# 启动载荷组装：角色卡提示词 + 短期记忆 + 用户原话，一并交给 CatPaws 服务端
from func.catpaws.config import CWCatPawsConfig
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class CWCatPawsPrompt:
    """把 pipeline 的角色提示词与短期记忆打包成服务端 /cw/start 载荷"""

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = config or CWCatPawsConfig()

    def build(self, goal, meowid, text):
        """组装 {goal, system_prompt, memory, user_message, meowid}"""
        return {
            "goal": str(goal or "").strip(),
            "system_prompt": self.system_prompt(meowid, text),
            "memory": self.memory(text),
            "user_message": str(text or "").strip(),
            "meowid": str(meowid or "").strip(),
        }

    def system_prompt(self, meowid, current_message=""):
        """角色卡系统提示词（pipeline/system_prompt 桥接）"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_system_prompt(meowid, current_message) or ""
        except Exception:
            self.log.exception("[CatPaws] 读取系统提示词失败")
            return ""

    def memory(self, current_text=""):
        """短期记忆（pipeline/public_short_memory 桥接），按配置轮数取尾部

        触发前那条用户消息已经写进短期记忆了，这里把它剔掉，避免服务端把它
        当成「历史里说过一次」再叠加一次当前用户消息。
        """
        rounds = int(self.config.short_rounds or 0)
        if rounds <= 0:
            return []
        try:
            from func.pipeline.short_memory import ShortMemory
            items = ShortMemory().load()
        except Exception:
            self.log.exception("[CatPaws] 读取短期记忆失败")
            return []
        usable = [item for item in items if str(item.get("role") or "") in ("user", "assistant")]
        tail = usable[-rounds * 2:]
        body = str(current_text or "").strip()
        if body and tail and tail[-1].get("role") == "user" \
                and str(tail[-1].get("content") or "").strip() == body:
            tail = tail[:-1]
        return tail
