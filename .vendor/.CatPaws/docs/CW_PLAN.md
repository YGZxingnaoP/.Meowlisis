# CatPaws 方案（PC 侧）

本文是当前方案的落盘版：定位、边界、三类操作、agent 阶段机、action 存储、保护措施、目录结构与里程碑。
手机端实现细节见 `CW_IOS_SPEC.md`（接口契约以那份为准）。

---

## 1. 定位与边界

CatPaws = 让主项目"用眼睛看手机屏幕、用手操作手机"的服务。

| 边界 | 规定 |
|---|---|
| **AI 的观察通道** | 只有两样：`/cw/v1/screenshot`（图片直传多模态）与 `/cw/v1/ocr`（文本 + 像素框）。**视频流永远不进模型** |
| **视频流用途** | 只给人看：PC 前端实时预览、手机端 App 显示。推给**服务端中继**，不进模型、不进 prompt |
| 决策 | 决策循环在 CatPaws 内置轻量 agent 里；主项目只下发目标、接收结果 |
| 主项目改动 | 只新增 `func/catpaws`；不改 pipeline 提示词桥接、不改快回逻辑（后续方案） |
| 手机端 | 双 target：Runner 做所有设备能力，App 做界面/相机/音频/推流 |
| 坐标 | 对外只有截图像素；换算在手机端 |

---

## 2. 拓扑与端口

```
iPhone
├── CatPawRunner  :8100  /cw/v1/*        触摸/截图/OCR/元素树
└── CatPaw app            → PC 8081 WS   屏幕流（ReplayKit→H.264）
                          → PC 8443 WS   相机流（.cam 原协议，WKWebView 内）

Windows
├── go-ios tunnel/forward   127.0.0.1:8100 → 手机 8100
├── CatPaws 服务 :8080       前端页面 + 控制 API + agent + action + 日志（监听 127.0.0.1）
├── CatPaws 中继 :8081       WS 视频中继 + 设备控制通道（监听 0.0.0.0，token 鉴权）
└── .cam 服务    :8443       手机 App 内的 .cam 页面（已有，不改）
```

* 8081 必须监听 0.0.0.0：手机从局域网直连；8080 只监听 127.0.0.1。
* 视频不穿 USB 隧道，隧道只承载截图/动作这类小报文。

---

## 3. 三类操作

| 类 | 工具 | 设备端调用 | 典型场景 |
|---|---|---|---|
| 单次 | `cw_single` | `POST /actions` 一步 | 点图标、点返回、上下滑一屏 |
| 连续 | `cw_sequence` | `POST /actions` 多步 + `delay_ms` | 打字、游戏连招、进入→点击→返回 |
| action | `cw_action` | 起子进程跑 `actions/<id>/` 脚本 | 跳一跳、固定流程的付款、打开某 App 的固定路径 |

### 3.1 工具契约（function calling）

```json
{"name":"cw_observe","description":"看屏幕。执行任何操作前先调用。mode=ocr 返回文本与像素框；mode=image 返回原图给多模态模型。",
 "parameters":{"type":"object","properties":{
   "mode":{"type":"string","enum":["ocr","image"]},
   "region":{"type":"array","items":{"type":"integer"},"minItems":4,"maxItems":4},
   "max_edge":{"type":"integer","description":"仅 image 模式，长边像素，默认 1280"}},
  "required":["mode"]}}
```

```json
{"name":"cw_single","description":"单次原子操作。",
 "parameters":{"type":"object","properties":{
   "action":{"type":"string","enum":["tap","long_press","swipe","pinch","type_text","paste_text","press_key","launch_app","activate_app","terminate_app","wait"]},
   "x":{"type":"integer"},"y":{"type":"integer"},"count":{"type":"integer","minimum":1,"maximum":3},
   "duration_ms":{"type":"integer"},
   "from":{"type":"array","items":{"type":"integer"},"minItems":2,"maxItems":2},
   "to":{"type":"array","items":{"type":"integer"},"minItems":2,"maxItems":2},
   "scale":{"type":"number"},
   "text":{"type":"string"},
   "key":{"type":"string","enum":["home","volume_up","volume_down","delete","return"]},
   "bundle_id":{"type":"string"}},
  "required":["action"]}}
```

```json
{"name":"cw_sequence","description":"连续操作。一次下发多步，设备端保证每步间隔 ≥ delay_ms（默认 90ms）。",
 "parameters":{"type":"object","properties":{
   "steps":{"type":"array","minItems":1,"maxItems":20,"items":{"type":"object"}},
   "delay_ms":{"type":"integer","minimum":90,"maximum":2000,"default":90}},
  "required":["steps"]}}
```

