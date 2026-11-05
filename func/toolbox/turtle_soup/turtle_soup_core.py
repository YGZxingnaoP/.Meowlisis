# -*- coding: utf-8 -*-
# func/toolbox/turtle_soup/turtle_soup_core.py
# 海龟汤工具总入口：触发生成、拦截路由、判定与结束

import json
import os
import re
import threading
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.turtle_soup.config import TBTurtleSoupConfig
from func.toolbox.turtle_soup.state import TBTurtleSoupState
from func.toolbox.turtle_soup.prompt import build_game_block
from func.toolbox.turtle_soup.generate import generate
from func.toolbox.turtle_soup.judge import judge


ROUTE_CONSUMED = "consumed"
ROUTE_PASS = "pass"


@singleton
class TBTurtleSoupCore:
    """海龟汤工具：analysis 只负责触发，本模块负责生成/播报/判定/结束"""

    TOOL_NAME = "turtle_soup"

    # QQ 合并回复：固定等待窗口（秒）与单次合并上限（与 QQ 链路缓冲同款语义）
    QQ_MERGE_WAIT = 7.0
    QQ_MERGE_MAX = 10

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBTurtleSoupConfig()
        self.state = TBTurtleSoupState()
        # 编号用 thread-local 存储，避免 QQ / live 多线程并发触发开新局时串线
        self._local = threading.local()
        # QQ 合并缓冲：session_key -> {"items", "qq_context", "count", "timer"}
        self._merge_lock = threading.Lock()
        self._merges = {}
        # 启动（首次实例化）时清理残留的进行中缓存，避免崩溃后残留游戏态
        self._cleanup_cache()

    # ==================== 工具注册 ====================
    def set_meowid(self, meowid):
        self._local.meowid = meowid or ""

    @property
    def _meowid(self):
        """当前线程注入的内部编号（thread-local，多线程互不干扰）"""
        return getattr(self._local, "meowid", "")

    def build_tools(self) -> List[Dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "用户想玩海龟汤（情境猜谜）时调用，生成一道海龟汤开始游戏",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "difficulty": {
                            "type": "string",
                            "enum": ["easy", "hard"],
                            "description": "低难度汤面约20字/高难度约40字；可选，缺省由AI结合用户信息决定",
                        },
                    },
                    "required": [],
                },
            },
        }]

    # ==================== 触发入口 ====================
    def dispatch(self, name, arguments):
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        if not self.config.enabled:
            return "海龟汤模块未启用"
        if self.state.is_active(self.state.live_key()):
            self._speak("已经有一局海龟汤在进行中啦，先结束这局再开新的吧")
            return "已有进行中的海龟汤"
        difficulty = (arguments or {}).get("difficulty", "") or ""
        return self._start_game(self.state.live_key(), self._meowid, difficulty, qq_context=None)

    def dispatch_qq(self, name, arguments, qq_context):
        if name != self.TOOL_NAME or not self.config.enabled or not self.config.qq_enabled:
            return None
        key = self._qq_key(qq_context)
        if self.state.is_active(key):
            self._send_qq(qq_context, "已经有一局海龟汤在进行中啦，先结束这局再开新的吧")
            return True
        difficulty = (arguments or {}).get("difficulty", "") or ""
        self._start_game(key, self._meowid, difficulty, qq_context=qq_context)
        return True

    # ==================== 拦截入口 ====================
    def route_text(self, text, meowid="", channel="live"):
        """语音/msg/sensevoice/弹幕拦截：consumed=已处理，pass=放行主LLM，None=无游戏"""
        if not self.config.enabled:
            return None
        if not text or not text.strip():
            return None
        key = self.state.live_key()
        if not self.state.is_active(key):
            return None
        return self._route(key, meowid or "", text.strip(), qq_context=None)

    def route_qq_private(self, user_id, text, nickname=""):
        """QQ 私聊拦截：游戏激活时全权处理（零 TTS/音频），返回 True 表示已消费"""
        if not self.config.enabled or not self.config.qq_enabled:
            return False
        if not text or not text.strip():
            return False
        key = self.state.private_key(str(user_id or ""))
        if not self.state.is_active(key):
            return False
        qq_context = {"message_type": "private", "user_id": str(user_id), "target_id": str(user_id)}
        self._merge_qq(key, self._qq_meowid(user_id, nickname), text.strip(), qq_context)
        return True

    def route_qq_group(self, group_id, user_id, text, nickname=""):
        """QQ 群聊拦截：游戏激活时全权处理，返回 True 表示已消费"""
        if not self.config.enabled or not self.config.qq_enabled:
            return False
        if not text or not text.strip():
            return False
        key = self.state.group_key(str(group_id or ""))
        if not self.state.is_active(key):
            return False
        qq_context = {
            "message_type": "group",
            "target_id": str(group_id),
            "user_id": str(user_id),
            "group_id": str(group_id),
        }
        self._merge_qq(key, self._qq_meowid(user_id, nickname), text.strip(), qq_context)
        return True

    # ==================== QQ 合并回复 ====================
    def _merge_qq(self, key, meowid, text, qq_context):
        """把 QQ 消息放进该会话的合并缓冲：固定 7 秒内无新消息后统一判定并回复

        合并语义与 QQ 链路缓冲一致：连发消息合并成一条，达到上限立即回复。
        """
        to_flush = None
        with self._merge_lock:
            buf = self._merges.get(key)
            if buf is None:
                buf = {"items": [], "qq_context": qq_context, "count": 0, "timer": None}
                self._merges[key] = buf
            buf["items"].append({"meowid": str(meowid or ""), "text": text})
            buf["qq_context"] = qq_context
            if buf["timer"] is not None:
                buf["timer"].cancel()
                buf["timer"] = None
            buf["count"] += 1
            if buf["count"] >= self.QQ_MERGE_MAX:
                to_flush = self._merges.pop(key, None)
                self.log.info(f"[TurtleSoup] 合并达到上限 {self.QQ_MERGE_MAX} 条，立即回复")
            else:
                timer = threading.Timer(self.QQ_MERGE_WAIT, self._on_merge_timeout,
                                        args=(key, buf["count"]))
                timer.daemon = True
                buf["timer"] = timer
                timer.start()
                self.log.info(
                    f"[TurtleSoup] 合并第 {buf['count']} 条，{self.QQ_MERGE_WAIT:.0f} 秒后无新消息则回复")
        if to_flush:
            self._flush_qq_merge(key, to_flush)

    def _on_merge_timeout(self, key, count):
        """合并定时器到期：期间没有新消息（count 未变）才取出回复"""
        to_flush = None
        with self._merge_lock:
            buf = self._merges.get(key)
            if buf is None or buf["count"] != count:
                return
            to_flush = self._merges.pop(key, None)
        if to_flush:
            self._flush_qq_merge(key, to_flush)

    def _flush_qq_merge(self, key, buf):
        """合并窗口到期：逐条记到各自提问者名下，再整体判定 + 回复"""
        items = [it for it in (buf.get("items") or []) if str(it.get("text") or "").strip()]
        if not items or not self.state.is_active(key):
            return
        for it in items:
            self._save_memory("user", it["text"], it.get("meowid", ""))
            self._save_ltmem("user", it["text"], it.get("meowid", ""))
        text = "，".join(it["text"] for it in items)
        # 回复归属最近一个身份可用的提问者
        meowid = ""
        for it in reversed(items):
            if it.get("meowid"):
                meowid = str(it["meowid"])
                break
        self.log.info(f"[TurtleSoup] 合并回复（{len(items)} 条）: {text[:30]}")
        self._route(key, meowid, text, qq_context=buf.get("qq_context"), record_user=False)

    def _clear_merge(self, key):
        """清掉某会话挂起的合并缓冲（开局/结束时调用）"""
        with self._merge_lock:
            buf = self._merges.pop(key, None)
            if buf and buf.get("timer") is not None:
                buf["timer"].cancel()

    def _qq_meowid(self, user_id, nickname=""):
        """QQ 号 → 内部编号：身份标准统一走 meowid，昵称只用于首次建档"""
        if not str(user_id or "").strip():
            return ""
        try:
            from func.pipeline.id_signup import IdSignupBridge
            return IdSignupBridge().meowid_of_account("qq", str(user_id), str(nickname or ""))
        except Exception:
            self.log.exception("[TurtleSoup] QQ 身份解析失败")
            return ""

    # ==================== 核心路由 ====================
    def _route(self, key, meowid, text, qq_context, record_user=True):
        """判定 + 分支。voice 返回 consumed/pass；qq 内部已处理

        record_user：用户文本是否由本方法写记忆。QQ 合并回复已按提问者逐条写过，
        这里传 False，避免同一条文本重复落库。
        """
        # 关键词兜底（强退出/强重报）
        if self._is_giveup_kw(text):
            self._end_game(key, meowid, text, mode="give_up", qq_context=qq_context)
            return ROUTE_CONSUMED
        if self._is_repeat_kw(text):
            self._announce_surface(key, meowid, qq_context)
            return ROUTE_CONSUMED

        puzzle = self.state.get_puzzle(key)
        history = self.state.get_history(key)
        result = judge(puzzle, meowid, text, history)

        if result.get("repeat"):
            self._announce_surface(key, meowid, qq_context)
            return ROUTE_CONSUMED
        if result.get("give_up"):
            self._end_game(key, meowid, text, mode="give_up", qq_context=qq_context)
            return ROUTE_CONSUMED
        if result.get("solved"):
            self._end_game(key, meowid, text, mode="solved", qq_context=qq_context)
            return ROUTE_CONSUMED

        # 普通猜测
        if qq_context is not None:
            self._host_reply_qq(key, meowid, text, qq_context, record_user=record_user)
            return ROUTE_CONSUMED
        self.state.record_turn(key, "user", text)
        return ROUTE_PASS

    # ==================== 开始游戏 ====================
    def _start_game(self, key, meowid, difficulty, qq_context):
        self._clear_merge(key)
        text = f"用户想玩海龟汤，难度：{difficulty or '由你决定'}"
        puzzle = generate(meowid, text, difficulty)
        if not puzzle:
            if qq_context is not None:
                self._send_qq(qq_context, "没想出来，再来一次吧")
            else:
                self._speak("没想出来，再来一次吧")
            return "生成失败"

        game_block = build_game_block(puzzle)
        self.state.start(key, puzzle, game_block)
        self._save_cache(key)

        title = (puzzle.get("title") or "").strip()
        surface = (puzzle.get("surface") or "").strip()
        opening = f"来玩海龟汤吧！题目是「{title}」\n汤面：{surface}\n你可以用「是/否」提问，或直接猜汤底。"
        if qq_context is not None:
            self._send_qq(qq_context, opening)
        else:
            self._speak(opening)
        self._save_memory("assistant", opening, meowid)
        self._save_ltmem("assistant", opening, meowid)
        return "已开始"

    # ==================== 重报汤面 ====================
    def _announce_surface(self, key, meowid, qq_context):
        puzzle = self.state.get_puzzle(key)
        if not puzzle:
            return
        title = (puzzle.get("title") or "").strip()
        surface = (puzzle.get("surface") or "").strip()
        text = f"汤面再说一遍：\n「{title}」\n{surface}"
        if qq_context is not None:
            self._send_qq(qq_context, text)
        else:
            self._speak(text)
        self._save_memory("assistant", text, meowid)
        self._save_ltmem("assistant", text, meowid)

    # ==================== 结束游戏 ====================
    def _end_game(self, key, meowid, text, mode, qq_context):
        puzzle = self.state.get_puzzle(key)
        reply = self._build_end_text(puzzle, meowid, mode)
        if qq_context is not None:
            self._send_qq(qq_context, reply)
        else:
            self._speak(reply)
        self._save_memory("assistant", reply, meowid)
        self._save_ltmem("assistant", reply, meowid)
        self._archive(key)
        self._remove_cache(key)
        self.state.end(key)
        self._clear_merge(key)

    def _build_end_text(self, puzzle, meowid, mode):
        """揭晓汤底：提示词写明是系统结算指令、必须把汤底讲出来（不做文案兜底）"""
        if not puzzle:
            return ""
        title = (puzzle.get("title") or "").strip()
        surface = (puzzle.get("surface") or "").strip()
        answer = (puzzle.get("answer") or "").strip()
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            system = TBoxGetPrompt().get_system_prompt(meowid, "") or ""
            if mode == "solved":
                instruction = (
                    "【系统引导·结算】这一段不是用户发来的话，是系统下发的结算指令：本局海龟汤已经结束，用户猜中了汤底。\n"
                    f"题目：{title}\n汤面：{surface}\n汤底（用户还没看到，必须由你亲口讲出来）：{answer}\n"
                    "请以你的角色身份回复用户：先为ta猜中而高兴，再把汤底完整地讲给ta听。\n"
                    "硬性要求：必须把汤底讲清楚，不能省略、不能只说「就是那样」、不能反问用户、不能只道喜不报答案；"
                    "不要在回复里提到「系统」「指令」这些词。"
                )
            else:
                instruction = (
                    "【系统引导·结算】这一段不是用户发来的话，是系统下发的结算指令：本局海龟汤已经结束，用户放弃并要揭晓。\n"
                    f"题目：{title}\n汤面：{surface}\n汤底（用户还没看到，必须由你亲口讲出来）：{answer}\n"
                    "请以你的角色身份回复用户：自然收尾，把汤底完整地讲给ta听。\n"
                    "硬性要求：必须把汤底讲清楚，不能省略、不能只说「就是这样」、不能反问用户；"
                    "不要在回复里提到「系统」「指令」这些词。"
                )
            llm = self._llm()
            if llm and llm.client:
                resp = llm.chat([
                    {"role": "system", "content": system},
                    {"role": "user", "content": instruction},
                ])
                if resp and resp.choices:
                    content = (resp.choices[0].message.content or "").strip()
                    if content:
                        return content
        except Exception:
            self.log.exception("[TurtleSoup] 生成结束文案失败")
        return ""

    # ==================== QQ 主持回答 ====================
    def _host_reply_qq(self, key, meowid, text, qq_context, record_user=True):
        """QQ 普通猜测：napcat LLM 主持 + 发 QQ 文本（零 TTS/音频）"""
        try:
            history = self.state.get_history(key)  # 不含当前消息（当前由 reply 内部追加）

            def on_segment(seg):
                if seg:
                    self._send_qq(qq_context, seg)

            if str(qq_context.get("message_type", "")) == "group":
                from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
                gid = str(qq_context.get("group_id", "") or qq_context.get("target_id", ""))
                gname = str(qq_context.get("group_name", "") or gid)
                reply = TBNapCatGroupLLM().reply(
                    meowid, gid, gname, text, history, "", on_segment,
                )
            else:
                from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM
                reply = TBNapCatLLM().reply(
                    meowid,
                    str(qq_context.get("user_id", "")),
                    text,
                    history,
                    on_segment,
                )
            self.state.record_turn(key, "user", text)
            if record_user:
                self._save_memory("user", text, meowid)
                self._save_ltmem("user", text, meowid)
            if reply:
                self.state.record_turn(key, "assistant", reply)
                self._save_memory("assistant", reply, meowid)
                self._save_ltmem("assistant", reply, meowid)
        except Exception:
            self.log.exception("[TurtleSoup] QQ 主持回答失败")

    # ==================== 缓存与归档 ====================
    def _cleanup_cache(self):
        """清理 cache_dir 下所有残留 json（进行中的局缓存）"""
        try:
            cache_dir = self.config.cache_dir
            if os.path.isdir(cache_dir):
                for f in os.listdir(cache_dir):
                    if f.endswith(".json"):
                        try:
                            os.remove(os.path.join(cache_dir, f))
                        except Exception:
                            pass
        except Exception:
            pass

    def _cache_path(self, key):
        safe = re.sub(r'[\\/:*?"<>|]', "_", str(key))
        return os.path.join(self.config.cache_dir, f"{safe}.json")

    def _save_cache(self, key):
        puzzle = self.state.get_puzzle(key)
        if not puzzle:
            return
        try:
            os.makedirs(self.config.cache_dir, exist_ok=True)
            with open(self._cache_path(key), "w", encoding="utf-8") as f:
                json.dump(puzzle, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("[TurtleSoup] 写缓存失败")

    def _remove_cache(self, key):
        try:
            path = self._cache_path(key)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _archive(self, key):
        """结束的局归档到 character/turtle_soup"""
        puzzle = self.state.get_puzzle(key)
        if not puzzle:
            return
        try:
            os.makedirs(self.config.bank_dir, exist_ok=True)
            safe = re.sub(r'[\\/:*?"<>|]', "_", (puzzle.get("title") or "未命名").strip()) or "未命名"
            path = os.path.join(self.config.bank_dir, f"{safe}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(puzzle, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("[TurtleSoup] 归档失败")

    # ==================== 发送 ====================
    def _speak(self, text):
        if not text:
            return
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(text, source="turtle_soup")
        except Exception:
            self.log.exception("[TurtleSoup] TTS 播报失败")

    def _send_qq(self, qq_context, text):
        if not text:
            return
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            core = TBNapCatCore()
            if str(qq_context.get("message_type", "")) == "group":
                core.send_group_text(str(qq_context.get("target_id", "")), text)
            else:
                core.send_private_text(
                    str(qq_context.get("target_id", "") or qq_context.get("user_id", "")),
                    text,
                )
        except Exception:
            self.log.exception("[TurtleSoup] QQ 发送失败")

    # ==================== 记忆 ====================
    def _save_memory(self, role, content, meowid=""):
        """写短期记忆（type=turtle_soup，独立裁剪）"""
        if not content:
            return
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({
                "role": role,
                "content": f"【海龟汤】{content}",
                "type": "turtle_soup",
            }, 40, trim_mode="rounds")
        except Exception:
            self.log.exception("[TurtleSoup] 短期记忆保存失败")

    def _save_ltmem(self, role, content, meowid=""):
        """写长期记忆/用户记忆（AI 输出记 ai_name，用户猜测记 meowid）"""
        if not content:
            return
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            from func.config.app_config import AppConfig
            bridge = MeowLLMLtMemBridge()
            if not meowid:
                self.log.error("[TurtleSoup] 无身份编号，跳过记忆写入")
                return
            name = meowid
            if role == "user":
                bridge.record_user_message(name, content)
            else:
                bridge.record_ai_message(name, AppConfig().ai_name, content)
        except Exception:
            self.log.exception("[TurtleSoup] 长期记忆保存失败")

    # ==================== 工具方法 ====================
    @staticmethod
    def _qq_key(qq_context):
        if str(qq_context.get("message_type", "")) == "group":
            return TBTurtleSoupState.group_key(str(qq_context.get("target_id", "")))
        return TBTurtleSoupState.private_key(
            str(qq_context.get("user_id", "") or qq_context.get("target_id", ""))
        )

    @staticmethod
    def _is_giveup_kw(text):
        return any(k in text for k in ("不玩了", "放弃", "结束游戏", "停止", "揭晓", "公布答案", "公布汤底"))

    @staticmethod
    def _is_repeat_kw(text):
        return any(k in text for k in ("再说一遍", "重复一遍", "谜面是什么", "汤面是什么", "题目是什么"))

    @staticmethod
    def _llm():
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "meowllm":
            from func.toolbox.port.meowllm import TBoxMeowLLM
            return TBoxMeowLLM(cfg)
        if cfg.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(cfg)
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
