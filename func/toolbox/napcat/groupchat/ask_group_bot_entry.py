# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/ask_group_bot_entry.py
# napcat 父级入口工具：向指定群的机器人（如幻梦）发指令。
# 用户主动命令时触发（如「去xx群艾特幻梦」「让幻梦玩今日老婆」）。

from typing import List, Dict, Optional

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.groupchat.ask_group_bot import TBAskGroupBot
from func.toolbox.napcat.active_sender.get_grouplist import TBGetGroupList


class TBAskGroupBotEntry:
    """父级入口 napcat_ask_bot：用户说「去xx群艾特/叫/让幻梦做xx」时调用。

    - bot_name  ：机器人名（如 幻梦），明确指定用哪个机器人；
    - group_name：群名（模糊匹配群列表）或纯数字群号，明确指定去哪个群；
    - command   ：明确指定执行哪个指令（从已知名单选）。
    """

    TOOL_NAME = "napcat_ask_bot"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self.bot = TBAskGroupBot()

    def set_username(self, username: str):
        """父级注入当前用户（本工具暂不需要，保持接口兼容）"""
        pass

    def _cmd_map(self) -> Dict[str, List[str]]:
        """静态默认名单 ∪ observe 动态缓存，按机器人名返回指令列表。"""
        return self.bot.merged_commands()

    def _cmd_desc(self) -> str:
        cmap = self._cmd_map()
        if not cmap:
            return "默认发 菜单 获取"
        return "；".join(f"{name}: {'、'.join(cmds)}" for name, cmds in cmap.items())

    def build_tools(self) -> List[dict]:
        cmd_desc = self._cmd_desc()
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "向指定QQ群的机器人（如幻梦）发送指令，触发它回复。"
                    "用户说「去xx群艾特/叫/让幻梦做xx」时调用。"
                    f"已知机器人及指令名单：{cmd_desc}。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "bot_name": {
                            "type": "string",
                            "description": "机器人名，如 幻梦",
                        },
                        "group_name": {
                            "type": "string",
                            "description": "目标群：群名（模糊匹配群列表）或纯数字群号",
                        },
                        "command": {
                            "type": "string",
                            "description": f"要执行的指令，从名单中选择：{cmd_desc}",
                        },
                    },
                    "required": ["bot_name", "group_name", "command"],
                },
            },
        }]

    def _resolve_group_id(self, group_name: str) -> Optional[str]:
        """群名 → 群号：纯数字直接当群号，否则按群名模糊匹配群列表。"""
        name = str(group_name or "").strip()
        if not name:
            return None
        if name.isdigit():
            return name
        try:
            groups = TBGetGroupList().get()
        except Exception:
            self.log.exception("获取群列表失败")
            groups = []
        for g in groups:
            if not isinstance(g, dict):
                continue
            gname = str(g.get("group_name", "") or "")
            if name in gname or gname in name:
                return str(g.get("group_id", ""))
        return None

    def dispatch(self, name: str, arguments: Dict) -> str:
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        args = arguments or {}
        bot_name = str(args.get("bot_name", "") or "").strip()
        group_name = str(args.get("group_name", "") or "").strip()
        command = str(args.get("command", "") or "").strip()
        if not bot_name or not group_name or not command:
            return "缺少参数：bot_name / group_name / command"

        group_id = self._resolve_group_id(group_name)
        if not group_id:
            return f"未找到群「{group_name}」，请确认群名或直接给群号"
        return self.bot.execute_forced(group_id, bot_name, command)