```json
{"name":"cw_action","description":"执行已登记 action。调用前先看它的 scene 是否匹配当前界面。",
 "parameters":{"type":"object","properties":{
   "action_id":{"type":"string"},"params":{"type":"object"}},"required":["action_id"]}}
```

```json
{"name":"cw_ask_user","description":"不确定时向用户提问，阻塞等待回答（60s 超时按取消处理）。",
 "parameters":{"type":"object","properties":{
   "question":{"type":"string"},
   "options":{"type":"array","items":{"type":"string"}}},"required":["question"]}}
```

阶段工具（**只在 reflecting 阶段可见**）：

```json
{"name":"cw_write_action","description":"把本次成功操作沉淀成 action（新建即 unverified）。",
 "parameters":{"type":"object","properties":{
   "id":{"type":"string"},"title":{"type":"string"},"scene":{"type":"string"},
   "steps":{"type":"array","items":{"type":"string"}},
   "code":{"type":"string"},"params":{"type":"object"}},"required":["id","title","scene","code"]}}
```

```json
{"name":"cw_update_action","description":"小规模修改已有 action。仅当 status=unverified 或 updatable=true 时可用。",
 "parameters":{"type":"object","properties":{
   "action_id":{"type":"string"},"code":{"type":"string"},"reason":{"type":"string"}},
  "required":["action_id","code","reason"]}}
```

### 3.2 打字场景

* 中文：优先 `paste_text`（剪贴板 + 长按粘贴），最稳。
* 需要"逐字键入"时（如某些输入框不接受粘贴）：PC 侧把中文转拼音 → `cw_sequence` 逐字母 `type_text` + 点候选词；转换失败就 `cw_ask_user` 请用户代打。
* 允许回退：`press_key delete` 连按 = 删字；`cw_single` 的 `count` 支持 1..3，更长用 `cw_sequence`。

---

## 4. agent 阶段机

```
idle ──start(goal)──► running ──目标完成/被停止/超步数──► reflecting ──► idle
                        ▲                                  │
                        └──────── 用户再次下目标 ───────────┘
```

| 阶段 | 可见工具 | 约束 |
|---|---|---|
| idle | 无 | 不占用设备 |
| running | `cw_observe` `cw_single` `cw_sequence` `cw_action` `cw_ask_user` `cw_update_action` | **禁止新建 action**（工具表里没有 `cw_write_action`）；只允许对 `unverified`/`updatable` 的 action 做小规模微调 |
| reflecting | `cw_observe`(只读) `cw_write_action` `cw_update_action` `cw_ask_user` | **禁止执行任何操作**（没有操作工具），只做沉淀与更新 |

实现要点：

* 工具表由 `CWAgentTools.schemas(phase)` 生成，阶段切换时重建；`cw_write_action` / `cw_update_action` 的实现里**再校验一次阶段**（双重保险）。
* 目标完成后自动进入 reflecting 跑一次轻量反思（配置可关：`catpaws.reflect_enabled`）。
* 反思输入：本次操作日志摘要（动作序列 + 成败 + 界面 OCR 片段），不重放视频、不重截图。

---

## 5. action 存储与状态机

### 5.1 目录

```
actions/
├── jump_jump/               用户自己写的（保留）
│   ├── manifest.json
│   └── main.py
└── wechat_pay/              AI 沉淀的
    ├── manifest.json
    └── main.py
```

目录名 ASCII snake_case；中文标题写在 manifest 的 `title`。

### 5.2 manifest.json

```json
{
  "id": "wechat_pay",
  "title": "微信付款",
  "scene": "在微信聊天/收付款页完成一笔小额付款",
  "status": "unverified",
  "updatable": false,
  "author": "ai",
  "version": 1,
  "entry": "main.py:run",
  "params": {"max_amount": 50},
  "steps": ["进入聊天", "点 + 选转账", "输入金额", "确认"],
  "requires": ["launch_app:com.tencent.xin"],
  "last_run": {"ok": false, "at": "", "elapsed_ms": 0},
  "created_at": "2026-01-01T00:00:00+08:00",
  "updated_at": "2026-01-01T00:00:00+08:00"
}
```

| 字段 | 说明 |
|---|---|
| `status` | `unverified` / `verified` |
| `updatable` | 用户标注：软件迭代后允许 AI 更新 |
| `author` | `ai` / `user` |
| `entry` | `文件:函数`，默认 `main.py:run` |
| `steps` | 给模型读的语义步骤，不是执行序列 |

### 5.3 规则（硬约束，代码里锁死）

