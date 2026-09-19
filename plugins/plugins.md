# 插件系统说明

本目录（项目根 `plugins/`）用于放置工具箱插件。程序启动时自动扫描并加载，无需改动主程序代码。

## 目录结构

```
plugins/
├── plugins.md           本说明文件
└── <插件id>/            一个插件一个目录，目录名即插件 id
    ├── plugin.py        必须，插件入口
    └── 其它模块.py      可选
```

## 启动加载与开关

程序启动时读取 `config.yml` 根节点的 `plugins` 配置：

```yaml
plugins:
  enabled: true          # 总开关，false 则完全不加载插件
  dir: ./plugins         # 插件根目录（相对项目根）
  auto_load: true        # 是否自动扫描加载
  fail_fast: false       # 单插件加载失败是否中断启动
  disabled: []           # 黑名单（按插件 id）

  <插件id>:              # 单插件开关与自定义配置
    enabled: true
    some_key: some_value
```

开关优先级：`plugins.enabled`（总）→ `plugins.disabled`（黑名单）→ `plugins.<id>.enabled`（单插件，缺省取插件自身的 `default_enabled`）。

未写 `plugins` 节点时：默认启用，自动扫描 `./plugins`。

## plugin.py 约定

必须导出 `PLUGIN`（实例）或 `Plugin`（类，`ToolboxPlugin` 子类）。加载器优先取 `PLUGIN`，其次取 `Plugin`。

```python
from func.toolbox.plugins.sdk import ToolboxPlugin, TriggerTool


class MyTool(TriggerTool):
    name = "my_tool"                       # 全局唯一，无点号
    description = "仅在用户明确要求xxx时调用；其它情况禁止调用"
    parameters = {"arg1": {"type": "string", "description": "参数1"}}
    required = ["arg1"]
    prompt_hint = "- 用户要求xxx → 调用 my_tool"   # 追加进意图分析提示词

    def handle(self, arguments, ctx):
        """语音链路执行"""
        ctx.tts().send_stream("回复文本", source="toolbox_my")
        return "ok"

    def handle_qq(self, arguments, qq_context, ctx):
        """QQ 链路执行"""
        target = str(qq_context.get("target_id") or "")
        ctx.napcat().send_private_text(target, "回复文本")
        return "ok"


class Plugin(ToolboxPlugin):
    id = "my_plugin"
    title = "我的插件"
    default_enabled = True

    def trigger_tools(self):
        """返回触发型工具列表"""
        return [MyTool()]

    def prompt_hint(self):
        """返回意图分析引导文案"""
        return "【我的插件】用户想xxx时调用 my_tool"


PLUGIN = Plugin()
```

## 工具类型

### 触发型工具 TriggerTool

由「语音意图分析」或「QQ 意图分析」的 LLM 决策后调用，这是最常用的类型。

| 成员 | 说明 |
|---|---|
| `name` | 工具名，全局唯一、无点号 |
| `description` | 给 LLM 的说明，务必写清「仅在…时调用 / 其它情况禁止调用」 |
| `parameters` | JSON Schema properties |
| `required` | 必填参数名列表 |
| `prompt_hint` | 可选，一行引导文案，自动追加进两处意图分析提示词 |
| `handle(args, ctx)` | 语音链路：用 `ctx.tts()` 播报 |
| `handle_qq(args, qq_context, ctx)` | QQ 链路：用 `ctx.napcat()` 发送；缺省回退 `handle` |

### 接口型工具 InterfaceTool

供其它代码按名调用，不暴露给 LLM。本项目暂未使用，需要时实现 `call(ctx, **kwargs)` 并在 `interface_tools()` 中返回。

## PluginContext 能力

插件通过注入的 `ctx` 访问项目能力，不建议直接 import 主程序内部模块。

| 成员 | 说明 |
|---|---|
| `ctx.id` | 插件 id |
| `ctx.log` | 日志对象 |
| `ctx.config` | 本插件配置（即 `plugins.<id>` 下的键值） |
| `ctx.tts()` | TTS 语音桥接，`send_stream(text, source=...)` |
| `ctx.llm()` | toolbox LLM 端口，`chat(messages, tools=...)` |
| `ctx.prompt()` | 角色提示词获取器 |
| `ctx.napcat()` | QQ 发送入口 |

## 生命周期

| 方法 | 说明 |
|---|---|
| `setup(ctx)` | 插件初始化（读配置、起后台线程等） |
| `teardown()` | 插件卸载清理 |

## 注意事项

- 触发型工具名全局唯一，重复时后加载者覆盖前者，以日志提示为准；
- 单个插件加载失败只记日志、不阻断启动（`fail_fast: true` 可改为中断）；
- 插件目录以 `_` 或 `.` 开头的目录会被跳过；
- 插件根目录会加入 `sys.path`，插件内部可正常使用相对导入。
