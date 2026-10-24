# -*- coding: utf-8 -*-
# func/llm/message_get.py
# 从 pipeline 接收识别结果并做正则清洗

import re


class MessageGet:
    """接收 SenseVoice 识别文本，按配置规则做正则清洗"""

    def __init__(self, config):
        self.replace_rules = config.message_replace_rules

    def set_rules(self, rules):
        """配置热重载：换掉清洗规则（保持调用点不变）"""
        self.replace_rules = rules or {}

    def clean(self, text: str) -> str:
        """对输入文本逐条应用替换规则并去首尾空白"""
        if not text:
            return text
        for pattern, repl in self.replace_rules.items():
            text = re.sub(pattern, repl, text)
        return text.strip()
