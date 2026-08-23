# -*- coding: utf-8 -*-
# func/toolbox/meowvision/get_prompt.py
# MeowVision 提示词获取：获取角色提示词与用户当前消息

from func.pipeline.system_prompt import SystemPromptBridge


class TBVisionGetPrompt:
    """获取视觉理解所需的系统提示词（角色身份）与用户当前消息"""

    def __init__(self):
        self.bridge = SystemPromptBridge()

    def get_system_prompt(self, username=None, current_message: str = "",
                          need_description: bool = True) -> str:
        """获取视觉专用系统提示词：角色完整提示词 + 看图指令。
        need_description=True 时，要求模型先输出 50~80 字纯文本图片描述，再输出角色回复；
        need_description=False 时（角色自己截图），只要求输出角色回复。
        """
        base = ""
        try:
            base = self.bridge.get_system_prompt(username, current_message)
        except Exception:
            base = ""

        if need_description:
            guide = (
                "你现在看到了一张或多张图片。必须调用 reply_image 工具，"
                "在 description 字段输出30~50字的图片描述，在 reply 字段以角色身份"
                "自然、口语化、简短地回复用户，10~30字。"
            )
        else:
            guide = (
                "你现在看到了屏幕/图片内容。你必须以你角色自己的第一人称口吻，"
                "像平时聊天一样自然地吐槽、评价、关心用户，口语化、简短，20~40字。\n"
                "【严格禁止】禁止输出代码分析、技术报告、markdown 列表、操作说明、"
                "使用指南等机械内容；禁止用第三人称或助手口吻。"
            )

        if base:
            return f"{base}\n\n{guide}"
        return guide

    @staticmethod
    def get_user_message(current_message: str = "") -> str:
        """获取用户当前消息（看图时用户说的话）"""
        return (current_message or "").strip()
