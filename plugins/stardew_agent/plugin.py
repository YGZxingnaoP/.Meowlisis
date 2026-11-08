# -*- coding: utf-8 -*-
"""星露谷 AI 玩家 0.7.1

主模型负责和用户说话；插件在后台自主游玩、写日志/记忆/日记/计划，
并把游玩状态注入系统提示词。所有记录按存档分开存放。
"""

import re
import threading
import time

from func.toolbox.plugins.sdk import (CHANNEL_MAIN, CHANNEL_QQ, ToolboxPlugin,
                                      TriggerTool)

from .brain import reflect
from .core.bridge import Bridge
from .records import diary, habits, journal, memtips, plans, todos
from .runner.agent import Agent
from .voice import social

DEFAULT_PREFIX = "星露谷"
SEASON_CN = {"spring": "春", "summer": "夏", "fall": "秋", "winter": "冬"}


class StardewPlayTool(TriggerTool):
    name = "stardew_play"
    description = (
        "让「星露谷 AI 玩家」开始或停止自己玩星露谷，或者查看当前状态。"
        "【仅在】用户明确提到星露谷/农场游戏，并且是「去玩 / 开始玩 / 别玩了 / 现在在干嘛」这类意图时调用；"
        "普通聊天、问天气、聊别的游戏都不要调用。"
    )
    parameters = {
        "action": {"type": "string", "enum": ["start", "stop", "status"],
                   "description": "start=开始玩，stop=停止并交还控制，status=看状态"},
        "request": {"type": "string", "description": "用户原话或具体请求"},
    }
    required = []
    prompt_hint = ("- 星露谷 AI 玩家：用户说「去玩星露谷 / 开始玩 / 别玩了 / 星露谷在干嘛」→ "
                   "stardew_play(action=start|stop|status)；用户对角色提具体请求（浇地、去镇上…）→ "
                   "stardew_play(request=原话)，角色会自己判断立刻做还是记成待办。")
    channels = (CHANNEL_MAIN, CHANNEL_QQ)

    def handle(self, arguments, ctx):
        args = arguments or {}
        action = str(args.get("action") or "").strip()
        if action in ("start", "stop", "status"):
            return PLUGIN.play_action(action)
        request = str(args.get("request") or "").strip()
        if request and PLUGIN._agent is not None:
            result = PLUGIN._agent.handle_request(request, by="主人", source="main")
            PLUGIN._feedback_tts(result.get("reply"))
            return result["reply"]
        return PLUGIN.play_action("status")

    def handle_qq(self, arguments, qq_context, ctx):
        qq_context = dict(qq_context or {})
        PLUGIN._remember_target(qq_context)
        args = arguments or {}
        action = str(args.get("action") or "").strip()
        if action in ("start", "stop", "status"):
            text = PLUGIN.play_action(action) or ""
            if text:
                PLUGIN._reply(text)
            return text
        request = str(args.get("request") or "").strip()
        if request and PLUGIN._agent is not None:
            result = PLUGIN._agent.handle_request(
                request, by=qq_context.get("nickname") or "有人", source="qq")
            PLUGIN._reply(result["reply"])
            return result["reply"]
        text = PLUGIN.play_action("status")
        PLUGIN._reply(text)
        return text

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        return PLUGIN.route_text(text, meowid, channel)


