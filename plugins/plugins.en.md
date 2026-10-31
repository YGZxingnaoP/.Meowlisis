# Plugin System Manual

> [中文](plugins.md) | English

This directory (the project root `plugins/`) is where toolbox plugins live. The program scans and loads it automatically at startup — no need to touch the main program's code.

## Directory structure

```
plugins/
├── plugins.md           this manual
└── <plugin id>/         one directory per plugin, directory name is the plugin id
    ├── plugin.py        required, plugin entry point
    ├── schema.py        optional, GUI config panel definition (PLUGIN / FIELDS / CARDS)
    ├── config.yml       auto-generated, per-plugin config (filled in from schema defaults)
    ├── card.png         optional, GUI card image
    └── 其它模块.py       optional (other modules)
```

A plugin's own data does **not** live in the plugin directory — see "Data" below.

## Startup loading and switches

At startup the program reads the `plugins` config under the root node of `config.yml`:

```yaml
plugins:
  enabled: true          # master switch; false means plugins are not loaded at all
  dir: ./plugins         # plugin root (relative paths resolve against [main project root], not the process working directory)
  auto_load: true        # whether to scan and load automatically
  fail_fast: false       # whether one plugin failing to load aborts startup
  disabled: []           # blacklist (by plugin id)

  <plugin id>:           # per-plugin switch and custom config
    enabled: true
    some_key: some_value
```

