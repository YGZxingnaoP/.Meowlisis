# 插件系统说明

> [English](plugins.en.md) | 中文

本目录（项目根 `plugins/`）用于放置工具箱插件。程序启动时自动扫描并加载，无需改动主程序代码。

## 目录结构

```
plugins/
├── plugins.md           本说明文件
└── <插件id>/            一个插件一个目录，目录名即插件 id
    ├── plugin.py        必须，插件入口
    ├── schema.py        可选，GUI 配置面板定义（PLUGIN / FIELDS / CARDS）
    ├── config.yml       自动生成，插件独立配置（按 schema 默认值补全）
    ├── card.png         可选，GUI 卡片图
    └── 其它模块.py      可选
```

插件自身的数据**不放在插件目录里**，见下方「数据目录」。

## 启动加载与开关

程序启动时读取 `config.yml` 根节点的 `plugins` 配置：

```yaml
plugins:
  enabled: true          # 总开关，false 则完全不加载插件
  dir: ./plugins         # 插件根目录（相对路径按【主项目根】解析，不看进程工作目录）
  auto_load: true        # 是否自动扫描加载
  fail_fast: false       # 单插件加载失败是否中断启动
  disabled: []           # 黑名单（按插件 id）

  <插件id>:              # 单插件开关与自定义配置
    enabled: true
    some_key: some_value
```

- 开关优先级：`plugins.enabled`（总）→ `plugins.disabled`（黑名单）→ `plugins.<id>.enabled`（单插件，缺省取插件自身的 `default_enabled`）。
- 单个插件加载失败**只记日志、不阻断启动**；`fail_fast: true` 时改为抛错中断。
- 未写 `plugins` 节点时：默认启用，自动扫描 `./plugins`。

## plugin.py 约定

必须导出 `PLUGIN`（实例）或 `Plugin`（类，`ToolboxPlugin` 子类）。加载器优先取 `PLUGIN`，其次取 `Plugin`。

```python
from func.toolbox.plugins.sdk import (CHANNEL_MAIN, CHANNEL_QQ, ToolboxPlugin, TriggerTool)


class MyTool(TriggerTool):
    name = "my_tool"
    description = "仅在用户明确要求xxx时调用；其它情况禁止调用"
    parameters = {"arg1": {"type": "string", "description": "参数1"}}
    required = ["arg1"]
    prompt_hint = "- 用户要求xxx → 调用 my_tool"
    trigger_words = ("xxx", "xx一下")
    channels = (CHANNEL_MAIN,)          # 只在主链路可用；QQ 不暴露、不执行

    def handle(self, arguments, ctx):
        ctx.tts().send_stream("回复文本", source="toolbox_my")
        return "ok"

    def handle_qq(self, arguments, qq_context, ctx):
        target = str(qq_context.get("target_id") or "")
        ctx.napcat().send_private_text(target, "回复文本")
        return "ok"

    def route_text(self, text, meowid="", channel=CHANNEL_MAIN):
        return False


class Plugin(ToolboxPlugin):
    id = "my_plugin"
    title = "我的插件"
    default_enabled = True

    def trigger_tools(self):
        return [MyTool()]

    def prompt_hint(self):
        return "【我的插件】用户想xxx时调用 my_tool"

    def setup(self, ctx):
        self.ctx = ctx


PLUGIN = Plugin()
```

## 链路（channel）

框架只有两条链路，`TriggerTool.channels` 声明本工具参与哪些：

| 常量 | 值 | 含义 |
|---|---|---|
| `CHANNEL_MAIN` | `"main"` | 主链路：语音 / 弹幕，走 `analysis.py` |
| `CHANNEL_QQ` | `"qq"` | QQ 链路，走 `napcat/analysis/analysis_core.py` |

`channels` 默认 `(CHANNEL_MAIN, CHANNEL_QQ)` 两条全开。声明后由**框架**统一过滤：

- `trigger_schemas(channel)` 只返回该链路的工具 → QQ 的意图分析**看不到**没声明 `"qq"` 的工具；
- `dispatch_qq()` 对没声明 `"qq"` 的工具直接返回 `None`，不会执行。

所以「只在主链路触发」写一行 `channels = (CHANNEL_MAIN,)` 即可，**不要**在 `handle_qq` 里写拒绝逻辑。

## 工具类型

### 触发型工具 TriggerTool

由「语音意图分析」或「QQ 意图分析」的 LLM 决策后调用，也可被 `trigger_words` 关键词硬触发。

| 成员 | 说明 |
|---|---|
| `name` | 工具名，全局唯一、无点号 |
| `description` | 给 LLM 的说明，务必写清「仅在…时调用 / 其它情况禁止调用」 |
| `parameters` | JSON Schema properties |
| `required` | 必填参数名列表 |
| `prompt_hint` | 可选，一行引导文案，自动追加进两处意图分析提示词 |
| `trigger_words` | 可选，关键词硬触发（命中即调用，不过 LLM） |
| `channels` | 参与哪些链路，默认两条全开 |
| `uid` | **只读属性**，当前请求的内部编号（见「身份契约」） |
| `handle(args, ctx)` | 主链路执行，未实现抛 `NotImplementedError` |
| `handle_qq(args, qq_context, ctx)` | QQ 链路执行，未实现抛 `NotImplementedError`（不再回退 `handle`） |
| `route_text(text, meowid, channel)` | 会话拦截，返回 `True` 表示已接管该输入；默认 `False` |

