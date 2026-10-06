# -*- coding: utf-8 -*-
"""养猪游戏：LLM 点评（可选），失败时回落模板文案。

端口优先级：插件独立 api_key > ctx.llm()（toolbox 端口）> 模板兜底。
"""

import random

_SYSTEM = "你是只傲娇的猫娘，用中文回答。只输出一句话，20~40字，口语化，不要客套，不要 emoji。"

# 模板兜底（LLM 不可用时使用）
_FALLBACK = {
    "checkin": [
        "打卡打完了，猪猪们都挺安分的，别偷懒啊。",
        "今天的猪圈还算像样，继续保持。",
    ],
    "fake": [
        "偷偷摸摸的，也不看看人家猪圈里养的是什么货色。",
        "假扮这种事你也干得出来，胆子不小。",
    ],
    "steal": [
        "手脚挺快嘛，就是别被人逮住了。",
        "偷来的猪也是要养的，你可得上点心。",
    ],
    "raid": [
        "打得倒是挺热闹，下次别把猪圈拆了。",
        "战况不错，就是有点吵。",
    ],
    "trade": [
        "买卖谈成了，钱货两清，别赖账。",
        "交易这种事，你最拿手了是吧。",
    ],
}


class PigLLM:
    def __init__(self, ctx, cfg):
        self.ctx = ctx
        self.cfg = cfg

    # ---------- 端口 ----------
    def _port(self):
        llm_cfg = self.cfg.llm or {}
        if llm_cfg.get("enabled") is False:
            return None
        if llm_cfg.get("api_key"):
            try:
                from openai import OpenAI
                kw = {"api_key": llm_cfg["api_key"]}
                if llm_cfg.get("base_url"):
                    kw["base_url"] = llm_cfg["base_url"]
                return ("own", OpenAI(**kw), llm_cfg)
            except Exception:
                pass
        try:
            port = self.ctx.llm() if self.ctx else None
            if port is not None and getattr(port, "client", None):
                return ("port", port, llm_cfg)
        except Exception:
            pass
        return None

    # ---------- 对外 ----------
    def comment(self, scene, facts):
        """生成一句点评；失败返回模板文案。"""
        text = self._ask(scene, facts)
        if text:
            return text
        pool = _FALLBACK.get(scene) or ["猪猪们都在看着你呢。"]
        return random.choice(pool)

    def battle_report(self, facts):
        """战斗激情描述（多句）。"""
        text = self._ask("battle", facts, max_tokens=220,
                         system="你是个热血的说书人，用中文把这场猪猪大战写得热血又搞笑，"
                                "3~5句，不要客套，不要 emoji。")
        return text or ""

    # ---------- 内部 ----------
    def _ask(self, scene, facts, max_tokens=120, system=None):
        prompt = self._build_prompt(scene, facts)
        if not prompt:
            return ""
        port = self._port()
        if not port:
            return ""
        kind, obj, llm_cfg = port
        try:
            if kind == "own":
                model = llm_cfg.get("model") or "deepseek-chat"
                base_url = llm_cfg.get("base_url") or ""
                if base_url:
                    obj = obj
                resp = obj.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system or _SYSTEM},
                              {"role": "user", "content": prompt}],
                    temperature=float(llm_cfg.get("temperature") or 0.8),
                    max_tokens=max_tokens,
                )
                return self._pick(resp)
            resp = obj.chat([{"role": "system", "content": system or _SYSTEM},
                             {"role": "user", "content": prompt}])
            return self._pick(resp)
        except Exception:
            try:
                self.ctx.log.exception("养猪游戏：LLM 点评失败")
            except Exception:
                pass
            return ""

    @staticmethod
    def _pick(resp):
        try:
            choices = getattr(resp, "choices", None)
            if not choices:
                return ""
            content = getattr(choices[0].message, "content", None)
            return str(content or "").strip().replace("\n", " ")
        except Exception:
            return ""

    @staticmethod
    def _build_prompt(scene, facts):
        head = {
            "checkin": "玩家刚打完卡：",
            "fake": "玩家刚做了假扮打卡：",
            "steal": "玩家刚偷了别人的猪：",
            "raid": "玩家刚打完一场抢猪大战：",
            "trade": "玩家刚完成一笔猪猪交易：",
            "battle": "猪猪大战的双方数据：",
        }.get(scene)
        if not head:
            return ""
        return head + str(facts or "")