| 场景 | 允许 | 结果状态 |
|---|---|---|
| AI 运行时想改 `unverified` | 允许小规模微调 | 仍 `unverified` |
| AI 运行时想改 `verified + updatable=true` | 允许小规模微调 | 降为 `unverified`（`updatable` 保留） |
| AI 运行时想改 `verified + updatable=false` | **拒绝**，直接失败上报 | 不变，**禁止复制副本绕过** |
| 运行中新建 action | **禁止**（工具不可见） | — |
| 反思阶段新建 | 允许 | `unverified`，不自动试跑 |
| 反思阶段更新 | 同"运行时修改"规则 | 同上 |
| 跑通（完整执行 ok） | 自动置 `verified`，清空 failure 计数 | `verified` |

"小规模微调"的量化边界：只允许改该目录内**已存在**的 `.py`，改动 ≤60 行，改后必须编译通过，不允许新增/删除文件（新增文件等于新建 action，只能在反思阶段做）。

### 5.4 审查（写前必过）

| 检查 | 规则 |
|---|---|
| 语法 | `ast.parse` 必须通过（compile 工具） |
| 禁止调用 | `eval` `exec` `compile` `__import__` `open`(写模式) `os.system` `subprocess` `ctypes` `socket` |
| 允许 import | 标准库白名单（`json` `time` `re` `math` `random` `datetime` `typing`）+ 注入模块 `cw_script` |
| 体积 | ≤5 个文件、单文件 ≤800 行、总大小 ≤200KB |
| 命名 | 目录名与 manifest `id` 一致 |

### 5.5 执行模型（脚本如何操作手机）

脚本**没有网络权限、拿不到 token**，只能和父进程说 JSONL：

```
子进程 stdout → 父进程：
  {"op":"emit","step":{"action":"tap","x":585,"y":1266}}
  {"op":"emit","steps":[{...},{...}],"delay_ms":90}
  {"op":"observe","mode":"ocr"}
  {"op":"ask","question":"金额填多少？"}
  {"op":"log","text":"进入付款页"}
  {"op":"done","ok":true}

父进程 stdin → 子进程：
  {"op":"observation","data":{...}}
  {"op":"answer","text":"20"}
  {"op":"cancel"}
```

* 父进程是唯一能发 `/cw/v1/actions` 的角色，保护措施（步数/频率/黑名单/停止）对脚本同样生效。
* 子进程用 `runtime/311/python.exe` 起，`cwd` 锁定在 action 目录，超时 120s，stdout 逐行解析，非法行直接丢弃。
* 脚本只用 `from cw_script import emit, observe, ask, log, done`（父进程通过 `PYTHONPATH` 注入该模块）。

---

## 6. 保护措施

| 措施 | 规则 |
|---|---|
| 坐标 | 由设备端校验，越界整批拒绝 |
| 频率 | 动作间隔 ≥90ms（设备端强制）；单链路动作速率 ≤5 动作/秒 |
| 数量 | 连续操作 ≤20 步；单链路 ≤200 步 |
| 时长 | 单动作 ≤120s；单链路 ≤15 分钟（超时自动停止并播报） |
| action | 单次 ≤120s；同一 action 连续失败 2 次 → 本链路禁用 |
| 危险 App | `bundle_id` 黑名单（设置/钱包/银行/系统更新）→ 未在 `allowlist` 内一律拒绝启动 |
| 敏感界面 | OCR 命中"支付/密码/验证码/删除/抹掉"等词 → 暂停并 `cw_ask_user` 二次确认 |
| 停止 | 三处入口：PC 前端大红按钮、手机 App 红按钮、语音/文字停止词；停止立即清空队列并打断设备端序列 |
| 日志 | 全程 `logs/catpaws_ops_<date>.jsonl`，可回放 |
| token | Bearer；错误即终止链路 |

停止词默认：`停止操作 / 停止 / 停下 / 别操作了 / 取消操作 / 退出操作 / 算了`（只在链路激活时生效）。

---

## 7. 操作日志（journal）

```json
{"ts":"2026-01-01T12:00:00.123+08:00","session":"s_01","phase":"running",
 "kind":"single","action":"tap","params":{"x":585,"y":1266},
 "ok":true,"code":"OK","elapsed_ms":38,
 "screen":{"pixel":[1179,2556],"scale":3.0},
 "thumb":"logs/catpaws_thumbs/s_01_0007.jpg",
 "action_id":null,"note":""}
```

* `kind`：`single` / `sequence`（含 `steps` 数组）/ `action` / `observe` / `ask` / `phase`
* 每次状态变化（进入 running/reflecting、被停止、超限）都写一条
* 缩略图：每次操作后按配置抓一张（默认开、jpg 质量 60、长边 320），给前端时间线用

