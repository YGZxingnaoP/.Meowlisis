# -*- coding: utf-8 -*-
"""演示插件：GUI 配置面板 schema（纯数据，不写逻辑）。

- PLUGIN：卡片元信息（id 必须与目录名一致）
- FIELDS：配置项，key 支持点号路径（llm.api_key → 写入 config.yml 的嵌套结构）
- CARDS：可选，GUI 分组卡片（本示例不用）

字段类型（与现有插件一致）：
    check     勾选框        {"key","label","type","default","help"}
    text      单行文本      {"key","label","type","default","help"}
    password  密码（打码）  {"key","label","type","default","help"}
    num       数字          {"key","label","type","default","min","max","step"}
    select    下拉          {"key","label","type","default","options":[{"value","label"}]}

配置读取：插件里用 ctx.config["llm"]["api_key"] 这种形式取嵌套值。
"""

PLUGIN = {
    "id": "demo_plugin",
    "title": "演示插件",
    "version": "1.0.0",
    "group": "dev",
    "emoji": "\U0001F9EA",          # 🧪
    "default_enabled": False,
}

FIELDS = [
    {"key": "enabled", "label": "启用演示插件", "type": "check", "default": False,
     "help": "仅调试用；开启后 demo_hello / demo_state 会进入 LLM 工具列表"},

    {"key": "greet_name", "label": "默认问候对象", "type": "text", "default": "主人",
     "help": "demo_hello 未传 name 时使用"},

    {"key": "loud", "label": "默认大声问候", "type": "check", "default": False},

    {"key": "retry", "label": "重试次数", "type": "num", "default": 3,
     "min": 0, "max": 10, "step": 1},

    {"key": "mode", "label": "演示模式", "type": "select", "default": "normal",
     "options": [{"value": "normal", "label": "普通"},
                 {"value": "silent", "label": "静默（不出声）"}]},

    # ---- 点号路径：写在 config.yml 的 llm.* 下 ----
    {"key": "llm.provider", "label": "接口平台", "type": "select", "default": "deepseek",
     "options": [{"value": "deepseek", "label": "DeepSeek"},
                 {"value": "aliyun", "label": "阿里云"},
                 {"value": "gemini", "label": "Gemini"},
                 {"value": "openai", "label": "OpenAI"}]},
    {"key": "llm.api_key", "label": "API Key", "type": "password", "default": "",
     "help": "演示插件的独立 LLM 端口用；留空表示不可用"},
    {"key": "llm.model", "label": "模型", "type": "text", "default": "",
     "help": "留空用平台默认"},
    {"key": "llm.temperature", "label": "温度", "type": "num", "default": 0.7,
     "min": 0, "max": 2, "step": 0.1},
]
