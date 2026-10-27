# -*- coding: utf-8 -*-
# func/catpaws/if_start.py
# 触发判断：前缀触发直接进链路；意图词命中再用独立 port 判断要不要操作手机
import json
import re

from func.catpaws.config import CWCatPawsConfig
from func.catpaws.port import get_catpaws_port
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

CW_INTENT_PROMPT = (
    "你是意图判断器，只判断用户这句话是不是在要求别人真的去操作一台 iPhone 把事情办完"
    "（点外卖、发消息、开应用、搜索、下单、改设置、刷页面…）。\n"
    "只是闲聊、提问、讨论手机、表达情绪、说自己想吃什么但没让谁去办，一律算 false。\n"
    "只输出一行 JSON，不要解释：{\"hit\": true 或 false, \"goal\": \"要办的事，尽量保留用户原话里的关键信息\"}"
)


@singleton
class CWCatPawsIfStart:
    """触发判断：返回 (mode, goal)，mode 为 prefix/intent，未命中返回 (None, "")"""

    MODE_PREFIX = "prefix"
    MODE_INTENT = "intent"

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = config or CWCatPawsConfig()

    def decide(self, text, username=""):
        """判断消息是否进入 catpaws 链路，并给出要执行的目标"""
        body = str(text or "").strip()
        if not body:
            return None, ""
        mode = self.config.trigger_mode
        if mode in ("both", "prefix"):
            for prefix in self.config.prefixes:
                if prefix and body.startswith(prefix):
                    rest = body[len(prefix):].lstrip("：:，,。!！?？ 　")
                    return self.MODE_PREFIX, (rest.strip() or body)
        if mode in ("both", "intent"):
            if any(word and word in body for word in self.config.intent_words):
                hit, goal = self._judge(body, username)
                if hit:
                    return self.MODE_INTENT, (goal or body)
        return None, ""

    def _judge(self, body, username=""):
        """交给独立 port 判断是不是真的要操作手机"""
        prompt = self.config.intent_prompt or CW_INTENT_PROMPT
        try:
            port = get_catpaws_port(self.config)
            answer = port.text([{"role": "system", "content": prompt},
                                {"role": "user", "content": body}])
        except Exception:
            self.log.exception("[CatPaws] 意图判断失败，本条不接管")
            return False, ""
        return self._parse(answer)

    @staticmethod
    def _parse(answer):
        """解析 port 返回的一行 JSON"""
        text = str(answer or "").strip()
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                data = json.loads(match.group(0))
                return bool(data.get("hit")), str(data.get("goal") or "").strip()
            except Exception:
                pass
        if re.search(r'"hit"\s*:\s*true', text, re.I):
            return True, ""
        return False, ""