---

## 8. 前端

保留现有控制台逻辑（初始化连接、动作列表、运行/停止），改成左右布局：

```
┌───────────────────────┬──────────────────────────┐
│  手机实时画面          │  操作过程（时间线）        │
│  WebCodecs 解码 H.264  │  阶段切换 / 动作 / 结果    │
│  （订阅 8081 中继）     │  缩略图 / 耗时 / action 名 │
├───────────────────────┴──────────────────────────┤
│  ▶ 开始链路  ■ 停止   状态：设备/会话/中继         │
└──────────────────────────────────────────────────┘
```

* 视频：`ws://127.0.0.1:8081/ws?role=viewer&src=screen&token=`，帧格式与 `.cam` 相同，可复用其 viewer 解码逻辑。
* 操作过程：轮询或 WS 推送 `{"t":"op",...}`，与手机 App 共用同一份事件。
* 不引入前端框架（继续 vanilla JS），页面拆分成 `web/index.html` + `web/js/{viewer.js,timeline.js,session.js}`，单文件 ≤800 行。

---

## 9. PC 侧代码结构

```
.vendor/.CatPaws/
├── src/
│   ├── cw/
│   │   ├── protocol.py       动作/结果数据模型 + 参数校验（纯函数）
│   │   ├── config.py         读主项目 config.yml 的 catpaws 段
│   │   ├── geometry.py       像素坐标校验
│   │   ├── device_client.py  aiohttp → /cw/v1/*，重试与会话自愈
│   │   ├── mock_device.py    无手机时的回放驱动（开发/自测）
│   │   ├── guard.py          保护措施（步数/频率/黑名单/敏感词/停止）
│   │   ├── journal.py        操作日志 + 缩略图
│   │   ├── ops.py            三类操作统一入口（single/sequence/action 分发）
│   │   ├── actions_store.py  action 目录、manifest、状态机
│   │   ├── actions_review.py 静态审查 + compile
│   │   ├── actions_runner.py 子进程执行 + JSONL 双向协议
│   │   ├── script_api.py     注入给脚本的 cw_script 模块
│   │   ├── llm_client.py     OpenAI 兼容（含视觉消息拼装）
│   │   ├── agent.py          阶段机 + 循环 + 工具分发
│   │   ├── agent_tools.py    工具 schema（按阶段生成）
│   │   ├── relay.py          8081 WS 中继（设备/观看端/控制）
│   │   ├── web.py            8080 前端 + 控制 API
│   │   └── server.py         进程入口
│   └── server/ screen/       旧代码：逐步退化为薄壳或删除
├── actions/                  每个 action 一个文件夹
├── web/                      前端静态页
├── docs/                     CW_IOS_SPEC.md / CW_PLAN.md
└── logs/                     无（日志统一落项目根 logs/）
```

* 所有类 `CW` 前缀，零注释，单文件 ≤800 行。
* 旧 `/api/run_action` 保留为兼容壳，内部转发到 `ops.py`。

---

## 10. 配置（主项目 config.yml 新增段）

```yaml
catpaws:
  enabled: true
  host: 127.0.0.1
  port: 8080
  relay_port: 8081
  token: ""
  runner_bundle_id: com.<team>.catpawrunner
  app_bundle_id: com.<team>.catpaw
  device_ip: 127.0.0.1
  device_port: 8100
  reflect_enabled: true
  max_steps_per_session: 200
  session_timeout_sec: 900
  app_allowlist: []
  app_denylist: ["com.apple.Preferences", "com.apple.mobilesafari.settings"]
  llm:
    base_url: https://api.deepseek.com/v1
    api_key: ""
    model: deepseek-chat
    vision_model: qwen-vl-max
    vision_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    vision_api_key: ""
```

手机端 App 的 7 项配置在 App 内（UserDefaults），不进 config.yml。

---

## 11. func/catpaws（主项目侧）

```
func/catpaws/
├── __init__.py
├── config.py      CWCatPawsConfig     读 config.yml → catpaws
├── client.py      CWCatPawsClient     HTTP → CatPaws 8080（start/stop/status/answer）
├── if_start.py    CWCatPawsIfStart    前缀 + 关键词判定，抽目标；停止词判定
├── state.py       CWCatPawsState      .temp/catpaws_state.json（active/session/goal）
├── stop.py        CWCatPawsStop       停止词命中 → 调 client.stop()
├── voice.py       CWCatPawsVoicePort  语音接口占位（ask 回调），本轮不实现
└── core.py        CWCatPawsCore       start(goal)/stop()/status()，回调给主项目
```

