# -*- coding: utf-8 -*-
# func/sensevoice/optimizer.py
# 识别结果易错词替换优化（字符串替换）

from func.log.default_log import DefaultLog


class SenseVoiceTextOptimizer:
    """识别文本优化类：按配置将错误词替换为正确词"""

    def __init__(self, config):
        self.log = DefaultLog().getLogger()
        self.replace_rules = config.replace_rules

    def optimize(self, text: str) -> str:
        """对识别文本逐条替换错误词为正确词（字符串替换，不涉及正则）"""
        if not text:
            return text
        for correct, wrongs in self.replace_rules.items():
            if not isinstance(wrongs, (list, tuple)):
                wrongs = [wrongs]
            for w in wrongs:
                w = str(w).strip()
                if w:
                    text = text.replace(w, str(correct))
        return text
