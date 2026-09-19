# -*- coding: utf-8 -*-
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory


class MeowMsgAbmemBridge:
    """记忆回忆判定桥接类"""

    def __init__(self):
        """初始化摘要加载器"""
        self.abmem = MeowLoadAbstractMemory()

    def decide(self, text: str, username: str = "") -> dict:
        """把消息转给摘要加载器判定是否需要加强回忆"""
        return self.abmem.decide_recall(text, username)