class StardewSuggestTool(TriggerTool):
    name = "stardew_suggest"
    description = (
        "用户对星露谷里的角色提出建议、吩咐、催促或询问安排时调用。"
        "例如「去把地浇了」「先去镇上买种子」「别熬夜」「立刻去做」「刚才那个先别弄了」。"
        "不需要用户提到“星露谷”三个字；插件会把这句话交给角色判断，"
        "决定立刻做还是记成待办，并用角色自己的话回复。"
    )
    parameters = {
        "request": {"type": "string", "description": "用户原话或具体请求"},
    }
    required = ["request"]
    prompt_hint = ("- 用户对星露谷角色提建议、吩咐、催促、问安排（浇水、去镇上、钓鱼、别熬夜、"
                   "立刻去做、刚才那个…）→ stardew_suggest(request=用户原话)。"
                   "不需要用户提到“星露谷”；不要自己替角色安排游戏里的具体行动。")
    channels = (CHANNEL_MAIN, CHANNEL_QQ)

    @staticmethod
    def _history(ctx):
        """主链路/QQ 这次调用带进来的最近对话，用来理解“立刻去做”。"""
        try:
            request = ctx.request() or {}
        except Exception:
            return []
        history = request.get("short_memory") or []
        picked = []
        for item in list(history)[-8:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                picked.append({"role": role, "content": content[:300]})
        return picked

    def handle(self, arguments, ctx):
        request = str((arguments or {}).get("request") or "").strip()
        if not request:
            return "你想让我做什么？"
        result = PLUGIN.suggest(request, by="主人", source="main",
                                context=self._history(ctx))
        return result.get("reply") or "我记下了。"

    def handle_qq(self, arguments, qq_context, ctx):
        request = str((arguments or {}).get("request") or "").strip()
        if not request:
            return ""
        result = PLUGIN.suggest(request, by=(qq_context or {}).get("nickname") or "有人",
                                source="qq", context=self._history(ctx))
        text = result.get("reply") or "我记下了。"
        PLUGIN._reply(text)
        return text


class Plugin(ToolboxPlugin):
    id = "stardew_agent"
    title = "星露谷 AI 玩家"
    version = "0.8.1"
    default_enabled = False

    def __init__(self):
        self.ctx = None
        self._bridge = None
        self._prefix = DEFAULT_PREFIX
        self._agent = None
        self._last_target = None
        self._dashboard = None
        self._prompt_originals = {}
        self._tips_cache = ("", 0.0)
        self._plugin_state = None

    def trigger_tools(self):
        return [StardewPlayTool(), StardewSuggestTool()]

    def prompt_hint(self):
        base = ("- 星露谷 AI 玩家：用户说「去玩星露谷 / 开始玩 / 别玩了 / 星露谷在干嘛」时，"
                "调用 stardew_play(action=start|stop|status)；"
                "没明确提到星露谷或农场游戏时不要调用。")
        block = ""
        if self._agent is not None and getattr(self._agent, "playing", False):
            block = self._agent.prompt_block()
        return base + (("\n\n" + block) if block else "")

    def qq_knowledge(self, text, qq_context, stage=""):
        if self._agent is None or not getattr(self._agent, "playing", False):
            return ""
        return self._agent.qq_block()

    def setup(self, ctx):
        self.ctx = ctx
        config = ctx.config or {}
        self._prefix = str(config.get("qq_prefix") or DEFAULT_PREFIX).strip() or DEFAULT_PREFIX
        self._bridge = Bridge(config.get("bridge_url") or "http://127.0.0.1:8766",
                              config.get("timeout") or 5)
        self._agent = Agent(ctx, self._bridge, config, on_say=self._say, on_share=self._share)
        self._agent.start()
        self._start_dashboard()
        try:
            self._plugin_state = ctx.state()
        except Exception:
            self._plugin_state = None
        info = self._bridge.ping()
        ctx.log.info("星露谷插件已初始化：prefix=%s bridge=%s mod=%s"
                     % (self._prefix, self._bridge.base_url,
                        info.get("version") or info.get("reason") or "未知"))

    def teardown(self):
        self._stop_dashboard()
        if self._agent is not None:
            self._agent.stop()
        self._agent = None
        self._bridge = None
        self.ctx = None

    # ---- 面板 ----
    def _start_dashboard(self):
        config = (self.ctx.config or {}) if self.ctx is not None else {}
        if not bool((config.get("dashboard") or {}).get("enabled", True)):
            return
        from .web import DashboardServer
        port = int((config.get("dashboard") or {}).get("port") or 8760)
        self._dashboard = DashboardServer(self, port)
        self._dashboard.start()
        if self.ctx is not None:
            self.ctx.log.info("星露谷面板：http://127.0.0.1:%d/" % port)

    def _stop_dashboard(self):
        if self._dashboard is not None:
            self._dashboard.stop()
            self._dashboard = None

    def dashboard_url(self):
        config = (self.ctx.config or {}) if self.ctx is not None else {}
        port = int((config.get("dashboard") or {}).get("port") or 8760)
        return "http://127.0.0.1:%d/" % port

    # ---- QQ ----
    def route_qq(self, text, qq_context, nickname=""):
        body = (text or "").strip()
        if self.ctx is None or self._bridge is None or self._agent is None:
            return False
        qq_context = dict(qq_context or {})
        if nickname:
            qq_context.setdefault("nickname", nickname)
        self._remember_target(qq_context)

        if body and getattr(self._agent, "pending_question", None):
            answer_text = body
            if answer_text.startswith(self._prefix):
                answer_text = answer_text[len(self._prefix):].strip()
            answer = self._agent.answer_pending(answer_text)
            if answer is not None:
                self._reply(answer.get("reply") or "")
                return True

        if not body.startswith(self._prefix):
            return False
        sub = body[len(self._prefix):].strip()
        if not sub or sub in ("帮助", "help", "?", "？"):
            return False
        head, _, tail = sub.partition(" ")
        head, tail = head.strip(), tail.strip()

        if head in ("习惯", "作息", "habits"):
            self._reply(self._agent.habits_text())
            return True
        if head in ("记忆", "tips", "回想"):
            self._reply(self._agent.tips_text())
            return True
        if head in ("状态", "status", "看看"):
            self._reply(self._agent.status_text())
            return True
        if head in ("开始玩", "去玩", "玩", "开工", "start"):
            text = self.play_action("start")
            if text:
                self._reply(text)
            return True
        if head in ("别玩了", "不玩了", "退出游戏", "停止玩", "下班", "stop", "停"):
            text = self.play_action("stop")
            if text:
                self._reply(text)
            return True
        if head in ("计划", "plan"):
            self._reply(self._agent._day_plan_text() or "今天还没有计划。")
            return True
        if head in ("长线", "规划", "long"):
            data = plans.load_long_term(self._agent.store, self._agent.long_term_config,
                                        self._agent.max_roots) if self._agent.store else None
            self._reply(plans.long_term_text(data) if data else "还没有长线规划。")
            return True
        if head in ("待办", "todo", "todos"):
            self._reply(todos.summary(self._agent.store, self._agent.day_stamp)
                        if self._agent.store else "还没有待办。")
            return True
        if head in ("日记", "diary"):
            day, data = diary.latest(self._agent.store) if self._agent.store else ("", None)
            self._reply(diary.render(data) if data else "还没写过日记。")
            return True
        if head in ("日志", "journal", "记录"):
            if self._agent.store:
                rows = journal.read_day(self._agent.store, self._agent.day_stamp)
                self._reply(journal.render(rows, max_rows=40) or "今天还没有日志。")
            else:
                self._reply("还没读到存档。")
            return True
        if head in ("网页", "面板", "dashboard", "web"):
            self._reply(self.dashboard_url())
            return True
        if head in ("改名", "起名", "名字", "name"):
            if not tail:
                self._speak("有人要起名，但还没告诉我要叫什么")
            else:
                ok, message = self._agent.set_pending_name(tail)
                self._reply(message)
            return True
        if head in ("建议", "提议", "suggest", "去做", "go", "执行"):
            if not tail:
                self._speak("有人让我去做事，但没说做什么")
            else:
                result = self._agent.handle_request(tail, by=qq_context.get("nickname") or "",
                                                    source="qq")
                self._reply(result["reply"])
            return True
        if head in ("去", "move", "walk"):
            parts = tail.split()
            if len(parts) >= 2 and parts[0].lstrip("-").isdigit() and parts[1].lstrip("-").isdigit():
                self._speak("准备走到 %d,%d" % (int(parts[0]), int(parts[1])))
                self._spawn(lambda: self._bridge.call("move_to", x=int(parts[0]), y=int(parts[1])))
                return True
            return False
        if head in ("睡", "睡觉", "sleep"):
            ok, message = self._agent.request_sleep()
            self._reply(message)
            return True
        if head in ("暂停", "pause"):
            self._agent.pause()
            self._speak("先停下来")
            return True
        if head in ("继续", "恢复", "resume"):
            self._agent.resume()
            self._speak("继续干活")
            return True
        if head in ("社交", "social"):
            self._reply(social.digest(self.ctx, self._agent.persona) if not tail
                        else "已留言：" + tail)
            if tail:
                social.post(self.ctx, self._agent.persona, tail, kind="say")
            return True
        if head in ("说", "say"):
            self._agent.say(tail or "……", force=True)
            return True

        result = self._agent.handle_request(sub, by=qq_context.get("nickname") or "",
                                            source="qq")
        self._reply(result["reply"])
        return True

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        body = str(text or "").strip()
        if self._agent is None or not body.startswith(self._prefix):
            return False
        sub = body[len(self._prefix):].strip()
        if not sub:
            return False
        head, _, tail = sub.partition(" ")
        head, tail = head.strip(), tail.strip()
        if head in ("状态", "status", "看看"):
            self._say(self._agent.status_text())
            return True
        if head in ("开始玩", "去玩", "玩", "开工", "start"):
            self.play_action("start")
            self._speak("开始今天的农场生活")
            return True
        if head in ("别玩了", "不玩了", "下班", "stop", "停"):
            self.play_action("stop")
            self._speak("停下手里的活")
            return True
        if head in ("睡", "睡觉", "sleep"):
            _, message = self._agent.request_sleep()
            self._say(message)
            return True
        if tail:
            result = self._agent.handle_request(sub, by=str(meowid or "观众"), source="live")
            self._say(result["reply"])
            return True
        return False

    # ---- 用户建议：交给插件自己的角色判断，并让她自己回一句 ----
    def suggest(self, request, by="", source="main", context=None):
        request = str(request or "").strip()
        if not request:
            return {"mode": "refuse", "reply": "你想让我做什么？"}
        if self._agent is None:
            return {"mode": "refuse", "reply": "星露谷插件还没初始化。"}
        state = self._agent._read_state()
        if not state.get("ok") or not state.get("ready"):
            return {"mode": "refuse", "reply": "游戏还没开，等开了再说。"}
        self._agent.state = state
        self._agent.state_text = str(state.get("text") or "")
        self._agent._ensure_world(state)
        if not self._agent.day_stamp:
            self._agent._check_day(state)
        result = self._agent.handle_request(request, by=by, source=source, context=context)
        reply = str(result.get("reply") or "").strip()
        # QQ 由 handle_qq 的 _reply 统一发，避免双声；主聊天/面板由插件自己说
        if reply and source != "qq":
            self._say(reply)
        return result

    # ---- 开始 / 停止 ----
    def play_action(self, action):
        if self._agent is None or self._bridge is None:
            return "星露谷插件还没初始化。"
        action = str(action or "status").strip().lower()
        if action in ("start", "开始", "开始玩", "play"):
            if not self._bridge.ping().get("ok"):
                return "游戏没开或者还没读档，我进不去。"
            if not self._bridge.state().get("ready"):
                return "游戏在标题画面，还没读档。"
            self._agent.start_play()
            if self._plugin_state is not None:
                self._plugin_state.enter()
            return ""
        if action in ("stop", "停", "停止", "别玩了"):
            self._agent.stop_play()
            if self._plugin_state is not None:
                self._plugin_state.exit()
            return ""
        return self._agent.status_text()

    # ---- 发送 / 分享 ----
    def _spawn(self, fn):
        def run():
            try:
                fn()
            except Exception as exc:
                if self.ctx is not None:
                    self.ctx.log.warning("星露谷后台动作失败：%s" % exc)

        threading.Thread(target=run, name="stardew_action", daemon=True).start()

    def _remember_target(self, qq_context):
        if str(qq_context.get("message_type", "")) == "group":
            group_id = str(qq_context.get("group_id") or qq_context.get("target_id") or "")
            if group_id:
                self._last_target = ("group", group_id)
        else:
            user_id = str(qq_context.get("user_id") or qq_context.get("target_id") or "")
            if user_id:
                self._last_target = ("private", user_id)

    def _share(self, text, image_path=""):
        config = (self.ctx.config or {}) if self.ctx is not None else {}
        share = config.get("share") or {}

        def as_list(value):
            if value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                return [str(item).strip() for item in value if str(item).strip()]
            return [part.strip() for part in re.split(r"[,，;]", str(value)) if part.strip()]

        targets = [("group", g) for g in as_list(share.get("groups"))]
        targets += [("private", u) for u in as_list(share.get("users"))]
        if not targets:
            if image_path:
                self._send_image(image_path)
            self._send(text)
            return
        napcat = self.ctx.napcat()
        for kind, target in targets:
            try:
                if image_path:
                    if kind == "group":
                        napcat.send_group_image(target, image_path)
                    else:
                        napcat.send_private_image(target, image_path)
                if kind == "group":
                    napcat.send_group_text(target, text)
                else:
                    napcat.send_private_text(target, text)
            except Exception as exc:
                self.ctx.log.warning("星露谷分享失败：%s" % exc)

    def _feedback_tts(self, text):
        config = (self.ctx.config or {}) if self.ctx is not None else {}
        if not text or not bool((config.get("broadcast") or {}).get("tts")):
            return
        try:
            self.ctx.tts().send_stream(str(text), source="stardew")
        except Exception:
            pass

    def _speak(self, event):
        if self._agent is None:
            return ""
        text = reflect.speak(self._agent.ctx, self._agent.state, event,
                             self._agent.persona, self._agent.traits)
        self._reply(text)
        return text

    def _reply(self, text):
        self._send(text)

    def _say(self, text):
        self._send(text)
        config = (self.ctx.config or {}) if self.ctx is not None else {}
        if bool((config.get("broadcast") or {}).get("tts")):
            try:
                self.ctx.tts().send_stream(str(text or ""), source="stardew")
            except Exception:
                pass

    def _send(self, text):
        if self.ctx is None or not text or self._last_target is None:
            return
        kind, target = self._last_target
        try:
            napcat = self.ctx.napcat()
            if kind == "group":
                napcat.send_group_text(target, text)
            else:
                napcat.send_private_text(target, text)
        except Exception as exc:
            self.ctx.log.warning("星露谷回复失败：%s" % exc)

    def _send_image(self, path):
        if self.ctx is None or not path or self._last_target is None:
            return
        kind, target = self._last_target
        try:
            napcat = self.ctx.napcat()
            if kind == "group":
                napcat.send_group_image(target, path)
            else:
                napcat.send_private_image(target, path)
        except Exception as exc:
            self.ctx.log.warning("星露谷发图失败：%s" % exc)


PLUGIN = Plugin()
