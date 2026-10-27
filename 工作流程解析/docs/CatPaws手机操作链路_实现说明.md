# CatPaws 手机操作链路 · 实现说明（2026-10）

本轮把「角色操作手机」做成了和点歌（meowsinger）同构的一条链路：主项目负责触发与桥接，
`.vendor/.CatPaws` 负责模型判断与真机操作，两边通过 HTTP + 事件流对接。

## 一、配置真值

- 唯一真值：**`.vendor/.CatPaws/config.yml`**（含模型 key，已加进 `.gitignore`）。
- 主项目 `config.yml` 里的 `catpaws:` 节点已整段删除；`func/catpaws` 不再读主项目配置。
- 字段说明见 `.vendor/.CatPaws/CONFIG.md`；GUI 里的「手机操作」配置卡直接读写这个文件。
- 触发词/停止词/桥接参数改完立即生效（`CWCatPawsConfig.refresh()` 按 mtime 重读）；
  服务端的设备/链路参数改动需要重启 CatPaws 服务。

## 二、主项目侧（`func/catpaws`）

| 文件 | 职责 |
|---|---|
| `config.py` | 读 `.vendor/.CatPaws/config.yml`（触发、停止、服务地址、`sync`、独立 LLM 端口） |
| `port/` | 独立 LLM 端口（deepseek/aliyun/gemini/meowllm），**只用于意图判断与兜底角色化回应** |
| `if_start.py` | 触发判断：`prefix` 命中直接进链路（目标=去掉触发词后的剩余文本）；`intent` 词命中先让模型判断 |
| `stop.py` | 停止词（默认「别再操控手机了」「手机还我」）：立刻停手、停播报、结束链路 |
| `state.py` | 链路状态落盘 `.temp/catpaws_state.json`（是否接管、阶段、会话、已读事件序号） |
| `client.py` | 访问 CatPaws 服务端（status/start/stop/answer/replies/screenshot） |
| `prompt.py` | 组装 `/cw/start` 载荷：角色卡 `pipeline/system_prompt` + 短期记忆 `pipeline/short_memory` + 用户原话 |
| `memory.py` | 桥接记忆：用户消息写 `phone_control_user`，角色回复写 **`phone_control_response`**，同时写长期记忆/摘要/用户记忆 |
| `voice.py` | 桥接 TTS（`ToolboxTtsBridge`）、追问等待（`TBExcuse.wait_text`）、手机没连上时的角色化说明 |
| `core.py` | 调度：触发 → 启动 → 轮询事件桥接 → 等 `end` 释放拦截 |

入口仍是 `func/pipeline/msg_catpaws.py`（`api.py` 的 `/msg`、`/chat`、语音回调三处已经接好）。
链路接管期间 `receive()` 一律返回 `True`：消息不进主 LLM，停止词立即停，其余当补充指令转给服务端。

**不和 `func/llm` 桥接**：角色回复由 `.CatPaws` 自己的端口生成，主项目只把文本送 TTS 与记忆。

## 三、服务端侧（`.vendor/.CatPaws`）

### 三类操作（与需求逐条对应）

| 类别 | 工具 | 适用 | 关键约束 |
|---|---|---|---|
| 单次操作 | `cw_single` | 大部分场景：点一下、滑一下、找图标点图标、返回上一级 | 滑动用 `direction+ratio`；**`edge` 可从屏幕边缘起手**（iOS 返回 = `edge=left` + `direction=right`） |
| 连续操作 | `cw_sequence` | 游戏连招、打字、进入→点击→返回这种已确定路径 | `delay_ms` **默认 90ms、下限 90ms**（传更小会被夹到 90）；单批最多 `sequence_steps` 步 |
| action 操作 | `cw_action` | 界面对得上已登记脚本时直接调；脚本由反思阶段写入 | 目录 `actions/<id>/` + `manifest.json` + 入口 `main.py`；**可以有多个 .py 互相 import** |

输入文字：`cw_type_cn`（粘贴 → 拼音点键 → 点候选 → 失败回退删字 → 请主人代打）；
自己点键盘用 `cw_keys`（先点输入框让键盘弹出）。`cw_input` 走 WDA 元素写入，作兜底。

- `src/cw/port/`：独立 LLM 端口（`port.type` + 各 provider 块），agent 与角色交流都走它。
- `src/cw/session.py`：阶段改为 `control`（操作中）/ `recording`（反思中）/ `end`（结束），
  另加插话队列、提问阻塞、`pending_question`。
- `src/cw/agent.py`：
  - `control` 阶段允许边操作边说话（每轮 assistant 文本都会进事件流，由主项目播报并记忆）；
  - 无步数上限（`agent.max_rounds=0`、`max_steps_per_session=0`、`session_timeout_sec=0`）；
  - 收尾必须调 `cw_task_done`，服务端会先问主人「还有别的事吗」，确认后才结束；
  - `recording` 阶段可以继续操作手机，但 `guard.reflect_block_words` 命中即拦；写脚本前要**再确认一次**；
  - 结束不回桌面（`agent.exit_to_home=false`），开始前回桌面（`start_home=true`）；
  - **空闲防息屏**（`agent.keep_awake_sec`，**默认 0 关闭**）：只在链路进行中（操作中/反思中）
    且空闲超过设定秒数时，轻点**状态栏正中**（键盘盖不到、也没有按钮；配置 `agent.keep_awake_point`
    可改）。⚠️ 千万别设在屏幕底部——输入法弹出时那里是空格/发送键，会往输入框里塞字符；
  - **连接不再偷偷降级**：设备连不上时保持「离线」（`/cw/status` 的 `device.online=false`），
    不再自动换成 mock 假设备；状态轮询会每 5 秒重试一次连接，手机就绪后无需重启服务
    （需要旧行为就把 `device.mock_fallback` 打开）；
  - **锁屏兜底**：`E_DEVICE_LOCKED` → 暂停链路以角色口吻请主人解锁（开链前 3 次 / 操作中 5 次），
    解锁后自动继续，不会无限硬点。
