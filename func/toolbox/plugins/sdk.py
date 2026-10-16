import contextvars
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

CHANNEL_MAIN = "main"
CHANNEL_QQ = "qq"
CHANNELS = (CHANNEL_MAIN, CHANNEL_QQ)

_REQUEST = contextvars.ContextVar("plugin_request", default={})


def begin_request(meowid="", **rest):
    _REQUEST.set({"meowid": str(meowid or ""), **rest})


def update_request(**kw):
    _REQUEST.set({**_REQUEST.get(), **kw})


def current_request():
    return _REQUEST.get()


def current_uid():
    return str(_REQUEST.get().get("meowid") or "")


class JsonStore:
    def __init__(self, path):
        self.path = path

    def load(self, default):
        if not os.path.isfile(self.path):
            return default
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


class PluginContext:
    def __init__(self, plugin_id, log, config):
        self.id = plugin_id
        self.log = log
        self.config = config or {}
        self.dir = os.path.join(ROOT, "plugins", plugin_id)

    def uid(self):
        return current_uid()

    def request(self):
        return current_request()

    def display_name(self, uid=None):
        from func.pipeline.id_signup import display_name
        return display_name(current_uid() if uid is None else uid)

    def root(self):
        return ROOT

    def plugin_dir(self):
        return self.dir

    def path(self, *parts):
        return os.path.join(ROOT, *[str(p) for p in parts])

    def resolve(self, path):
        p = os.path.expanduser(str(path))
        return os.path.normpath(p if os.path.isabs(p) else os.path.join(ROOT, p))

    def data_dir(self, per_user=None):
        uid = current_uid() if per_user is None else str(per_user)
        base = os.path.join(ROOT, "character", "plugin_data", self.id)
        return os.path.join(base, uid) if uid else base

    def store(self, name, per_user=None):
        return JsonStore(os.path.join(self.data_dir(per_user), name + ".json"))

    def tts(self):
        from func.pipeline.toolbox_tts import ToolboxTtsBridge
        return ToolboxTtsBridge()

    def llm(self):
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

    def prompt(self):
        from func.toolbox.get_prompt import TBoxGetPrompt
        return TBoxGetPrompt()

    def napcat(self):
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        return TBNapCatCore()

    def short_memory(self):
        from func.pipeline.short_memory import ShortMemory
        return ShortMemory()

    def ltmem(self):
        from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
        return MeowLLMLtMemBridge()

    def excuse(self):
        from func.toolbox.excuse import TBExcuse
        return TBExcuse()

    def toolbox(self):
        from func.toolbox.toolbox_core import TBoxCore
        return TBoxCore()

    def ai_name(self):
        from func.config.app_config import AppConfig
        return AppConfig().ai_name

    def state(self):
        from func.pipeline.plugins_state import PluginStateHandle
        from func.toolbox.plugins.manager import PluginManager
        return PluginStateHandle(self.id, PluginManager().state_decl(self.id), self.log)


class TriggerTool:
    name = ""
    description = ""
    parameters = {}
    required = []
    prompt_hint = ""
    trigger_words = ()
    channels = CHANNELS

    @property
    def uid(self):
        return current_uid()

    def build_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": list(self.required),
                },
            },
        }

    def handle(self, arguments, ctx):
        raise NotImplementedError

    def handle_qq(self, arguments, qq_context, ctx):
        raise NotImplementedError

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        return False


class InterfaceTool:
    name = ""
    description = ""

    def call(self, ctx, **kwargs):
        raise NotImplementedError


class ToolboxPlugin:
    id = ""
    title = ""
    version = "1.0.0"
    default_enabled = True

    def trigger_tools(self):
        return []

    def interface_tools(self):
        return []

    def prompt_hint(self):
        return ""

    def state_decl(self):
        return {}

    def setup(self, ctx):
        pass

    def teardown(self):
        pass
