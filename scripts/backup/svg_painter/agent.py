# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/agent.py
# SVG 绘画 Agent —— 极致单工具版
#
# 设计原则（为适配 v4-flash 等爱"闷头思考"的推理模型）：
#   模型侧只暴露一个工具 paint_submit_svg：把整幅画面一次性提交。
#   没有 start_session/蓝图/finish 之类的多轮 agentic 协商——
#   提交画面 = 自动上板 + 存档 + 收笔。模型只负责"输出内容"。
#   正文/思考里直接写 <svg>…</svg> 也会被自动识别上板（双通道兜底）。

import json
import re
import time
from types import SimpleNamespace

from func.log.default_log import DefaultLog
from func.toolbox.svg_painter.prompts import TBSvgPainterPrompts
from func.toolbox.svg_painter.port.base import create_painter_llm


def _extract_svg(text: str) -> str:
    """从文本（正文或思考内容）提取完整的 <svg>…</svg> 块，取最长者；无则空串"""
    if not text:
        return ""
    found = re.findall(r"<svg\b[^>]*>.*?</svg>", text, re.S | re.I)
    if not found:
        return ""
    return max(found, key=len).strip()


class TBSvgPainterAgent:
    """一轮绘画：调模型 → 拿到画面（工具或正文 svg）→ 上板存档收尾"""

    # ==================== 模型唯一可见的工具 ====================
    PAINT_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "paint_submit_svg",
                "description": "把整幅画面一次性提交（这是你唯一要做的动作）："
                               "把你画的完整 SVG 写进 svg 参数，一次给全、不分步、不加说明。"
                               "svg 可以是完整文档（<svg viewBox='0 0 600 800'>…</svg>），"
                               "也可以只给内部元素（系统会按画布尺寸摆放）；"
                               "不想用工具时，把同样的 <svg>…</svg> 直接写在回复正文里，系统也会自动识别上板。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "svg": {"type": "string",
                                "description": "整幅画面的 SVG 内容（一次给全；坐标落在 viewBox 内）"},
                        "note": {"type": "string", "description": "一句话说明（可选，如画了什么）"},
                    },
                    "required": ["svg"],
                },
            },
        },
    ]

    def __init__(self, core):
        self.log = DefaultLog().getLogger()
        self.core = core
        self.config = core.config
        self.board = core.board  
        self._board = None          
        self.archive = core.archive
        self.prompts = core.prompts
        self._port_llm = None  
        self._channel = None   

    def _board_ref(self):
        return self._board or self.board

    def _port(self):
        if self._port_llm is None:
            self._port_llm = create_painter_llm(self.config)
        return self._port_llm

    # ==================== 对外入口 ====================
    def run(self, context: dict) -> str:
        """执行一轮绘画：只取模型输出的画面并上板，返回收笔 summary"""
        ctx = context or {}
        self._board = ctx.get("board") or self._board or self.board
        board = self._board_ref()
        session = ctx.get("session") or {}
        username = str(ctx.get("username") or "主人")
        user_text = str(ctx.get("text") or ctx.get("request") or "").strip()
        short_memory = ctx.get("short_memory") or []
        persona = str(ctx.get("system_prompt") or "")
        key = self._channel or ctx.get("session_key") or "live"

        port = self._port()
        if port is None or not getattr(port, "client", None):
            self._broadcast({"type": "status", "text": "绘画模型未配置", "ok": False})
            return "绘画模型未配置，请在工具箱-绘画配置中填写 API Key"
        if not user_text:
            return ""

        # ---------- 组装系统提示 ----------
        board = self._board_ref()
        base_note = ""
        try:
            n = board.fragment_count
            if n > 0:
                base_note = (f"当前画布已有旧画面（{board.summary()}）。"
                             f"若用户是要改/续画它，请基于旧画内容提交新整幅（会整体替换）；"
                             f"若用户是要画新图，直接提交新图即可。")
        except Exception:
            pass
        system = self.prompts.build_system(persona, board.width, board.height, board.bg, base_note)
        self._base_system = system
        messages = [{"role": "system", "content": system}]
        for m in (short_memory or [])[-4:]:
            role = m.get("role")
            if role in ("user", "assistant") and m.get("content"):
                messages.append({"role": role, "content": str(m["content"])})
        messages.append({"role": "user", "content": f"（{username}）：{user_text}"})

        self._broadcast({"type": "status", "text": "AI 正在作画…", "ok": True, "info": "构思画面"})

        meta = None            # 临时会话 meta（首次拿到画面时才创建）
        final_summary = ""
        steps = 0
        reminded = False       # 已提醒过"请直接提交画面"

        while steps < 3:
            steps += 1
            # 取走绘画期间用户的插话（作为新一轮需求信息带给模型）
            try:
                inter = self.core.drain_interject(key) or []
            except Exception:
                inter = []
            for it in inter:
                uname = str(it.get("username") or username)
                t = str(it.get("text") or "").strip()
                if t:
                    messages.append({"role": "user",
                                     "content": f"（{uname} 插话）：{t}"})
                    self.log.info(f"[svg_painter] 收到插话并入: {uname}: {t[:40]}")

            resp = self._call_model(port, messages, len(messages))
            if resp is None:
                self._broadcast({"type": "status", "text": "绘画模型响应失败", "ok": False})
                return "绘画模型响应失败，请稍后再试"
            msg = resp.choices[0].message
            reasoning = str(getattr(msg, "reasoning_content", None) or "")
            content = str(getattr(msg, "content", None) or "").strip()
            tool_calls = getattr(msg, "tool_calls", None) or []

            # ---- 1) 工具：paint_submit_svg（唯一工具） ----
            svg_txt = ""
            note = ""
            for tc in tool_calls:
                fn = getattr(tc, "function", None)
                if not fn or fn.name != "paint_submit_svg":
                    continue
                try:
                    args = json.loads((fn.arguments or "{}") or "{}")
                except Exception:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                svg_txt = str(args.get("svg") or "").strip()
                note = str(args.get("note") or "").strip()
                break

            # ---- 2) 正文直出 / 思考里写了完整 <svg>（兜底） ----
            if not svg_txt:
                svg_txt = _extract_svg(content)
            if not svg_txt:
                svg_txt = _extract_svg(reasoning)

            # ---- 3) 拿到画面 → 上板存档收尾 ----
            if svg_txt:
                if meta is None:
                    meta = self._open_meta(username, user_text)
                    if meta:
                        session["meta"] = meta
                        session["temp_dir"] = meta.get("session_dir", "")
                        session["topic"] = meta.get("topic", "")
                        try:
                            self.core.state.get_ref(key)["meta"] = meta
                        except Exception:
                            pass
                summary = self._land(meta, board, svg_txt, note or content)
                if summary:
                    final_summary = summary
                break

            # ---- 4) 这轮没给画面：提醒一次后重试 ----
            if content and not reminded:
                # 模型在说别的话（寒暄/解释）→ 转达并把要求再强调一遍
                self._say_chat(content[:200])
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user",
                                 "content": "请调用 paint_submit_svg 把整幅画面提交上来"
                                            "（或直接在正文写 <svg>…</svg>）。"})
                reminded = True
                continue
            messages.append({"role": "user",
                             "content": "你还没有提交画面。请立即调用 paint_submit_svg "
                                        "提交整幅 SVG（这是你唯一要做的），不要只写构思文字。"})
            if reminded:
                break
            reminded = True

        if not final_summary:
            # 三轮回合仍无画面：留一个明确交代，不归档空图
            try:
                n = board.fragment_count
            except Exception:
                n = 0
            if n > 0:
                # 画布有旧内容时保留现状并提示
                final_summary = "这轮还没画好，先保留当前画面；想继续随时喊我～"
            else:
                final_summary = "没有画出来……模型没有提交画面（可能是思考型模型未吐工具），" \
                                "可换支持 function calling 的模型或稍后再试。"
            self.log.warning(f"[svg_painter] 本轮未获得画面（{steps} 轮）")
        return final_summary

    # ==================== 会话与上板 ====================
    def _open_meta(self, username: str, request: str) -> dict:
        """首次拿到画面时创建临时会话 meta（目录/版本/思考等）"""
        try:
            meta = self.archive.create_temp_session(
                username=username,
                request=request,
                topic=(request or "画")[:24],
                intent="new",
                model=(self._port().model if self._port() else ""),
            )
            self.log.info(f"[svg_painter] 新会话: {meta.get('name')}")
            return meta
        except Exception:
            self.log.exception("[svg_painter] 创建会话失败")
            return None

    def _land(self, meta, board, svg_txt: str, summary_hint: str = "") -> str:
        """画面落地：尺寸自适应 → 整幅替换 → 存档 → 广播 → 收笔归档(final 落盘)。返回 summary"""
        try:
            # 画布尺寸跟随 svg viewBox（模型可能给 600x800 之外的规格）
            vm = re.search(
                r"<svg\b[^>]*viewBox\s*=\s*[\"']([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)[\"']",
                svg_txt, re.I)
            if vm:
                vw, vh = int(float(vm.group(3))), int(float(vm.group(4)))
                if vw > 0 and vh > 0 and (vw, vh) != (board.width, board.height):
                    board.reset(vw, vh, board.bg)
            fid = board.replace_snapshot(svg_txt)
            if not fid:
                self.log.warning("[svg_painter] 画面校验未通过，未上板")
                return ""
            path = self.archive.save_version(meta, board.to_svg(), note="新画面")
            self._broadcast({"type": "snapshot", "svg": board.to_svg()})
            self._broadcast({"type": "saved", "path": path})
            # 收笔（final.svg 落盘到 .temp，等待用户说"不画了"再归档进 character）
            summary = (summary_hint or "").strip()
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            summary = re.sub(r"\s+", " ", summary)[:60]
            if len(summary) < 4 or "<svg" in (summary_hint or ""):
                summary = "画好啦！"
            try:
                self.archive.finish_temp(meta, board.to_svg(), summary=summary)
                self._broadcast({"type": "finish", "text": "本轮绘画完成",
                                 "summary": summary, "session": meta.get("name", "")})
            except Exception:
                self.log.exception("[svg_painter] 收笔落盘失败")
            self.log.info(f"[svg_painter] 画面已上板: {fid} v{len(meta.get('versions', []))}")
            return summary
        except Exception:
            self.log.exception("[svg_painter] 上板失败")
            return ""

    # ==================== 模型调用（流式聚合） ====================
    def _call_model(self, port, messages, n_msgs: int = 0) -> object:
        """流式调用并聚合（绘画回合关闭思考；失败重试一次）。返回聚合响应或 None"""
        try:
            n_brush = self._board_ref().fragment_count
        except Exception:
            n_brush = 0
        self.log.info(f"[svg_painter] → 请求模型（画布 {n_brush} 片段，对话 {n_msgs} 条，thinking=关）…")
        for attempt in (1, 2):
            try:
                agg = self._stream_aggregate(
                    port.chat_stream(messages, tools=self.PAINT_TOOLS,
                                     enable_thinking=False))
                if agg is not None:
                    return agg
            except Exception:
                self.log.exception(f"[svg_painter] 流式调用异常（第 {attempt} 次）")
        return None

    def _stream_aggregate(self, stream):
        """把流式 chunk 聚合为 SimpleNamespace 响应（与 chat() 同形态）"""
        reasoning_parts, content_parts = [], []
        tool_calls = {}          # index -> {id, name, args}
        got_any = False
        last_data = time.time()
        last_mark = 0
        for chunk in stream or []:
            got_any = True
            now = time.time()
            if now - last_data >= 10:
                self.log.info(f"[svg_painter] 等待模型数据流 {int(now - last_data)}s…")
            last_data = now
            try:
                choices = chunk.choices or []
                if not choices:
                    continue
                delta = choices[0].delta
            except Exception:
                continue
            r = getattr(delta, "reasoning_content", None) or ""
            if r:
                reasoning_parts.append(r)
                total = sum(len(x) for x in reasoning_parts)
                if total - last_mark >= 500:
                    self.log.info(f"[svg_painter] 模型思考中…（累计 {total} 字）")
                    last_mark = total
            c = getattr(delta, "content", None) or ""
            if c:
                content_parts.append(c)
            for dc in (getattr(delta, "tool_calls", None) or []):
                try:
                    idx = dc.index if dc.index is not None else 0
                except Exception:
                    idx = 0
                slot = tool_calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                if getattr(dc, "id", None):
                    slot["id"] = dc.id
                fn = getattr(dc, "function", None)
                if fn:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args"] += (fn.arguments or "")

        if not got_any:
            return None
        reasoning = "".join(reasoning_parts)
        content = "".join(content_parts)
        if reasoning:
            self.log.info(f"[svg_painter] 本轮思考完成（共 {len(reasoning)} 字）")
        tcs = None
        if tool_calls:
            tcs = []
            for idx in sorted(tool_calls):
                slot = tool_calls[idx]
                tcs.append(SimpleNamespace(
                    id=slot["id"] or f"call_{idx}",
                    type="function",
                    function=SimpleNamespace(name=slot["name"],
                                             arguments=slot["args"] or "{}"),
                ))
                self.log.info(f"[svg_painter] 模型请求工具: {slot['name']}")
        msg = SimpleNamespace(reasoning_content=reasoning or None,
                              content=content or None,
                              tool_calls=tcs)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    # ==================== 推送 ====================
    def _say_chat(self, text: str):
        """模型的无画面话语即时转达给用户"""
        text = (text or "").strip()
        if not text:
            return
        try:
            self.log.info(f"[svg_painter] 插话回应: {text[:120]}")
            self.core.chat_say(self._channel or "live", text)
        except Exception:
            self.log.exception("[svg_painter] 插话回应发送失败")

    def _broadcast(self, payload: dict):
        try:
            from func.toolbox.svg_painter.server import get_svg_painter_server
            channel = getattr(self, "_channel", None) or "live"
            get_svg_painter_server().broadcast(channel, payload)
        except Exception:
            pass
