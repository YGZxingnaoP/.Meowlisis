# -*- coding: utf-8 -*-
"""观影陪伴插件入口：安静陪看、记录观感、按记录答问、结束给一段影评并归档。

本文件不 import 主项目任何模块：插件基线来自本目录 plugin_base.py，
主程序能力（语音/记忆/状态/LLM）全部由框架注入的 ctx 提供。
"""

from .plugin_base import (CAP_ACTIVE_REPLY, CAP_DANMAKU, CAP_DANMAKU_GIFT, CAP_REMINDER,
                          CHANNEL_MAIN, CHANNEL_QQ, ToolboxPlugin, TriggerTool)
from .session import SESSION

HINT = ("- 观影陪伴：用户说「陪我看电影/一起看片/观影模式」→ movie_watch(action=start)；"
        "观影进行中用户问「演到哪了/刚才演什么/剧情/台词说了什么/你觉得怎么样」→ action=ask；"
        "用户说「看完了/结束观影/不看了」→ action=stop。")

DESCRIPTION = (
    "观影陪伴：陪用户一起看电影/剧/片。开始后插件会安静地每隔几分钟截一帧画面、"
    "顺手把听到的台词一起记下（全程不出声），用户提问时再依据这些记录回答，"
    "用户说结束时给一段整体影评并把整场记录归档。"
    "【仅在】用户明确要求「陪我看电影 / 一起看片 / 观影模式」时 action=start；"
    "【仅在】观影进行中用户问「演到哪了 / 刚才演什么 / 剧情 / 台词 / 你觉得怎么样」时 action=ask；"
    "【仅在】用户说「看完了 / 结束观影 / 不看了」时 action=stop；"
    "【严格禁止】普通闲聊、问天气新闻、画画、发消息、单纯讨论某部影片资料时调用。"
)


class MovieWatchTool(TriggerTool):
    name = "movie_watch"
    description = DESCRIPTION
    parameters = {
        "action": {"type": "string", "enum": ["start", "ask", "stop", "status"],
                   "description": "start=开始陪看，ask=回答观影提问，stop=结束并给整体影评，status=查状态"},
        "request": {"type": "string", "description": "用户原话，用于判定意图与回答"},
        "window": {"type": "string",
                   "description": "可选：播放器窗口标题（包含匹配）；不填则绑定开播时的前台窗口"},
    }
    required = []
    trigger_words = ("陪我看电影", "陪我看部电影", "陪我看片", "陪我看剧",
                     "一起看电影", "一起看片", "观影模式", "开始观影")
    prompt_hint = HINT
    channels = (CHANNEL_MAIN, CHANNEL_QQ)

    def handle(self, arguments, ctx):
        SESSION.set_ctx(ctx)
        args = arguments or {}
        action = str(args.get("action") or "").strip()
        text = str(args.get("request") or "").strip()
        window = str(args.get("window") or "").strip()
        status, reply = SESSION.handle_action(action, text, ctx.uid(), window, speak=True)
        ctx.log.info(f"[movie_watch] action={action or 'auto'} status={status}")
        return reply or status

    def handle_qq(self, arguments, qq_context, ctx):
        SESSION.set_ctx(ctx)
        args = arguments or {}
        action = str(args.get("action") or "").strip()
        text = str(args.get("request") or "").strip()
        uid = str((qq_context or {}).get("meowid") or ctx.uid() or "")
        status, reply = SESSION.handle_action(action, text, uid, "", speak=False)
        ctx.log.info(f"[movie_watch] QQ action={action or 'auto'} status={status}")
        if reply:
            target = str((qq_context or {}).get("target_id")
                         or (qq_context or {}).get("user_id") or "")
            try:
                if str((qq_context or {}).get("message_type") or "") == "group":
                    ctx.napcat().send_group_text(target, reply)
                else:
                    ctx.napcat().send_private_text(target, reply)
            except Exception:
                ctx.log.exception("[movie_watch] QQ 发送失败")
        return reply or status

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        return SESSION.route_text(text, meowid, channel)


class Plugin(ToolboxPlugin):
    id = "movie_watch"
    title = "观影陪伴"
    version = "1.1.0"
    default_enabled = True

    def trigger_tools(self):
        return [MovieWatchTool()]

    def prompt_hint(self):
        return HINT

    def state_decl(self):
        return {
            "title": "观影中",
            "caps": {
                CAP_DANMAKU: False,
                CAP_DANMAKU_GIFT: False,
                CAP_ACTIVE_REPLY: False,
                CAP_REMINDER: False,
            },
        }

    def setup(self, ctx):
        SESSION.set_ctx(ctx)
        capture = ctx.config.get("capture") or {}
        try:
            low = int(capture.get("min_interval", 180))
            high = int(capture.get("max_interval", 240))
        except (TypeError, ValueError):
            low, high = 180, 240
        ctx.log.info(f"观影陪伴插件已就绪：截屏间隔 {low}~{high} 秒（随机），"
                     f"静音记录，结束后归档到 plugin_data")

    def teardown(self):
        SESSION.teardown()


PLUGIN = Plugin()
