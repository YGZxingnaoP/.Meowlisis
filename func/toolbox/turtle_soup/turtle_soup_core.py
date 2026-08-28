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

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBTurtleSoupConfig()
        self.state = TBTurtleSoupState()
        # 用户名用 thread-local 存储，避免 QQ / live 多线程并发触发开新局时串线
        self._local = threading.local()
        # 启动（首次实例化）时清理残留的进行中缓存，避免崩溃后残留游戏态
        self._cleanup_cache()

    # ==================== 工具注册 ====================
    def set_username(self, username):
        self._local.username = username or ""

    @property
    def _username(self):
        """当前线程注入的用户名（thread-local，多线程互不干扰）"""
        return getattr(self._local, "username", "")

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
        return self._start_game(self.state.live_key(), self._username, difficulty, qq_context=None)

    def dispatch_qq(self, name, arguments, qq_context):
        if name != self.TOOL_NAME or not self.config.enabled or not self.config.qq_enabled:
            return None
        key = self._qq_key(qq_context)
        if self.state.is_active(key):
            self._send_qq(qq_context, "已经有一局海龟汤在进行中啦，先结束这局再开新的吧")
            return True
        difficulty = (arguments or {}).get("difficulty", "") or ""
        self._start_game(key, self._username, difficulty, qq_context=qq_context)
        return True

    # ==================== 拦截入口 ====================
    def route_text(self, text, username="", channel="live"):
        """语音/msg/sensevoice/弹幕拦截：consumed=已处理，pass=放行主LLM，None=无游戏"""
        if not self.config.enabled:
            return None
        if not text or not text.strip():
            return None
        key = self.state.live_key()
        if not self.state.is_active(key):
            return None
        return self._route(key, username or "", text.strip(), qq_context=None)

    def route_qq_private(self, user_id, text):
        """QQ 私聊拦截：游戏激活时全权处理（零 TTS/音频），返回 True 表示已消费"""
        if not self.config.enabled or not self.config.qq_enabled:
            return False
        if not text or not text.strip():
            return False
        key = self.state.private_key(str(user_id or ""))
        if not self.state.is_active(key):
            return False
        qq_context = {"message_type": "private", "user_id": str(user_id), "target_id": str(user_id)}
        self._route(key, "", text.strip(), qq_context=qq_context)
        return True

    def route_qq_group(self, group_id, user_id, text):
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
        self._route(key, "", text.strip(), qq_context=qq_context)
        return True

    # ==================== 核心路由 ====================
    def _route(self, key, username, text, qq_context):
        """判定 + 分支。voice 返回 consumed/pass；qq 内部已处理"""
        # 关键词兜底（强退出/强重报）
        if self._is_giveup_kw(text):
            self._end_game(key, username, text, mode="give_up", qq_context=qq_context)
            return ROUTE_CONSUMED
        if self._is_repeat_kw(text):
            self._announce_surface(key, username, qq_context)
            return ROUTE_CONSUMED

        puzzle = self.state.get_puzzle(key)
        history = self.state.get_history(key)
        result = judge(puzzle, username, text, history)

        if result.get("repeat"):
            self._announce_surface(key, username, qq_context)
            return ROUTE_CONSUMED
        if result.get("give_up"):
            self._end_game(key, username, text, mode="give_up", qq_context=qq_context)
            return ROUTE_CONSUMED
        if result.get("solved"):
            self._end_game(key, username, text, mode="solved", qq_context=qq_context)
            return ROUTE_CONSUMED

        # 普通猜测
        if qq_context is not None:
            self._host_reply_qq(key, username, text, qq_context)
            return ROUTE_CONSUMED
        self.state.record_turn(key, "user", text)
        return ROUTE_PASS

    # ==================== 开始游戏 ====================
    def _start_game(self, key, username, difficulty, qq_context):
        text = f"用户想玩海龟汤，难度：{difficulty or '由你决定'}"
        puzzle = generate(username, text, difficulty)
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
        self._save_memory("assistant", opening, username)
        self._save_ltmem("assistant", opening, username)
        return "已开始"

    # ==================== 重报汤面 ====================
    def _announce_surface(self, key, username, qq_context):
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
        self._save_memory("assistant", text, username)
        self._save_ltmem("assistant", text, username)

    # ==================== 结束游戏 ====================
    def _end_game(self, key, username, text, mode, qq_context):
        puzzle = self.state.get_puzzle(key)
        reply = self._build_end_text(puzzle, username, mode)
        if qq_context is not None:
            self._send_qq(qq_context, reply)
        else:
            self._speak(reply)
        self._save_memory("assistant", reply, username)
        self._save_ltmem("assistant", reply, username)
        self._archive(key)
        self._remove_cache(key)
        self.state.end(key)

    def _build_end_text(self, puzzle, username, mode):
        if not puzzle:
            return "游戏结束啦"
        title = (puzzle.get("title") or "").strip()
        surface = (puzzle.get("surface") or "").strip()
        answer = (puzzle.get("answer") or "").strip()
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            system = TBoxGetPrompt().get_system_prompt(username, "") or ""
            if mode == "solved":
                instruction = (
                    f"用户刚刚猜中了海龟汤汤底！题目「{title}」，汤面「{surface}」，汤底「{answer}」。"
                    "请以你的角色身份祝贺用户，并公布汤底。"
                )
            else:
                instruction = (
                    f"用户放弃了这局海龟汤。题目「{title}」，汤面「{surface}」，汤底「{answer}」。"
                    "请以你的角色身份公布汤底，语气自然。"
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
        return f"题目「{title}」的汤底是：{answer}"

    # ==================== QQ 主持回答 ====================
    def _host_reply_qq(self, key, username, text, qq_context):
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
                    username or "用户", gid, gname, text, history, "", on_segment,
                )
            else:
                from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM
                reply = TBNapCatLLM().reply(
                    username or "用户",
                    str(qq_context.get("user_id", "")),
                    text,
                    history,
                    on_segment,
                )
            self.state.record_turn(key, "user", text)
            self._save_memory("user", text, username)
            self._save_ltmem("user", text, username)
            if reply:
                self.state.record_turn(key, "assistant", reply)
                self._save_memory("assistant", reply, username)
                self._save_ltmem("assistant", reply, username)
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
    def _save_memory(self, role, content, username=""):
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

    def _save_ltmem(self, role, content, username=""):
        """写长期记忆/用户记忆（AI 输出记 ai_name，用户猜测记 username）"""
        if not content:
            return
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            from func.config.app_config import AppConfig
            bridge = MeowLLMLtMemBridge()
            name = username or "用户"
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
        if cfg.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(cfg)
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