* 结构对齐 `func/meowsinger`（`if_start` / `stop` / `state` / `core` / `config`）。
* **不建语音链路**：`voice.py` 只定义 `ask(text) -> answer` 与 `on_question` 回调签名，实际语音留给 `msg` + `sensevoice` 接。
* 不接 pipeline：本轮只提供可被调用的入口与状态，`qq_response` / 快回截断等接线等后续方案。

---

## 12. 里程碑

| # | 内容 | 可验证点 |
|---|---|---|
| M1 | `protocol/config/geometry/device_client/mock_device/journal/guard` | 用 mock 驱动跑通 single + sequence，日志与保护措施生效 |
| M2 | `actions_store/review/runner/script_api` | 手写一个 action 跑通；AI 写脚本被审查拦截/放行符合规则 |
| M3 | `llm_client/agent/agent_tools` | 一句目标 → 自动观察/操作/结束 → 反思阶段；running 阶段看不到写脚本工具 |
| M4 | `relay/web` | 前端左屏右时间线；手机视频接入；停止按钮可用 |
| M5 | `func/catpaws` + `config.yml` | 主项目调用 start/stop；停止词生效 |
| 并行 | iOS 规范已交付 | macOS agent 按 `CW_IOS_SPEC.md` 做 M1~M4 |

---

## 13. 明确不做

* 不做视频流进模型（AI 只看截图/OCR）
* 不做单 App 合并（iOS 限制，已定双 target）
* 不在运行时新建 action（只在反思阶段）
* 不建语音链路（只留接口）
* 不接 pipeline 桥接与快回截断（后续方案）
* 不支持安卓（但驱动接口按可分叉设计，`cw_*` 动作名与坐标契约保持不变）
* 不做横屏操作（本期返回 `E_UNSUPPORTED`）

---

## 14. 实现状态（PC 侧已落地）

| 模块 | 文件 | 状态 |
|---|---|---|
| 协议与校验 | `src/cw/protocol.py` | ✅ 动作白名单、参数范围、`delay_ms` 钳制到 90..2000 |
| 坐标 | `src/cw/geometry.py` | ✅ 像素↔点、越界、竖屏校验 |
| 配置 | `src/cw/config.py` | ✅ 读主项目 `config.yml` → `catpaws`，日志目录不可写时回落到临时目录 |
| 设备驱动 | `src/cw/device_client.py` | ✅ `/cw/v1/*` 客户端 + 错误码映射 |
| mock 驱动 | `src/cw/mock_device.py` | ✅ 合成截图 + OCR 框，无手机也能跑通全链路 |
| 保护措施 | `src/cw/guard.py` | ✅ 步数/速率/黑名单/敏感词/时长 |
| 操作日志 | `src/cw/journal.py` | ✅ jsonl + 环形缓存 + 缩略图 |
| 链路状态 | `src/cw/session.py` | ✅ 阶段机 + 阻塞式提问 |
| 三类操作 | `src/cw/ops.py` | ✅ single/sequence/action 统一入口 |
| action 存储 | `src/cw/actions_store.py` | ✅ manifest/状态机/锁定与更新规则 |
| action 审查 | `src/cw/actions_review.py` | ✅ ast + import 白名单 + 禁用调用 |
| action 执行 | `src/cw/actions_runner.py` | ✅ 子进程 + JSONL 双向协议 + 超时/取消 |
| 脚本 API | `src/cw/script_api.py`、`src/cw_script.py` | ✅ emit/observe/ask/params/log/done |
| LLM | `src/cw/llm_client.py` | ✅ OpenAI 兼容 + 视觉消息 |
| 工具表 | `src/cw/agent_tools.py` | ✅ 按阶段生成，running 无 `cw_write_action` |
| agent | `src/cw/agent.py` | ✅ 观察→操作→反思循环 + 提问 + 停止 |
| 视频中继 | `src/cw/relay.py` | ✅ WS、token、vcfg/reqkey、帧转发、操作事件下发 |
| 控制台 | `src/cw/web.py` + `web/` | ✅ 左画面右操作过程 + 开始/停止/视频/截图 |
| 入口 | `src/cw/server.py`、`start.bat` | ✅ 设备不可达自动降级 mock |
| 主项目模块 | `func/catpaws/` | ✅ config/client/if_start/state/stop/voice/core |
| 示例 action | `actions/jump_jump/` | ✅ 纯 CV 跳一跳（unverified，真机跑通后自动转 verified） |
| iOS 端 | `docs/CW_IOS_SPEC.md` | 📄 规范已交付，代码由 macOS agent 实现 |

待接入（按之前约定不做）：pipeline 桥接与快回截断、语音问答双通道、前端配置页、GUI 启动卡按钮。
