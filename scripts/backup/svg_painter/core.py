# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/core.py
# SVG 绘画模块总入口（@singleton）
# - live 主对话 与 QQ 分开独立：每个会话 key 一块画布（live / qq_private / qq_group）
# - 会话激活期「全权接管」该来源的消息（route_text / route_qq_*），直到用户说结束
# - 会话建在 .temp/svg_paint，结束（用户喊停/收工）才归档进 character/svg_paints
# - 不设超时退出：绘画会话一旦开始，持续到用户明确表示结束

import os
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.svg_painter.config import TBSvgPainterConfig
from func.toolbox.svg_painter.board import TBSvgBoardState
from func.toolbox.svg_painter.archive import TBSvgPainterArchive
from func.toolbox.svg_painter.prompts import TBSvgPainterPrompts
from func.toolbox.svg_painter.agent import TBSvgPainterAgent
from func.toolbox.svg_painter.state import TBSvgPaintingState


@singleton
class TBSvgPainterCore:
    """SVG 绘画模块会话化总入口"""

    TOOL_NAME = "svg_paint"

    # 结束绘画的词（激活期命中即收工归档，回普通对话）
    END_WORDS = (
        "不画了", "不画啦", "收工", "结束绘画", "退出绘画", "别画了", "停笔",
        "画完了", "画好啦", "画好了", "就这样吧", "就这样", "先这样吧",
        "到此为止", "不用画了", "停下吧", "行了够了",
    )

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBSvgPainterConfig()
        # 兜底默认画布（live 会话真正画布按会话创建）
        self.board = TBSvgBoardState()
        self.archive = TBSvgPainterArchive(self.config.backup_dir, self.config.temp_dir)
        self.prompts = TBSvgPainterPrompts()
        self.agent = TBSvgPainterAgent(self)
        self.state = TBSvgPaintingState()

        self._context = {}
        self._running = {}          # key -> bool（该会话是否正在跑 agent）
        self._pending_end = set()   # 绘制期间用户说结束的 key（本轮跑完后归档）
        self._lock = threading.Lock()
        self._reply_callback = None

    # ==================== 上下文注入 ====================
    def set_username(self, username: str):
        if username:
            self._context["username"] = username or ""

    def set_context(self, context: dict):
        if context:
            self._context.update(context or {})

    def set_reply_callback(self, callback):
        self._reply_callback = callback

    # ==================== 状态 ====================
    def is_enabled(self) -> bool:
        return bool(self.config.enabled)

    def is_painting(self, key: str = None) -> bool:
        if key is not None:
            return bool(self._running.get(key))
        return any(self._running.values())

    def board_for(self, key: str):
        """某会话的画布（server 首帧快照用），无则 None"""
        s = self.state.get(key)
        return s.get("board") if s else None

    # ==================== 父级工具 schema（触发入口） ====================
    def build_tools(self):
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "在 SVG 画板上绘画/画图/画画。只要用户表达「画/画一张/画个…/帮我画/画图/"
                    "绘一幅/想要一张图」等意图即可调用。进入绘画模式后，AI 会持续接管绘画相关对话"
                    "（可反复修改/续画/新画），直到用户说「不画了/收工/就这样」才结束归档。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "用户原始的绘画请求原文（必填，完整保留用户描述）",
                        },
                        "topic": {
                            "type": "string",
                            "description": "画面主题短词（可空，如：月亮上的猫）",
                        },
                    },
                    "required": ["request"],
                },
            },
        }]

    # ==================== 开局（live：analysis.dispatch / QQ：dispatch_qq） ====================
    def dispatch(self, name: str, arguments: dict) -> str:
        """live 主对话开局（父级 decide 命中 svg_paint 时调用）"""
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        return self._open_session("live", arguments, qq_context=None)

    def dispatch_qq(self, name: str, arguments: dict, qq_context: dict) -> str:
        """QQ 开局（napcat analysis 命中 svg_paint 时调用），key 按私聊/群聊隔离"""
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        if not self.config.enabled:
            return "绘画模块未开启"
        if not qq_context:
            return "缺少 QQ 上下文"
        if str(qq_context.get("message_type", "")) == "group":
            key = TBSvgPaintingState.group_key(str(qq_context.get("target_id", "")))
        else:
            key = TBSvgPaintingState.private_key(
                str(qq_context.get("user_id", "") or qq_context.get("target_id", "")))
        return self._open_session(key, arguments, qq_context=qq_context)

    def _open_session(self, key: str, arguments: dict, qq_context=None) -> str:
        if not self.config.enabled:
            return "绘画模块未开启（请在工具箱-绘画配置中启用并填写模型）"
        if self.state.is_active(key):
            return f"该绘画会话已在创作中，先说结束或画完再来开新的"
        if self.is_painting(key):
            return "绘画进行中，请稍候"

        arguments = arguments or {}
        request = str(arguments.get("request") or self._context.get("text") or "").strip()
        username = str(self._context.get("username") or "主人")

        # 每会话独立画布
        board = TBSvgBoardState()
        self.state.start(key, board, username=username, topic="")
        session = self.state.get_ref(key)
        if qq_context:
            session["qq_context"] = qq_context
            session["owner_uid"] = str(qq_context.get("user_id", "") or
                                       qq_context.get("target_id", "") or "")

        ctx = self._build_ctx(key, username, request)
        ctx["board"] = board
        ctx["session"] = session
        ctx["qq_context"] = qq_context
        self._launch(key, ctx, board)
        # QQ 开局即时反馈（live 由主链路已有回复，不重复发声）
        if qq_context:
            self._reply_key(key, "好呀，这就给你画～画完我叫你！")
        self.log.info(f"[svg_painter] 绘画会话开启 key={key}: {request[:40]}")
        return "开始作画…（画板页面实时展示；说「不画了」结束）"

    def _build_ctx(self, key: str, username: str, text: str) -> dict:
        """组装一轮 agent 上下文：短记忆 + 角色人设（显式传入）"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            persona = SystemPromptBridge().get_tool_prompt(username, text) or ""
        except Exception:
            persona = str(self._context.get("system_prompt") or "")
        short_memory = self._context.get("short_memory") or []
        try:
            if not short_memory:
                from func.pipeline.short_memory import ShortMemory
                short_memory = ShortMemory().load()[-6:]
        except Exception:
            pass
        return {
            "username": username,
            "text": text,
            "request": text,
            "short_memory": short_memory,
            "system_prompt": persona,
        }

    # ==================== 激活期接管入口 ====================
    def route_text(self, text: str, username: str = "") -> bool:
        """live 主对话拦截：绘画会话激活时全权接管，返回 True 表示已消费"""
        if not self.config.enabled or not text or not text.strip():
            return False
        key = TBSvgPaintingState.live_key()
        if not self.state.is_active(key):
            return False
        self._route(key, text, username or "主人")
        return True

    def route_qq_private(self, user_id, text) -> bool:
        if not self.config.enabled or not text or not text.strip():
            return False
        key = TBSvgPaintingState.private_key(str(user_id or ""))
        if not self.state.is_active(key):
            return False
        self._route(key, text, "")
        return True

    def route_qq_group(self, group_id, user_id, text) -> bool:
        if not self.config.enabled or not text or not text.strip():
            return False
        key = TBSvgPaintingState.group_key(str(group_id or ""))
        if not self.state.is_active(key):
            return False
        self._route(key, text, "")
        return True

    def _route(self, key: str, text: str, username: str):
        """激活期路由：
        - 结束词 → 收工归档；
        - 正在绘画（agent 线程运行中）→ 作为插话放入 inbox（边画边聊：可更新计划/实时评价）；
        - 画完一轮空闲 → 当作新一轮绘画需求继续。
        绘画会话消费的所有用户文本都会写入短期记忆与长期/用户记忆（同海龟汤口径）。
        """
        t = (text or "").strip()
        if not t:
            return
        uname = username or (self.state.get(key) or {}).get("username") or "主人"
        # 用户侧记忆（绘画期间输入，与主链路双通道无关：此段已被绘画同步拦截）
        self._save_memory("user", t, uname)
        if self._is_end_word(t):
            self._finish_session(key, reason="结束")
            return
        if self._running.get(key):
            self.push_interject(key, uname, t)
            # 轻量确认，让用户知道插话已被接收（绘画线程下轮会回应）
            self._reply_key(key, "收到～我先把手上这笔画完，马上回你")
            return
        session = self.state.get(key) or {}
        board = session.get("board")
        if board is None:
            self._finish_session(key, reason="状态异常")
            return
        ctx = self._build_ctx(key, uname, t)
        ctx["board"] = board
        ctx["session"] = self.state.get_ref(key)
        ctx["qq_context"] = session.get("qq_context")
        self._launch(key, ctx, board)

    # ==================== 绘画期间插话（方案B：边画边聊） ====================
    def push_interject(self, key: str, username: str, text: str):
        """绘画进行中收到用户消息 → 放进会话 inbox，绘画 agent 线程下一轮取走处理"""
        t = (text or "").strip()
        if not t:
            return
        try:
            session = self.state.get_ref(key)
            if session is None:
                return
            with self._lock:
                session.setdefault("inbox", []).append({"username": username or "", "text": t})
            self.log.info(f"[svg_painter] 插话入队 key={key}: {t[:50]}")
        except Exception:
            self.log.exception("[svg_painter] 插话入队失败")

    def drain_interject(self, key: str) -> list:
        """绘画 agent 线程取出该会话的所有待处理插话（取走即清空）"""
        try:
            session = self.state.get_ref(key)
            if session is None:
                return []
            with self._lock:
                items = list(session.get("inbox") or [])
                session["inbox"] = []
            return items
        except Exception:
            return []

    def chat_say(self, key: str, text: str):
        """绘画模块向用户发送回复（插话回应 / 收笔汇报；live 走 TTS，QQ 发消息），并写入记忆"""
        try:
            self.log.info(f"[svg_painter] 绘画回复发送 key={key}: {(text or '')[:80]}")
            # 助理侧记忆（回复进短期 + 长期/用户记忆）
            uname = (self.state.get(key) or {}).get("username") or "主人"
            self._save_memory("assistant", text, uname)
            self._reply_key(key, text)
        except Exception:
            self.log.exception("[svg_painter] chat_say 失败")

    # ==================== 执行 ====================
    def _launch(self, key: str, ctx: dict, board):
        with self._lock:
            self._running[key] = True
        t = threading.Thread(target=self._run, args=(key, ctx, board), daemon=True,
                             name=f"svg_painter_{key}")
        t.start()

    def _run(self, key: str, ctx: dict, board):
        """一轮绘画线程：跑完 agent 后保持会话激活（等下一句/结束词），不自动退出"""
        summary = "画好啦！"
        try:
            self.agent._channel = key
            summary = self.agent.run(ctx) or summary
            # 会话结束汇报（短，不影响前台）——经 chat_say 统一发声 + 写记忆
            self.chat_say(key, str(summary)[:80])
            # QQ：每轮收笔把成品渲染成图片发给用户（群聊 @ 发起人，私聊直发）
            try:
                ch = (self.state.get(key) or {}).get("channel", "")
                if ch in ("qq_private", "qq_group") and self.config.qq_send_image:
                    threading.Thread(target=self._send_painting_image, args=(key,),
                                     daemon=True).start()
            except Exception:
                self.log.exception("QQ 发图调度失败")
        except Exception:
            self.log.exception(f"[svg_painter] 绘画执行异常 key={key}")
            # 兜底收笔：让中间会话可在结束归档时被 flush 收走
            try:
                s = self.state.get(key)
                m = (s or {}).get("meta")
                b = (s or {}).get("board")
                if m and m.get("session_dir") and not m.get("final") and b is not None:
                    self.archive.finish_temp(m, b.to_svg(), "绘画中断")
            except Exception:
                pass
            self._reply_key(key, "画画的时候出了点问题，抱歉…")
        finally:
            with self._lock:
                self._running[key] = False
            # 绘制期间用户说了结束：等本轮跑完再收工归档
            pending = getattr(self, "_pending_end", None)
            if pending and key in pending:
                pending.discard(key)
                threading.Thread(target=self._finish_session, args=(key, "结束"),
                                 daemon=True).start()

    # ==================== 结束绘画（收工归档） ====================
    def _finish_session(self, key: str, reason: str = "结束"):
        """用户明确不画了：若 agent 在跑等它（避免并发归档），否则收尾归档并关闭会话"""
        if self._running.get(key):
            # 忙：把"结束"标为待办，等当前轮 agent 结束后由 _run 检查
            self._pending_end = self._pending_end if hasattr(self, "_pending_end") else set()
            self._pending_end.add(key)
            self._reply_key(key, "好～等这轮画完我就收工")
            return
        session = self.state.get(key)
        if not session:
            return
        meta = session.get("meta") or {}
        summary = (meta or {}).get("summary") or ""
        # 补收笔 + 归档 temp → character（含本次绘画期间产生的所有已完成临时会话）
        if meta and meta.get("session_dir"):
            try:
                board = session.get("board")
                if board is not None and not meta.get("final"):
                    self.archive.finish_temp(meta, board.to_svg(), summary or "收工")
                self.archive.archive_session(meta)
                self.archive.flush_finished_temp()
                self.archive.prune(self.config.keep_last_sessions)
            except Exception:
                self.log.exception(f"[svg_painter] 收工归档失败 key={key}")
        topic = (meta or {}).get("topic") or session.get("topic") or ""
        uname = session.get("username") or "主人"
        self._save_memory("assistant",
                          f"结束了一幅画作《{topic}》" if topic else "结束了绘画", uname)
        self._reply_key(key, f"好，这幅画收工啦！成品已保存，想看随时叫我看～" if topic
                        else "好，不画啦～随时想画再叫我")
        self.state.end(key)

    # ==================== 发送 / 记忆 ====================
    def _reply_key(self, key: str, text: str):
        if not text:
            return
        session = self.state.get(key)
        channel = (session or {}).get("channel") or "live"
        if channel in ("qq_private", "qq_group"):
            qc = (session or {}).get("qq_context")
            if qc:
                self._send_qq(qc, text)
        else:
            # live：直接走 TTS 播报（send_stream 已出声，不重复回调，避免双播）
            self._speak(text)

    def _speak(self, text: str):
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(text, source="svg_paint")
        except Exception:
            self.log.exception("[svg_painter] TTS 播报失败")

    def _send_qq(self, qq_context: dict, text: str):
        if not text:
            return
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            core = TBNapCatCore()
            if str(qq_context.get("message_type", "")) == "group":
                core.send_group_text(str(qq_context.get("target_id", "")), text)
            else:
                core.send_private_text(
                    str(qq_context.get("target_id", "") or qq_context.get("user_id", "")), text)
        except Exception:
            self.log.exception("[svg_painter] QQ 发送失败")

    # ==================== QQ 画完发图 ====================
    def _send_painting_image(self, key: str):
        """把该会话最近一轮成品 final.svg 渲染成 png 发给 QQ 用户：
        - 私聊：直接发给对方；
        - 群聊：@ 发起绘画的人并附图（对应关系：发起绘画的人 = dispatch_qq 时消息的 user_id）。
        """
        try:
            if not self.config.qq_send_image:
                return
            session = self.state.get(key) or {}
            channel = session.get("channel", "")
            if channel not in ("qq_private", "qq_group"):
                return
            meta = session.get("meta") or {}
            session_dir = meta.get("session_dir") or ""
            final_svg = os.path.join(session_dir, "final.svg")
            if not os.path.exists(final_svg):
                self.log.info(f"[svg_painter] 无成品 final.svg，跳过 QQ 发图 key={key}")
                return
            with open(final_svg, "r", encoding="utf-8") as f:
                svg_text = f.read()
            from func.toolbox.svg_painter.render import get_svg_renderer
            out_dir = os.path.join(self.config.temp_dir, "render")
            png = get_svg_renderer().svg_to_png(svg_text, out_dir=out_dir,
                                                scale=self.config.render_scale)
            if not png:
                self._reply_key(key, "画好啦！但图片渲染失败，可以到画板页查看～")
                return
            qc = session.get("qq_context") or {}
            owner = str(session.get("owner_uid") or qc.get("user_id") or qc.get("target_id") or "")
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            ncore = TBNapCatCore()
            if channel == "qq_private":
                ncore.send_private_image(owner or str(qc.get("target_id", "")), png)
            else:
                gid = str(qc.get("target_id") or qc.get("group_id") or "")
                if gid and owner:
                    # 群聊：一条消息 = @发起人 + 提示 + 图片
                    ncore.call_action_sync("send_group_msg", {
                        "group_id": int(gid),
                        "message": [
                            {"type": "at", "data": {"qq": owner}},
                            {"type": "text", "data": {"text": " 你的画好啦～"}},
                            {"type": "image", "data": {"file": ncore._to_file_uri(png)}},
                        ],
                    })
                elif gid:
                    ncore.send_group_image(gid, png)
            # 发送完成稍候再清理本地 png
            import time
            time.sleep(3)
            try:
                if os.path.exists(png):
                    os.remove(png)
            except Exception:
                pass
        except Exception:
            self.log.exception(f"[svg_painter] QQ 发图失败 key={key}")

    def _save_memory(self, role: str, content: str, username: str = ""):
        """写记忆（同海龟汤口径）：
        - 短期记忆：type=svg_paint 独立裁剪（rounds 成对）；
        - 长期/用户记忆：user → record_user_message，assistant → record_ai_message。
        """
        if not content:
            return
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({
                "role": role,
                "content": f"【绘画】{content}",
                "type": "svg_paint",
            }, 40, trim_mode="rounds")
        except Exception:
            pass
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            from func.config.app_config import AppConfig
            bridge = MeowLLMLtMemBridge()
            name = username or "主人"
            if role == "user":
                bridge.record_user_message(name, content)
            else:
                bridge.record_ai_message(name, AppConfig().ai_name, content)
        except Exception:
            pass

    # ==================== 工具 ====================
    @staticmethod
    def _is_end_word(text: str) -> bool:
        t = (text or "").strip()
        return any(k in t for k in TBSvgPainterCore.END_WORDS)
