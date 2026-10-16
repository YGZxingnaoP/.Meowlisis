from func.pipeline.plugins_state import CAP_ACTIVE_REPLY, CAP_DANMAKU
from func.toolbox.plugins.sdk import CHANNEL_MAIN, ToolboxPlugin, TriggerTool

from .session import SESSION


class ReadBookTool(TriggerTool):
    name = "read_book"
    description = (
        "朗读/听书：读一本小说或轻小说给用户听，会自动按章节朗读、做剧情概括与点评。"
        "【仅在用户明确要求读书/读小说/读轻小说/朗读/听书/念书/继续读某本书时调用】"
        "【严格禁止】普通闲聊、问答、查天气新闻、画画、发消息等一律不调用。"
        "调用后立即返回，无需等待朗读结束。"
    )
    parameters = {
        "request": {"type": "string", "description": "用户原话需求"},
        "book": {"type": "string", "description": "书名或关键词，可省略"},
        "mode": {"type": "string", "enum": ["read", "resume"], "description": "读新书或续读，默认 read"},
    }
    required = []
    trigger_words = ("读书", "读小说", "读轻小说", "朗读", "念书", "读给我听", "听书", "说书")
    prompt_hint = "- 读书助手：用户想听书/朗读小说/读轻小说/继续读某本书 → 调用 read_book。"
    channels = (CHANNEL_MAIN,)

    def handle(self, arguments, ctx):
        SESSION.set_ctx(ctx)
        args = arguments or {}
        return SESSION.start(str(args.get("request") or ""), str(args.get("book") or ""),
                             str(args.get("mode") or "read"), self.uid)

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        return SESSION.route_text(text, meowid, channel)


class Plugin(ToolboxPlugin):
    id = "epub_reader"
    title = "读书助手"
    version = "2.0.0"
    default_enabled = True

    def trigger_tools(self):
        return [ReadBookTool()]

    def prompt_hint(self):
        return "- 读书助手：用户想听书/朗读小说/读轻小说/继续读某本书 → 调用 read_book。"

    def state_decl(self):
        return {"title": "读书中", "caps": {CAP_DANMAKU: False, CAP_ACTIVE_REPLY: False}}

    def setup(self, ctx):
        SESSION.set_ctx(ctx)


PLUGIN = Plugin()