### 接口型工具 InterfaceTool

不进 LLM，供项目内部按名调用。实现 `call(ctx, **kwargs)` 并在 `interface_tools()` 中返回：

```python
PluginManager().call_interface("my_probe", deep=True)
```

## PluginContext 能力

插件通过注入的 `ctx` 访问项目能力，不建议直接 import 主程序内部模块。

### 身份

| 成员 | 说明 |
|---|---|
| `ctx.uid()` | 当前请求的内部编号（`meowid`），**程序识别身份只用它** |
| `ctx.request()` | 当前请求的完整上下文 `{meowid, text, short_memory, system_prompt}` |
| `ctx.display_name(uid=None)` | uid → 展示名。**展示的唯一合法来源**，禁止用 uid / QQ 号当昵称 |
| `self.uid`（工具内） | 同上，等价于 `ctx.uid()` |

### 路径

| 成员 | 说明 |
|---|---|
| `ctx.root()` | 主项目根目录 |
| `ctx.plugin_dir()` | 本插件目录 `<root>/plugins/<id>` |
| `ctx.path(*parts)` | 拼到主项目根下的绝对路径 |
| `ctx.resolve(p)` | 相对路径 → 绝对路径（相对**主项目根**，与进程工作目录无关） |

### 数据

| 成员 | 说明 |
|---|---|
| `ctx.data_dir(per_user=None)` | 插件数据目录，见下方约定 |
| `ctx.store(name, per_user=None)` | 返回 `JsonStore`，`load(default)` / `save(data)`，原子写 |

**数据目录约定**：

```
character/plugin_data/<插件id>/            ← per_user=""  →  插件全局数据
character/plugin_data/<插件id>/<uid>/      ← per_user=None →  当前请求那个人的数据
                                             per_user=uid  →  指定那个人的数据
```

⚠️ `per_user=None` 是**默认值**，跟着当前请求的 uid 走。要拿插件全局目录**必须显式传 `""`**。

### 项目能力

| 成员 | 说明 |
|---|---|
| `ctx.id` | 插件 id |
| `ctx.log` | 日志对象 |
| `ctx.config` | 本插件配置（即 `plugins.<id>` 下的键值） |
| `ctx.tts()` | TTS 语音桥接，`send_stream(text, source=...)` / `is_busy()` / `interrupt()` |
| `ctx.llm()` | toolbox LLM 端口，`chat(messages, tools=...)` |
| `ctx.prompt()` | 角色提示词获取器 |
| `ctx.napcat()` | QQ 发送入口 |
| `ctx.short_memory()` | 短期记忆，`save(msg, limit, trim_mode="rounds"\|"items")` / `load()` |
| `ctx.ltmem()` | 长期 / 用户记忆，`record_ai_message(uid, ai_name, content)` |
| `ctx.excuse()` | 阻塞追问，`ask(问题, uid, timeout=25)` |
| `ctx.toolbox()` | toolbox 总入口 |
| `ctx.ai_name()` | AI 名字 |
| `ctx.state()` | 插件状态句柄：`enter()` / `update(**caps)` / `exit()` / `is_active()` |

## 身份契约

- 框架在**每个请求开始时**把身份写进请求上下文（`contextvars`），工具的 `handle` / `handle_qq` / `route_text` 里用 `self.uid` 或 `ctx.uid()` 取。
- 身份只有一个键：`meowid`（内部编号，形如 `000001`）。**昵称 / QQ 号 / 显示名一律不能当身份**。
- 请求上下文**不跨线程**。插件自己起后台线程时，必须在请求边界把 uid 显式捕获、传进线程（`handle` 里 `self.uid` 存下来再传）。

框架内部维护请求上下文的几个函数（插件一般用不到，只在手动构造请求 / 后台任务回填身份时用）：

| 函数 | 说明 |
|---|---|
| `begin_request(meowid, **rest)` | 开一个新请求上下文；框架在分发前调用 |
| `update_request(**kw)` | 往当前请求上下文里合并字段 |
| `current_uid()` | 当前请求的 uid（无请求时返回 `""`） |
| `current_request()` | 当前请求的完整 dict |

## 生命周期

| 方法 | 说明 |
|---|---|
| `setup(ctx)` | 插件加载时调用一次（读配置、起后台线程等） |
| `teardown()` | 插件卸载 / 重载时调用 |

## 热重载

```python
PluginManager().reload("my_plugin")
```

流程：`teardown()` → 从注册表摘掉 → 清掉 `sys.modules` 里的 `meowplug_<id>` / `meowschema_<id>` → 重新加载。改插件代码后不用重启主程序。

## 注意事项

- 触发型工具名全局唯一，重复时后加载者覆盖前者，以日志提示为准；
- 插件目录以 `_` 或 `.` 开头的会被跳过；
- 插件根目录会加入 `sys.path`，插件内部可正常使用相对导入；
- 插件数据一律走 `ctx.store()` / `ctx.data_dir()`，**不要自己拼相对路径**（相对路径的基准是进程工作目录，会随启动方式变化）。
