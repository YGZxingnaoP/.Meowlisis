from func.toolbox.plugins.sdk import ToolboxPlugin, TriggerTool

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

    def handle(self, arguments, ctx):
        """语音/弹幕触发：开始或续读"""
        SESSION.set_ctx(ctx)
        args = arguments or {}
        username = str((self.context or {}).get("username") or "")
        request = str(args.get("request") or "")
        book = str(args.get("book") or "")
        mode = str(args.get("mode") or "read")
        return SESSION.start(request, book, mode, username)

    def route_text(self, text, username=""):
        """会话拦截：朗读中打断 / 窗口内续读"""
        return SESSION.route_text(text, username)


class Plugin(ToolboxPlugin):
    id = "epub_reader"
    title = "读书助手"
    version = "1.0.0"
    default_enabled = True

    def trigger_tools(self):
        """返回触发型工具列表"""
        return [ReadBookTool()]

    def prompt_hint(self):
        """返回意图分析引导文案"""
        return "- 读书助手：用户想听书/朗读小说/读轻小说/继续读某本书 → 调用 read_book。"

    def state_decl(self):
        """读书状态声明（标准接口）：不读弹幕 + 暂停主动回复计时

        其余能力位保持默认允许：礼物/舰长照常播报、待办提醒照常触发、
        语音闲聊不拦截（沿用原打断逻辑）。
        """
        try:
            from func.pipeline.plugins_state import CAP_DANMAKU, CAP_ACTIVE_REPLY
            return {
                "title": "读书中",
                "caps": {CAP_DANMAKU: False, CAP_ACTIVE_REPLY: False},
            }
        except Exception:
            return {}

    def setup(self, ctx):
        """插件初始化"""
        SESSION.set_ctx(ctx)


PLUGIN = Plugin()
