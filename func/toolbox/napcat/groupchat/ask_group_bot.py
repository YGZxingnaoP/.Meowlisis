# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/ask_group_bot.py
# napcat 独有工具：向群机器人（如幻梦）发指令。
# 仅挂在 napcat 群聊 LLM 上使用，禁止注册到 toolbox 父级 analysis。

import re
import threading
from typing import List, Dict, Optional
from urllib.parse import unquote

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.config import TBNapCatConfig

# 静态默认指令名单：幻梦「娱乐菜单」的可执行 command（AI 一开始就知道能玩什么）。
# 与 observe 动态缓存的指令合并后展示给 LLM，避免 AI 卡在「先发 /菜单」却拿不到指令。
DEFAULT_COMMANDS = {
    "幻梦": ["剧情模式", "homo", "打卡", "运势", "今日老婆", "今日梦境",
             "今日属性", "今日超能力", "随机图", "智慧之书", "随机Say"],
}


@singleton
class TBAskGroupBot:
    """向群机器人（如幻梦）发指令的 napcat 独有工具。

    - 指令格式：@机器人名 空格 /指令，例如 @幻梦 /菜单（注意 @ 与 /指令 之间有空格）
    - 触发条件（由群聊 AI 根据 tool description 判断）：
        1) 之前群里已经有其它用户用过该机器人（判定依据：幻梦是否发过言）；
        2) 当前群聊没有明显话题。
    - 本工具只负责发送指令，不阻塞等待回复；机器人回复会以群消息自然进入处理链。
    - 指令名单：从幻梦发的 markdown 菜单消息中解析 command=XXX 缓存到内存（不写文件）。
    """

    TOOL_NAME = "ask_group_bot"

    # 从 markdown 里提取 mqqapi://aio/inlinecmd?command=XXX 的指令
    CMD_RE = re.compile(r"command=([^&\s]+)")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self._lock = threading.Lock()
        # 运行时状态（仅内存，不写文件）
        # (group_id, bot_qq) -> 是否发过言
        self._bot_used: Dict[tuple, bool] = {}
        # (group_id, bot_qq) -> set(指令名)
        self._bot_commands: Dict[tuple, set] = {}

    # ==================== 观察：幻梦是否发过言 + 提取指令名单 ====================
    def observe(self, group_id: str, user_id: str, raw_message, is_bot: bool):
        """在收到群消息时调用：仅当 is_bot=True（幻梦发言）时，标记 used 并提取指令名单。

        按 (group_id, bot_qq) 独立判定，避免跨群污染。
        """
        if not is_bot:
            return
        uid = str(user_id or "")
        gid = str(group_id or "")
        # 确认该 QQ 是配置的机器人
        bots = self.config.group_bots or {}
        is_known_bot = any(str(qq) == uid for qq in bots.values())
        if not is_known_bot:
            return
        key = (gid, uid)
        with self._lock:
            self._bot_used[key] = True
            if key not in self._bot_commands:
                self._bot_commands[key] = set()
            self._bot_commands[key].update(self._extract_commands(raw_message))

    def was_used(self, group_id: str, bot_qq: str) -> bool:
        """查询某群某机器人是否已发过言（= 已被其它用户用过）"""
        with self._lock:
            return self._bot_used.get((str(group_id or ""), str(bot_qq)), False)

    def known_commands(self, group_id: str, bot_qq: str) -> List[str]:
        """获取某群某机器人已知的指令名单（按提取顺序稳定返回）"""
        with self._lock:
            return sorted(self._bot_commands.get((str(group_id or ""), str(bot_qq)), set()))

    def all_known_commands(self) -> Dict[str, List[str]]:
        """返回 {机器人名: 指令列表}（跨群汇总，供 tool description 动态展示）"""
        bots = self.config.group_bots or {}
        result = {}
        with self._lock:
            for name, qq in bots.items():
                cmds = set()
                for (gid, bid), cs in self._bot_commands.items():
                    if bid == str(qq):
                        cmds.update(cs)
                if cmds:
                    result[str(name)] = sorted(cmds)
        return result

    def merged_commands(self) -> Dict[str, List[str]]:
        """静态默认名单 ∪ observe 动态缓存（跨群汇总，按机器人名）。"""
        bots = self.config.group_bots or {}
        dynamic = self.all_known_commands()
        result = {}
        for name in bots:
            cmds = []
            seen = set()
            for c in list(DEFAULT_COMMANDS.get(name, [])) + list(dynamic.get(name, [])):
                if c and c not in seen:
                    seen.add(c)
                    cmds.append(c)
            result[str(name)] = cmds
        return result

    @classmethod
    def _extract_commands(cls, raw_message) -> List[str]:
        """从消息段（含 markdown）里提取 command=XXX 指令名单"""
        result = []
        for seg in raw_message or []:
            if not isinstance(seg, dict):
                continue
            data = seg.get("data") or {}
            text = str(data.get("content", "") or data.get("text", "") or "")
            for m in cls.CMD_RE.finditer(text):
                cmd = unquote(m.group(1)).strip()
                if cmd and cmd not in result:
                    result.append(cmd)
        return result

    # ==================== 解析机器人 QQ ====================
    def resolve_bot_qq(self, bot_name: str) -> Optional[str]:
        """按机器人名解析 QQ：group_bots 映射优先，其次按 QQ 值/纯数字"""
        name = str(bot_name or "").strip()
        if not name:
            return None
        bots = self.config.group_bots or {}
        if name in bots:
            return str(bots[name])
        for k, v in bots.items():
            if str(v) == name:
                return str(v)
        if name.isdigit():
            return name
        return None

    # ==================== tool schema ====================
    def build_tools(self) -> List[dict]:
        """构建 ask_group_bot 工具 schema（供 napcat 群聊 LLM 使用，不进 toolbox）"""
        # 已知指令名单 = 静态默认名单 ∪ observe 动态缓存，让 AI 知道有哪些指令可用
        cmd_hint = ""
        merged = self.merged_commands()
        if merged:
            lines = [f"- {name}: {'、'.join(cmds)}" for name, cmds in merged.items()]
            cmd_hint = "\n已知指令名单（可从中选择）：\n" + "\n".join(lines)
        else:
            cmd_hint = "\n暂无已知指令名单，可先发送 /菜单 获取。"

        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "向群里的机器人（如幻梦）发送指令，触发它回复，用于活跃气氛或提供娱乐内容。"
                    "指令格式为「@机器人名 空格 指令」，例如「@幻梦 今日老婆」（注意 @ 与指令之间有空格，指令不加斜杠）。"
                    "仅在同时满足以下两个条件时才使用本工具："
                    "1) 之前群里已经有其它用户用过该机器人（即该机器人之前发过言）；"
                    "2) 当前群聊没有明显话题（大家只是在闲聊或冷场）。"
                    + cmd_hint
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "group_id": {"type": "string", "description": "群号"},
                        "bot_name": {"type": "string", "description": "机器人名，如 幻梦"},
                        "command": {"type": "string", "description": "要执行的指令，如 菜单、今日老婆（不加斜杠）"},
                    },
                    "required": ["group_id", "bot_name", "command"],
                },
            },
        }]

    def dispatch(self, name: str, arguments: dict) -> str:
        if name == self.TOOL_NAME:
            return self.execute(
                arguments.get("group_id", ""),
                arguments.get("bot_name", ""),
                arguments.get("command", ""),
            )
        return f"错误：未知工具 {name}"

    # ==================== 执行 ====================
    def execute(self, group_id: str, bot_name: str, command: str) -> str:
        if not group_id or not bot_name or not command:
            return "发送失败：缺少群号 / 机器人名 / 指令"
        bot_qq = self.resolve_bot_qq(bot_name)
        if not bot_qq:
            return f"未找到机器人「{bot_name}」，请先在 napcat.group_bots 配置其 QQ 号"

        # 软校验：该群该机器人是否已发过言（= 已被其它用户用过）
        if not self.was_used(group_id, bot_qq):
            return (
                f"暂不向「{bot_name}」发指令：它在这个群里还没发过言（说明群里还没有人用过它）。"
            )

        cmd = str(command).strip()
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            TBNapCatCore().call_action_sync("send_group_msg", {
                "group_id": int(group_id),
                "message": [
                    {"type": "at", "data": {"qq": bot_qq}},
                    {"type": "text", "data": {"text": " " + cmd}},
                ],
            })
            self.log.info(f"[ask_group_bot] 已 @{bot_name}({bot_qq}) 发送指令：{cmd}")
            return f"已向「{bot_name}」发送指令：{cmd}（等待它在群里回复）"
        except Exception:
            self.log.exception("发送群机器人指令失败")
            return "发送群机器人指令失败"

    def execute_forced(self, group_id: str, bot_name: str, command: str) -> str:
        """父级主动触发：用户明确要求时，不校验 was_used（幻梦没发过言也发）。

        指令不加斜杠前缀，与幻梦菜单里的 command（如 今日老婆）保持一致。
        """
        if not group_id or not bot_name or not command:
            return "发送失败：缺少群号 / 机器人名 / 指令"
        bot_qq = self.resolve_bot_qq(bot_name)
        if not bot_qq:
            return f"未找到机器人「{bot_name}」，请先在 napcat.group_bots 配置其 QQ 号"

        cmd = str(command).strip()
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            TBNapCatCore().call_action_sync("send_group_msg", {
                "group_id": int(group_id),
                "message": [
                    {"type": "at", "data": {"qq": bot_qq}},
                    {"type": "text", "data": {"text": " " + cmd}},
                ],
            })
            self.log.info(f"[ask_group_bot:forced] 已 @{bot_name}({bot_qq}) 发送指令：{cmd}")
            return f"已向「{bot_name}」发送指令：{cmd}（等待它在群里回复）"
        except Exception:
            self.log.exception("发送群机器人指令失败")
            return "发送群机器人指令失败"
