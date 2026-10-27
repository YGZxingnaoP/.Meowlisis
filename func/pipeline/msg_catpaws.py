# -*- coding: utf-8 -*-
# func/pipeline/msg_catpaws.py
# msg / sensevoice / 弹幕 → catpaws 桥接：命中触发或正在操作手机时拦截
from func.log.default_log import DefaultLog


class MsgCatPawsBridge:
    """把 msg / chat / 语音识别的文本转给 catpaws 模块

    - 命中触发词或意图判断：启动手机操作链路并返回 True（上层跳过主 LLM 回复）；
    - 链路进行中：停止词立即停，其余作为补充指令送达并返回 True；
    - 未命中：返回 False（上层继续原链路）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_catpaws(self, text, meowid="", source="msg"):
        """返回 True 表示已被 catpaws 接管"""
        if not text or not str(text).strip():
            return False
        try:
            from func.catpaws.core import CWCatPawsCore
            return bool(CWCatPawsCore().receive(str(text).strip(), meowid, source))
        except Exception:
            self.log.exception("msg → catpaws 处理异常")
            return False