- `src/cw/toolparse.py`：模型把工具调用写成正文标记时的兜底解析，同时把标记从播报文本里剔掉。
- `src/cw/llm_client.py`：带图消息走 `vision` 端口，但仍带工具；思考模式回传 `reasoning_content`。
- `src/cw/web.py`：新增 `GET /cw/replies?since=`（增量事件流），`POST /cw/start` 接收
  `goal/system_prompt/memory/user_message`。

## 四、GUI

- **日志中心**：选中「CatPaws(iOS)」→ CatPaws 控制台（画面 + 状态 + 目标输入 + 停止/截图/拉起 launcher/Runner 探活 + 事件时间线 + 追问回答）；
  选中「手机接口」→ 手机摄像头（`.cam` 的 8445 端口，`object-fit: cover`：横竖屏都撑满、不拉伸）。
  视频中继没画面时会自动退回**截图轮询**（1.5 秒一张）并在画面上方说明原因（没连中继 / 没开推流 / 没收到帧），
  同时每 10 秒重新请求一次开推流。
- 后端代理：`gui/tools/catpaws_hub.py`（`/api/catpaws/*`），配置读写 `.vendor/.CatPaws/config.yml`。
- 轨道卡片：外环「手机操作」（配置面板）、启动环「手机操作」（启动服务并打开日志中心）。
- 卡面：`gui/resource/cat_photos/{catpaws,launcher_catpaws}.png`，用 `.ComfyNode` 的 ComfyUI、
  按既有卡面 PNG 里内嵌的同一套 workflow（同模型/LoRA/采样/尺寸/负面词）生成。

## 五、跑起来

1. 手机插线解锁 → `.vendor/.CatPaws/catpaws-launcher/start.cmd`（`status.cmd` 看到 `/cw/v1/ping -> 200`）；
2. GUI 启动球「手机操作」，或日志中心选中 CatPaws(iOS) 点 ▶；
3. 聊天里说「喵呜我要点外卖 来一份麦辣鸡腿堡」，或在 CatPaws 面板里直接输目标；
4. 停下来说「手机还我」/「别再操控手机了」。

## 六、测试

**桥接回归（不需要手机，服务端用 mock 设备 + 真模型）**

```bat
runtime\311\python.exe scripts\catpaws_bridge_test.py
```

跑一遍「触发 → 启动 → 边说边操作 → 追问（走 TBExcuse）→ 收尾确认 → 反思 → end 释放」，
并核对角色回复是否以 `phone_control_response` 写进短期记忆；`--home <临时目录>` 可把运行时目录挪走。

**真机（走主项目，和角色对话一样）**

```bat
scripts\catpaws_live.bat
```

一次开两个窗口：左边「对话框」（自动体检：主程序 1800 / CatPaws 服务是否 mock / Runner 8100，识别 meowid），
右边「日志」（跟主程序 `[CatPaws]` 行、服务启动行、**操作流水**：阶段/角色发言/工具/点按滑动/观察文字/提问回答/防息屏/锁屏）。
对话窗口说的话走 `POST /msg`，与 QQ/语音完全同一条链路（角色回复 + TTS + 记忆 + 手机操作）。

**真机（不经过主项目）**

```bat
runtime\311\python.exe scripts\catpaws_meituan_test.py --shots
```

默认目标是「打开美团，点一份外卖」；`--auto "没有了|先别写"` 可自动回答收尾/写脚本确认。
测试不写记忆、不出声，只看截图与事件流。

**action 脚本的保存标准**（反思阶段写脚本时按这个来）：

- 位置：`.vendor/.CatPaws/actions/<id>/`，必须有 `manifest.json` + 入口脚本（默认 `main.py`）；
- **一个 action 可以有多个 .py**，互相 `import 模块名` 即可（同目录自动进 `PYTHONPATH`，审查器把同目录
  的模块名当白名单放行）；文件名只能是 `xxx.py`，必须包含 `main.py`；
- `id`：snake_case、2~41 字符（`^[a-z][a-z0-9_]{1,40}$`），一个目录只能有一个 action；
- manifest 必填：`id/title/scene/status/updatable/author/version/entry/steps/params/requires`；
  `params` 里放可调参数（`cw_script.params()` 读），`steps` 写清流程，`entry` 用 `main.py:run`；
- 脚本约束：≤800 行；只能 import `json/time/re/math/random/datetime/typing/io/base64/PIL/cw_script`；
  禁止 `open/eval/exec/__import__`；入口用 `if __name__ == "__main__": run()`；
- 用 `cw_script` 提供的接口：`tap/long_press/swipe/swipe_dir/wait/press_key/home/type_text/paste_text/
  launch_app/observe_texts/observe_image/ocr_find/tap_text/screen/ask/params/log/done/should_stop`；
- 参考实现：`actions/jump_jump`（截图 + 图像识别 + 长按，v2）；骨架模板：`actions/example.py`；
  历史版本（TensorFlow/CV 两套旧实现）收在 `actions/_legacy/`，不会被登记。
