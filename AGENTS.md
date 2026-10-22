# AGENTS.md — Meowlisis 工作区约定

本文件由 DSH 作为项目指令自动加载，对**所有后续会话**生效（不是某一轮对话的临时要求）。
修改本文件即修改所有 agent 在此仓库的默认行为，比在对话里口头约定更持久。

## 一、目录红线：`.temp/` 禁止写入

`.temp/` 是主程序的**运行时缓存目录**，由程序自己读写，已在 `.gitignore` 中忽略：

- 短期记忆 `public_short_mem.json`、情绪/心理快照 `latest_*.json`、NapCat 原始事件 `napcat_raw_events.jsonl`、录音与歌曲临时片段、会话状态等；
- **禁止**在其中创建、修改、删除任何文件：脚本、测试、笔记、临时数据一律不行；
- 它不是工作区，也不是放"一次性脚本"的地方。历史上曾把验证脚本写进去，属于污染，不应再发生。

同类只读目录：`logs/`（运行日志）、`.vendor/`（内置运行时/模型/依赖，任务未明确要求时不要写）。

## 二、临时文件放哪里

| 需要 | 位置 |
|---|---|
| 一次性脚本、验证代码、冒烟测试 | 系统临时目录（`$env:TEMP\xxx.py`），或直接内联执行（`python -c` / `node -e`） |
| 值得保留的开发脚本（数据处理、打包） | `scripts/` |
| GUI 相关辅助工具 | `gui/tools/` |
| 方案/分析文档 | `工作流程解析/docs/` |

## 三、项目约定

- 配置真值：`config.yml`（不入库，含密钥）。增删配置项时，Python 侧在对应 `config.py` 读取，前端在 `gui/js/config/*.js` 用 `this._check/_num/_text(...)` 加字段（靠 `data-path` 自动保存）；需要出现在精简卡片的项补进 `gui/js/advanced.js` 的 `Config.SIMPLE`；中文字面量必须补 `gui/locales/en.js` 词条，并跑 `python gui/tools/check_i18n.py` 确认没有新增缺失。
- 分层：`func/toolbox/napcat/llm/` 是角色扮演桥接层（走 `func/pipeline` 提示词）；**非角色扮演**的工具判断放 `func/toolbox/napcat/analysis/`，并直接使用 `func/toolbox/port/*` 端口。
- 群聊回复链路集中在 `func/toolbox/qq_response.py`，合并/派发在 `func/toolbox/napcat/groupchat/group_coordinator.py`；改这两处保持最小改动，不新增解释性注释。
- 动手前先读原文件；不要清理或覆盖与本次任务无关的既有改动（工作区常有用户自己的未提交修改）。

## 四、验证习惯

- Python 改动至少做 AST/语法检查（可用 `python -c "import ast; ast.parse(open(p, encoding='utf-8').read())"`）；
- 前端 JS 改动用 `node --check`；
- 涉及配置面板的改动跑 `python gui/tools/check_i18n.py`；
- 运行时依赖 `runtime/311/python.exe`（不是系统 python）。
