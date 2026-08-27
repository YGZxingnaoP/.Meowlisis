# -*- coding: utf-8 -*-
# func/catbrain/rules_break/rules_break.py
# 内容审查器：判断消息是否含明确色情/露骨，命中则写对应桥接触发原则词注入

import json
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.catbrain.rules_break.config import TBRulesBreakConfig
from func.catbrain.rules_break.port import TBRulesBreakPort


@singleton
class TBRulesBreak:
    """内容审查器：独立 DeepSeek port + tool_choice 强制判断，结果写对应桥接。

    - 主线程结果写 MsgRuleBreakBridge（单会话）；
    - QQ 结果写 ToolboxRuleBreakBridge（按 session_key 隔离）。
    - explicit=True 表示命中色情/露骨 → SystemPromptBridge 注入原则词。
    """

    TOOL_NAME = "check_explicit_content"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBRulesBreakConfig()
        self.port = TBRulesBreakPort(self.config)

    # ==================== 工具定义 ====================
    def build_tools(self) -> List[Dict]:
        """构建审查工具定义：输出是否含明确色情/露骨"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "判断输入消息是否包含明确色情、露骨或性行为描写内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "explicit": {
                            "type": "boolean",
                            "description": "是否包含明确色情/露骨内容（true=有，false=无）"
                        }
                    },
                    "required": ["explicit"]
                }
            }
        }]

    def build_tool_choice(self) -> Dict:
        """强制调用审查工具"""
        return {"type": "function", "function": {"name": self.TOOL_NAME}}

    # ==================== 审查 ====================
    def check(self, content: str, short_memory: List[dict] = None) -> bool:
        """审查一段文本是否含明确色情/露骨，返回 bool（true=命中）。

        short_memory: 短期记忆（[{"role","content"}]），取最近 3 条作为上下文辅助判断。
        """
        if not content or not str(content).strip():
            return False
        if not self.port or not self.port.client:
            return False
        context_text = ""
        if short_memory:
            recent = [m for m in short_memory if isinstance(m, dict)][-3:]
            lines = [f"{m.get('role', '')}: {m.get('content', '')}" for m in recent]
            context_text = "之前的对话上下文：\n" + "\n".join(lines) + "\n\n"
        messages = [{
            "role": "user",
            "content": (
                context_text +
                "请审查以下消息是否包含明确色情、露骨或性行为描写内容，"
                "并调用工具输出结果：\n\n" + str(content)
            )
        }]
        try:
            resp = self.port.chat(messages, tools=self.build_tools(),
                                  tool_choice=self.build_tool_choice())
            return self._parse_explicit(resp)
        except Exception:
            self.log.exception("rules_break 审查异常")
            return False

    @staticmethod
    def _parse_explicit(resp) -> bool:
        """从 tool_calls 解析 explicit 字段"""
        if not resp or not getattr(resp, "choices", None):
            return False
        msg = resp.choices[0].message
        for tc in (msg.tool_calls or []):
            if tc.function.name == TBRulesBreak.TOOL_NAME:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    return bool(args.get("explicit", False))
                except Exception:
                    return False
        return False

    # ==================== 好感度门槛 ====================
    def _affinity(self, username: str) -> int:
        """读取用户档案好感度（character/info/users_info/{username}_latest.json）"""
        try:
            from func.catbrain.UserMemory.load_usrmem import MeowLoadUserMemory
            data = MeowLoadUserMemory().load(username)
            affinity = data.get("affinity", 0)
            if isinstance(affinity, (int, float)):
                return int(affinity)
        except Exception:
            pass
        return 0

    def _allow(self, username: str) -> bool:
        """好感度门槛：仅好感度 > affinity_min 才允许触发原则词注入"""
        return self._affinity(username) > self.config.affinity_min

    # ==================== 情绪覆盖（破甲词触发） ====================
    @staticmethod
    def _write_emotion_file(path: str, emotion: str):
        """把情绪缓存文件的 emotion 字段改为指定值（缺失则补默认结构）"""
        import os
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        data["emotion"] = emotion
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _force_love_emotion(self):
        """破甲词触发时，把情绪缓存强制改为 love（文件 + 内存），保证构建提示词前心情为 love"""
        # napcat 在线情绪（QQ 私聊/群聊构建提示词读内存 emotion）
        try:
            from func.toolbox.napcat.emotion_bridge import TBNapCatEmotionBridge
            TBNapCatEmotionBridge().set_emotion("love")
        except Exception:
            pass
        self._write_emotion_file(".temp/latest_emotion_online.json", "love")
        # 主线程情绪
        try:
            from func.pipeline.llm_emotion import LLMEmotionBridge
            LLMEmotionBridge().set_emotion("love")
        except Exception:
            pass
        self._write_emotion_file(".temp/latest_emotion.json", "love")

    # ==================== 入口：审查 + 写桥接 ====================
    def check_and_store_msg(self, username: str, content: str, short_memory: List[dict] = None) -> bool:
        """主线程审查：写 MsgRuleBreakBridge（开关关闭或好感度不足时显式清零，避免残留）"""
        from func.pipeline.msg_rulebreak import MsgRuleBreakBridge
        if not self.config.enabled_msg or not self._allow(username):
            MsgRuleBreakBridge().set_explicit(False)
            return False
        explicit = self.check(content, short_memory)
        MsgRuleBreakBridge().set_explicit(explicit)
        if explicit:
            self.log.info(
                f"[原则词触发] 主线程命中色情/露骨，用户={username}，内容={str(content)[:40]}"
            )
            self._force_love_emotion()
        return explicit

    def check_and_store_qq(self, session_key: str, username: str, content: str, short_memory: List[dict] = None) -> bool:
        """QQ 审查：写 ToolboxRuleBreakBridge（按 session_key 隔离）"""
        from func.pipeline.toolbox_rulebreak import ToolboxRuleBreakBridge
        if not self.config.enabled_qq or not self._allow(username):
            ToolboxRuleBreakBridge().set_explicit(session_key, False)
            return False
        explicit = self.check(content, short_memory)
        ToolboxRuleBreakBridge().set_explicit(session_key, explicit)
        if explicit:
            self.log.info(
                f"[原则词触发] QQ命中色情/露骨，session={session_key}，用户={username}，内容={str(content)[:40]}"
            )
            self._force_love_emotion()
        return explicit
