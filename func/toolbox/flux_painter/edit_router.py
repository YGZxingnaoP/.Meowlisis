# -*- coding: utf-8 -*-

import json
import re
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.flux_painter.config import TBFluxPainterConfig
from func.toolbox.flux_painter.painting_core import TBFluxPainterCore
from func.toolbox.flux_painter.port.base import create_painter_llm

JUDGE_SYSTEM = (
    "你是绘画改图判定助手。用户刚让你画了一张图，现在又发来一条消息。\n"
    "请判断这条新消息是否是在“上一张图的基础上做修改”（例如：改服装/颜色/姿势/表情/背景、"
    "加或删元素、换画风等），还是与改图无关的普通闲聊或全新的绘画请求。\n"
    "只输出一个 JSON，不要任何多余文字：\n"
    '{"modify": true 或 false, "instruction": "若 modify 为 true，提炼出要修改的具体指令；否则为空字符串"}'
)

@singleton
class TBFluxEditRouter:
    """画图改图判定与续画路由。"""

    def __init__(self):
        """初始化。"""
        self.log = DefaultLog().getLogger()

    def try_handle(self, channel: str, trigger_kind: str, text: str,
                   qq_context: dict = None, username: str = "") -> bool:
        """返回 True 表示已按改图处理（调用方不再走普通回复）；False 表示非改图/无窗口。"""
        cfg = TBFluxPainterConfig()
        if not cfg.edit_followup_enabled:
            return False
        t = str(text or "").strip()
        if not t:
            return False
        try:
            painter = TBFluxPainterCore()
            item = painter.get_last_paint(channel)
            if not item:
                self.log.debug(f"[改图判定] 无改图窗口 channel={channel}")
                return False
            try:
                remain = int(float(cfg.edit_followup_window)
                             - (time.time() - float(item.get("ts", 0))))
            except Exception:
                remain = -1
            self.log.info(f"[改图判定] 命中改图窗口 channel={channel} 剩余≈{remain}s，"
                          f"LLM 判定中… 输入={t[:30]!r}")
            decision = self._judge(cfg, item, t)
            if not decision.get("modify"):
                painter.clear_last_paint(channel)
                self.log.info(f"[改图判定] 判定为「非改图」，关闭窗口: {t[:30]}")
                return False
            instruction = str(decision.get("instruction") or t).strip() or t
            self.log.info(f"[改图判定] 判定为「改图」，续画 channel={channel}: {instruction[:40]}")
            painter.continue_paint(channel, instruction, qq_context or {}, username)
            return True
        except Exception:
            self.log.exception("[改图判定] 处理异常")
            return False

    def _judge(self, cfg: TBFluxPainterConfig, item: dict, text: str) -> dict:
        """LLM 判定：是否改图 + 修改指令（失败一律按非改图处理）"""
        be = item.get("elements") or {}
        llm = create_painter_llm(cfg)
        if llm is None or not getattr(llm, "client", None):
            self.log.warning("[改图判定] 绘画 LLM 不可用，按非改图处理")
            return {"modify": False, "instruction": ""}
        user_content = (
            f"上一版需求：{item.get('request') or ''}\n"
            f"上一版 positive：{be.get('positive') or ''}\n"
            f"上一版 cinema：{be.get('cinema') or ''}\n"
            f"上一版角色：{be.get('character') or ''}\n"
            f"用户新消息：{text}"
        )
        try:
            resp = llm.chat(
                [{"role": "system", "content": JUDGE_SYSTEM},
                 {"role": "user", "content": user_content}],
                tools=None, enable_thinking=False,
                options={"temperature": float(cfg.edit_followup_temperature),
                         "max_tokens": int(cfg.edit_followup_max_tokens)},
            )
        except Exception:
            self.log.exception("[改图判定] LLM 调用异常")
            return {"modify": False, "instruction": ""}
        content = ""
        if resp is not None and getattr(resp, "choices", None):
            content = str(getattr(resp.choices[0].message, "content", None) or "")
        return self._parse(content)

    @staticmethod
    def _parse(content: str) -> dict:
        """解析判定结果 JSON（含容错）"""
        if not content:
            return {"modify": False, "instruction": ""}
        m = re.search(r"\{[\s\S]*\}", content)
        if m:
            try:
                data = json.loads(m.group(0))
                modify = bool(data.get("modify"))
                instr = str(data.get("instruction") or "").strip()
                return {"modify": modify, "instruction": instr}
            except Exception:
                pass
        low = content.strip().lower()
        return {"modify": ("true" in low or "是" in content), "instruction": ""}