- Switch precedence: `plugins.enabled` (master) → `plugins.disabled` (blacklist) → `plugins.<id>.enabled` (per plugin; defaults to the plugin's own `default_enabled`).
- If a single plugin fails to load it **only logs and does not block startup**; with `fail_fast: true` it instead raises and aborts.
- If the `plugins` node is absent: enabled by default, scanning `./plugins` automatically.

## plugin.py conventions

You must export either `PLUGIN` (an instance) or `Plugin` (a class subclassing `ToolboxPlugin`). The loader prefers `PLUGIN`, then falls back to `Plugin`.

```python
from func.toolbox.plugins.sdk import (CHANNEL_MAIN, CHANNEL_QQ, ToolboxPlugin, TriggerTool)


class MyTool(TriggerTool):
    name = "my_tool"
    description = "Call only when the user explicitly asks for xxx; do not call otherwise"
    parameters = {"arg1": {"type": "string", "description": "parameter 1"}}
    required = ["arg1"]
    prompt_hint = "- user asks for xxx → call my_tool"
    trigger_words = ("xxx", "do xx")
    channels = (CHANNEL_MAIN,)          # only available on the main chain; not exposed to QQ, not executed there

    def handle(self, arguments, ctx):
        ctx.tts().send_stream("reply text", source="toolbox_my")
        return "ok"

    def handle_qq(self, arguments, qq_context, ctx):
        target = str(qq_context.get("target_id") or "")
        ctx.napcat().send_private_text(target, "reply text")
        return "ok"

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        return False


class Plugin(ToolboxPlugin):
    id = "my_plugin"
    title = "My Plugin"
    default_enabled = True

    def trigger_tools(self):
        return [MyTool()]

    def prompt_hint(self):
        return "[My Plugin] call my_tool when the user wants xxx"

    def qq_knowledge(self, text, qq_context, stage=""):
        return ""

    def setup(self, ctx):
        self.ctx = ctx


PLUGIN = Plugin()
```

## Chains (channel)

The framework has only two chains; `TriggerTool.channels` declares which ones a tool takes part in:

| Constant | Value | Meaning |
|---|---|---|
| `CHANNEL_MAIN` | `"main"` | Main chain: voice / bullet comments, goes through `analysis.py` |
| `CHANNEL_QQ` | `"qq"` | QQ chain, goes through `napcat/analysis/analysis_core.py` |

`channels` defaults to `(CHANNEL_MAIN, CHANNEL_QQ)` — both chains on. Once declared, the **framework** does the filtering for you:

- `trigger_schemas(channel)` only returns that chain's tools → QQ intent analysis **cannot see** tools that don't declare `"qq"`;
- `dispatch_qq()` returns `None` straight away for tools that don't declare `"qq"`, so they never execute.

So "trigger only on the main chain" is just one line, `channels = (CHANNEL_MAIN,)` — **do not** write rejection logic inside `handle_qq`.

## Tool types

### Trigger tools: TriggerTool

Invoked after an LLM decision in "voice intent analysis" or "QQ intent analysis"; can also be hard-triggered by `trigger_words` keywords.

| Member | Description |
|---|---|
| `name` | Tool name, globally unique, no dots |
| `description` | Description for the LLM — be sure to spell out "call only when … / do not call otherwise" |
| `parameters` | JSON Schema properties |
| `required` | List of required parameter names |
| `prompt_hint` | Optional, one line of guidance, automatically appended to both intent-analysis prompts |
| `trigger_words` | Optional, keyword hard trigger (a hit calls the tool, bypassing the LLM) |
| `channels` | Which chains it takes part in; both by default |
| `uid` | **Read-only property**, internal id of the current request (see "Identity contract") |
| `handle(args, ctx)` | Main-chain execution; raises `NotImplementedError` if unimplemented |
| `handle_qq(args, qq_context, ctx)` | QQ-chain execution; raises `NotImplementedError` if unimplemented (no falling back to `handle` any more) |
| `route_text(text, meowid, channel)` | Session interception; returning `True` means this input has been taken over; `False` by default |

### Interface tools: InterfaceTool

Not exposed to the LLM; called internally by name. Implement `call(ctx, **kwargs)` and return the instance from `interface_tools()`:

```python
PluginManager().call_interface("my_probe", deep=True)
```

## QQ knowledge injection: qq_knowledge

`route_qq` takes over a reply; `qq_knowledge` only supplies reference text — it does not take over, send messages, or change main-chain decisions.

```python
from func.toolbox.plugins.sdk import (
    QQ_STAGE_FOLLOWUP_JUDGE, QQ_STAGE_ACTIVE_DECIDE, QQ_STAGE_ACTIVE_REPLY,
)


class Plugin(ToolboxPlugin):
    id = "my_plugin"
    title = "My Plugin"

    def qq_knowledge(self, text, qq_context, stage=""):
        if not text.strip():
            return ""
        if stage == QQ_STAGE_FOLLOWUP_JUDGE:
            return "[reference] ..."   # for follow-up judging only
        if stage in (QQ_STAGE_ACTIVE_DECIDE, QQ_STAGE_ACTIVE_REPLY):
            return "[reference] ..."   # for proactive group replies
        return ""
```

Actual call stages:

| Stage | `stage` | Caller | Meaning |
|---|---|---|---|
| Follow-up judging | `followup_judge` | `TBNapcatFollowupJudge.judge()` | Reference only; `pass/continue` is still decided by the judge |
| Proactive group decision | `active_decide` | `decide` in `_reply_group_active()` | Reference is added to the proactive-reply system prompt |
| Forced proactive reply | `active_reply` | `force` in `_reply_group_active()` | Reference is added to the final reply system prompt |

The `private` / `directed` / `followup_reply` constants are reserved, but the main
project currently does **not** call `qq_knowledge` for them; `route_qq` still handles
those paths.

`qq_context` contains at least:

```python
{
    "channel": "qq",
    "message_type": "group",
    "group_id": "...",
    "group_name": "...",
    "self_id": "...",
    "user_id": "...",        # primary speaker for follow-up/proactive; may be empty
    "nickname": "...",
    "participants": [...],
}
```

Constraints:

- read-only: do not send messages, write memory, or call an LLM;
- return plain reference text, not instructions;
- return an empty string when there is nothing to add;
- multiple plugins are aggregated by `PluginManager.qq_knowledge()` and capped by
  `plugins.qq_knowledge_max_chars` (default 4000);
- return quickly; no network, file scans, or model calls;
- it cannot force a reply, override a follow-up `pass`, or override a proactive `pass`.

## PluginContext capabilities

Plugins reach project capabilities through the injected `ctx`; importing main-program internals directly is discouraged.

### Identity

| Member | Description |
|---|---|
| `ctx.uid()` | Internal id of the current request (`meowid`) — **the only thing the program uses to identify someone** |
| `ctx.request()` | Full context of the current request: `{meowid, text, short_memory, system_prompt}` |
| `ctx.display_name(uid=None)` | uid → display name. **The only legitimate source for display names**; using uid / QQ number as a nickname is forbidden |
| `self.uid` (inside a tool) | Same as above, equivalent to `ctx.uid()` |

### Paths

| Member | Description |
|---|---|
| `ctx.root()` | Main project root directory |
| `ctx.plugin_dir()` | This plugin's directory, `<root>/plugins/<id>` |
| `ctx.path(*parts)` | Absolute path joined under the main project root |
| `ctx.resolve(p)` | Relative path → absolute path (relative to the **main project root**, independent of the process working directory) |

### Data

| Member | Description |
|---|---|
| `ctx.data_dir(per_user=None)` | Plugin data directory, see the conventions below |
| `ctx.store(name, per_user=None)` | Returns a `JsonStore` with `load(default)` / `save(data)`, atomic writes |

**Data directory conventions**:

```
character/plugin_data/<plugin id>/            ← per_user=""   →  plugin-wide data
character/plugin_data/<plugin id>/<uid>/      ← per_user=None →  data for whoever made the current request
                                                per_user=uid  →  data for that specific person
```

⚠️ `per_user=None` is the **default** and follows the current request's uid. To get the plugin-wide directory you **must pass `""` explicitly**.

### Project capabilities

| Member | Description |
|---|---|
| `ctx.id` | Plugin id |
| `ctx.log` | Logger object |
| `ctx.config` | This plugin's config (i.e. the key-values under `plugins.<id>`) |
| `ctx.tts()` | TTS voice bridge, `send_stream(text, source=...)` / `is_busy()` / `interrupt()` |
| `ctx.llm()` | toolbox LLM port, `chat(messages, tools=...)` |
| `ctx.prompt()` | Character prompt getter |
| `ctx.napcat()` | QQ send entry point |
| `ctx.short_memory()` | Short-term memory, `save(msg, limit, trim_mode="rounds"\|"items")` / `load()` |
| `ctx.ltmem()` | Long-term / user memory, `record_ai_message(uid, ai_name, content)` |
| `ctx.excuse()` | Blocking follow-up question, `ask(question, uid, timeout=25)` |
| `ctx.toolbox()` | toolbox main entry point |
| `ctx.ai_name()` | AI name |
| `ctx.state()` | Plugin state handle: `enter()` / `update(**caps)` / `exit()` / `is_active()` |

## Identity contract

- The framework writes the identity into the request context (`contextvars`) **at the start of every request**; read it in a tool's `handle` / `handle_qq` / `route_text` via `self.uid` or `ctx.uid()`.
- There is exactly one identity key: `meowid` (internal id, shaped like `000001`). **Nicknames / QQ numbers / display names must never be used as identity**.
- The request context **does not cross threads**. If a plugin starts its own background thread, it must capture the uid explicitly at the request boundary and pass it into the thread (stash `self.uid` in `handle`, then hand it over).

A few framework-internal functions that maintain the request context (plugins rarely need them — only when constructing requests by hand or backfilling identity in background tasks):

| Function | Description |
|---|---|
| `begin_request(meowid, **rest)` | Open a new request context; the framework calls it before dispatch |
| `update_request(**kw)` | Merge fields into the current request context |
| `current_uid()` | uid of the current request (`""` when there is none) |
| `current_request()` | Full dict of the current request |

## Lifecycle

| Method | Description |
|---|---|
| `setup(ctx)` | Called once when the plugin loads (read config, start background threads, etc.) |
| `teardown()` | Called when the plugin is unloaded / reloaded |

## Hot reload

```python
PluginManager().reload("my_plugin")
```

Flow: `teardown()` → remove from the registry → clear `meowplug_<id>` / `meowschema_<id>` from `sys.modules` → load again. No need to restart the main program after changing plugin code.

## Gotchas

- Trigger tool names are globally unique; on a duplicate, the later-loaded one wins — trust the log message;
- Plugin directories starting with `_` or `.` are skipped;
- The plugin root is added to `sys.path`, so relative imports work fine inside plugins;
- Plugin data must always go through `ctx.store()` / `ctx.data_dir()` — **do not assemble relative paths yourself** (relative paths are based on the process working directory, which changes with how you launch).
