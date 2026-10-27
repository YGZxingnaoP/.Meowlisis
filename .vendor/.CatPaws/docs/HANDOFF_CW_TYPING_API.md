# CW 打字 / 焦点 / 元素 / 弹窗 API —— 交接给 Meowlisis 工作区

> 目标：把「AI 打不了字」从根上解决——设备端补 4 个端点 + 2 个小扩展，PC 端补工具与凭据通道。
> 本文是**契约**：设备端（WDA 工作区）按 §2 实现，PC 端（Meowlisis）按 §3 适配。
> 版本：提案 v1，对应 runner **1.1.0**（当前 1.0.7，未实现）。
> 日期：2026-10-27。

---

## 0. 结论、分工、兼容原则

| 端 | 要做什么 | 状态 |
|---|---|---|
| 设备端（`connector/WDA`，runner） | §2 的 4 个端点 + §2.5 的两个小扩展 | **未实现**（§7 是实现指引） |
| PC 端（`D:\.Meowlisis\.vendor\.CatPaws`） | §3 的客户端方法、3 个新工具、凭据库、降级与回归 | 本文要适配的部分 |
| `.cam` / CatCam | 无关，不动 | — |

**兼容原则（硬约束）**

1. 全部是**新增**：不改 `/cw/v1/ping|device|actions|stop|screenshot|ocr|paste` 的既有语义与字段。
2. PC 必须 **feature-detect**：读 `/device.capabilities`，没有 `find/type/focus` 就继续走旧路径（`cw_input`/`cw_keys`/`cw_paste`/`paste_text`）。
3. 老 runner 对新路径返回 404（`/cw/v1/*` 通配），PC 捕获 `E_NOT_FOUND` 后自动降级，只 warning 一次。
4. 新错误码只增不改；PC 对未知错误码按 `E_INTERNAL` 处理并原样展示。
5. 设备端所有坐标一律**截图像素**（左上原点），与 `/device.screen.pixel` 同源。

### 0.1 状态矩阵

| 端点 / 能力 | runner 1.0.7 | runner 1.1.0（本文） | PC 现在 | PC 目标 |
|---|---|---|---|---|
| `GET /cw/v1/focus` | ✗ | ✓ | ✗ | `device_client.focus()` |
| `POST /cw/v1/find` | ✗ | ✓ | 仅 `wda.py` 私有 class chain | `device_client.find()` |
| `POST /cw/v1/type` | ✗ | ✓ | 拼 `paste_text`/`type_text`/`cw_input` | `device_client.type_text()` |
| `GET/POST /cw/v1/alert*` | ✗ | ✓ | ✗ | `device_client.alert()` |
| `tap_element` | ✗ | ✓ | ✗ | `actions([{action:"tap_element",id}])` |
| `press_key` 扩展 | 5 个键 | +7 个键 | 5 个键 | 12 个键 |

---

## 1. 为什么（现状失败点，全部有代码依据）

| 场景 | 现在怎么走 | 为什么失败 |
|---|---|---|
| 密码框 | `paste_text` / `cw_input` | iOS **禁止粘贴进 secure field**（`CWPasteboard.m` 只对焦点元素长按）；`wda.py` 用 `value` 回读校验，secure 字段回读是掩码 → 永远判失败 |
| 手机号 / 数字键盘 | `type_text`（ASCII） | 依赖“已有第一响应者”（`CWKeyboard.m` → `FBTypeText`）；点偏一点就打到别处，且没有焦点查询 |
| 验证码 / 自定义键盘 | `cw_keys` OCR 认键 | 只认 a-z0-9；自定义键盘没有 `TextField` 元素；输入后是圆点/逐格，OCR 看不到结果 |
| 中文 | `paste_text` / `cw_input` | 粘贴菜单可能不出现（5 s 超时）；secure 字段直接不可用 |
| 系统弹窗 | 无 | “允许粘贴”“存储密码”“本地网络” 会挡住 UI，agent 不知道 |
| 任何输入后确认 | `_verify_text()` 用 OCR | OCR 读不到掩码、读不到光标、读不到“占位符 vs 已输入” |

根因一句话：**没有“焦点是谁 / 有哪些控件 / 这次输入成没成”的观测通道**，只能靠 OCR 猜。本提案就是补这三件事。

---

## 2. 设备端契约（runner 1.1.0）

### 2.0 通用约定

- 信封与现有完全一致：
  ```json
  {"protocol":"cw/1","ok":true,"code":"OK","message":"","elapsed_ms":12,"data":{…}}
  ```
- 鉴权：同现有 `CWToken`（`Authorization: Bearer`），空 = 不校验。
- 串行：新端点与 `/actions` 共用**同一把动作锁**；`/stop` 能打断（在 clearance / 输入 / 回读之间检查）。
- 能力：`GET /cw/v1/device` 的 `capabilities` 增加
  `"focus"`, `"find"`, `"type"`, `"alert"`, `"tap_element"`, `"press_key_ext"`。
- 版本：`GET /cw/v1/ping` 的 `version` ≥ `1.1.0`。
- 错误码沿用：`E_BAD_REQUEST` `E_UNAUTHORIZED` `E_UNSUPPORTED` `E_OUT_OF_RANGE`
  `E_DEVICE_LOCKED` `E_SESSION_LOST` `E_TIMEOUT` `E_BUSY` `E_CANCELLED`
  `E_NOT_FOUND` `E_INTERNAL`；**新增两个**：
  - `E_NOT_FOCUSED` —— 点了目标但焦点没落上去 / 当前没有第一响应者；
  - `E_SECURE_FIELD` —— 对安全输入框做了不允许的操作（粘贴、回读明文）。
- 元素 id：由 `/find` 生成，**30 秒**或下一次 `/find`、`/actions`、会话重建后失效；PC 不得长期缓存。

### 2.1 `GET /cw/v1/focus`

返回当前第一响应者与键盘状态。**任何输入前都先调它**。

```json
{
  "focus": {
    "found": true,
    "id": "e2",
    "type": "XCUIElementTypeTextField",
    "label": "手机号",
    "value": "",
    "secure": false,
    "enabled": true,
    "rect": [40, 512, 600, 88]
  },
  "keyboard": {
    "visible": true,
    "bounds": [0, 1580, 1284, 1198],
    "kind": "numeric"
  }
}
```

- 没有焦点：`"focus": {"found": false}`，`keyboard` 仍然返回。
- `secure: true` 时 `value` 一律 `""`（不回掩码内容）。
- `kind`：`"alphabetic" | "numeric" | "unknown"`，由键盘按键探测（有字母键=alphabetic，只有数字/符号=numeric）。
- 实现：`XCUIApplication.fb_focusedElement`（snapshot `hasKeyboardFocus`），
  键盘 `app.keyboards.firstMatch`；`rect` 用 `fb_frame` × scale 转像素。
- 耗时目标 ≤ 150 ms；不截图。

### 2.2 `POST /cw/v1/find`

按语义找控件，返回可点击/可输入的列表，替代“OCR 猜坐标”。

请求：

```json
{"using":"label","value":"手机号","limit":20,"visible_only":true}
```

| `using` | 语义 |
|---|---|
| `label` | 先精确匹配 `label`，没有再做大小写不敏感的包含匹配 |
| `text` | `label` 或 `value` 包含 |
| `value` | `value` 精确 |
| `type` | `XCUIElementTypeTextField` 这类类型名 |
| `class_chain` | 原样透传（兼容 `wda.py` 现有用法） |
| `predicate` | 原样透传 |
| `id` | 按已有 id 刷新 `rect`（用于“列表滚了但元素还在”） |

- `limit`：1..50，默认 20；超限 `E_BAD_REQUEST`。
- `visible_only`：默认 `true`（`hittable` + 在屏内）。
- 只返回可交互或可读的元素：`TextField / SecureTextField / TextView / SearchField / Button / Cell / StaticText / Switch / Slider`。
- 排序：`y` 升序，再 `x` 升序。
- 响应体积：≤ 32 KB；超了截断并置 `"truncated": true`。

响应：

```json
{
  "count": 2,
  "truncated": false,
  "elements": [
    {"id":"e2","type":"XCUIElementTypeTextField","label":"手机号",
     "value":"","secure":false,"enabled":true,"focused":true,
     "rect":[40,512,600,88]},
    {"id":"e3","type":"XCUIElementTypeSecureTextField","label":"密码",
     "value":"","secure":true,"enabled":true,"focused":false,
     "rect":[40,624,600,88]}
  ]
}
```

- `secure` 判定：`elementType == XCUIElementTypeSecureTextField`。
- 错误：`E_BAD_REQUEST`（参数/limit）、`E_UNSUPPORTED`（using 不认识）、`E_DEVICE_LOCKED`、`E_BUSY`。
- 实现：`XCUIApplication` 的 `descendantsMatchingType` / `matchingPredicate` / class chain；
  `fb_frame`、`fb_isVisible`、`fb_hasKeyboardFocus`。

### 2.3 `POST /cw/v1/type`

一次性完成「定位 → 聚焦 → 清空 → 输入 → 回读 → 提交」。

请求：

```json
{
  "text": "13800138000",
  "target": {"id": "e2"},
  "clear_first": true,
  "submit": false,
  "mode": "auto"
}
```

- `target` 三选一：`{"id":"e2"}` / `{"label":"手机号"}` / `{"x":340,"y":556}`；省略 = 当前焦点。
- `mode`：
  - `auto`：ASCII → `keys`（HID，数字键盘可用）；非 ASCII → `setvalue`；`setvalue` 失败且非 secure → `paste`；
    secure + 非 ASCII → **`E_SECURE_FIELD`**（iOS 不允许粘贴进安全输入框）。
  - `keys`：`FBTypeText`（只接受 ASCII，否则 `E_BAD_REQUEST`）。
  - `setvalue`：WDA `setValue`（支持中文/emoji）。
  - `paste`：剪贴板 + 长按 + 菜单（复用现有 `CWPasteboard`）；secure 直接 `E_SECURE_FIELD`。
- `clear_first`：`element.clear()`；失败则 select-all + delete；secure 用 delete 连按。
- `text`：≤ 4096 字符，禁止 `\0`；换行请用 `submit` 或 `press_key return`。
- 整次超时 10 s，单步 3 s；期间可被 `/stop` 打断（`E_CANCELLED`）。

响应：

```json
{
  "ok": true,
  "strategy": "keys",
  "secure": false,
  "readback": "13800138000",
  "match": true,
  "focus": {"id":"e2","type":"XCUIElementTypeTextField"},
  "keyboard": {"visible":true,"kind":"numeric"}
}
```

- secure 字段：`{"ok":true,"strategy":"keys","secure":true,"filled":true,"readback":""}`；
  **绝不返回明文**；`filled` 由「掩码长度变化」或「value 非空」判断。
- 失败码：`E_NOT_FOCUSED`（tap 后仍无焦点）、`E_SECURE_FIELD`、`E_BAD_REQUEST`、
  `E_BUSY`、`E_DEVICE_LOCKED`、`E_TIMEOUT`、`E_CANCELLED`。
- 实现要点：tap 目标 → 等 `hasKeyboardFocus`（≤ 1.5 s，50 ms 轮询）→ clear → 输入 → 读回；
  `keys` 后如果 `readback != text`（非 secure）返回 `ok:false, match:false`，**不要**静默成功。

### 2.4 系统弹窗

`GET /cw/v1/alert`

```json
{"present":true,"title":"允许“QQ”使用你的位置？","message":"",
 "buttons":[{"label":"不允许","index":0},{"label":"允许","index":1}]}
```

- 同时查当前 app 与 SpringBoard（`XCUIApplication.fb_systemApplication`）。
- 无弹窗：`{"present":false,"buttons":[]}`。

`POST /cw/v1/alert/accept` / `POST /cw/v1/alert/dismiss`

```json
{"button":"允许"}
```

- `button` 或 `index` 二选一；都不给时：accept 选第一个含 `允许/Allow/好/OK/继续` 的按钮，dismiss 选第一个含 `不允许/Don't/取消/Cancel` 的按钮，找不到用 index 0。
- 响应：`{"present":true,"accepted":true,"button":"允许"}`；没有弹窗 → `E_NOT_FOUND`。
- 覆盖：本地网络、相机/麦克风、**粘贴授权**、保存密码、通知。OTP 自动填充条能识别就列，识别不到就 `present:false`。

### 2.5 两个小扩展

1. `press_key` 新增：`escape`、`tab`、`space`、`arrow_up`、`arrow_down`、`arrow_left`、`arrow_right`；
   实现 `typeKey:` + `XCUIKeyboardKey*`；`space` 允许退化为 `typeText(" ")`。
   仍保留：`home`、`volume_up`、`volume_down`、`delete`、`return`。
2. `/actions` 新增步骤：`{"action":"tap_element","id":"e2"}`。
   id 来自 `/find`，TTL 30 s；失效返回 `E_NOT_FOUND`。
3. `GET /screenshot?region=x,y,w,h` **已有**，PC 直接用于输入框局部截图，无需设备端改动。

---

## 3. PC 端（Meowlisis）适配清单

### 3.1 改哪些文件

| 文件 | 改动 |
|---|---|
| `src/cw/device_client.py` | 新增 `focus()` / `find()` / `type_text()` / `alert()` / `accept_alert()` / `dismiss_alert()`；`supports(feature)` 读 capabilities 缓存 |
| `src/cw/protocol.py` | 错误码加 `E_NOT_FOCUSED`、`E_SECURE_FIELD`；`describe()` 补文案 |
| `src/cw/agent_tools.py` | 新工具 `cw_find` / `cw_type` / `cw_alert`；`cw_observe` 附带 `焦点/键盘` 摘要；旧工具标 deprecated |
| `src/cw/agent.py` | 提示词规则：输入前先 `cw_find`；密码/验证码只走 `cw_type(secret_id)`；动作前先 `cw_alert` |
| `src/cw/guard.py` | secret 策略：密码类目标需确认；journal 里 text 脱敏；`secret_id` 不进 LLM |
| `src/cw/journal.py` | `text` 一律写 `"***"`，只记 `len` 与 `strategy` |
| `src/cw/config.py` / `config.yml` | 新增 `catpaws.typing`、`catpaws.secrets` 段（见 §3.4） |
| `web/`（可选） | 操作记录里显示 `strategy / secure / filled` |

不要改：`/cw/v1` 信封、`/actions` 旧动作语义、`/paste`、`/ocr`、`/screenshot`、`cw_sequence` 的纯手势约束。

### 3.2 feature 检测与降级

```python
caps = client.capabilities()          # GET /device.data.capabilities
typing_ready = {"focus", "find", "type"} <= set(caps)
alert_ready  = "alert" in caps
```

- `typing_ready` 为真 → 注册 `cw_find`/`cw_type`；
- 为假 → 只注册旧工具（`cw_input`/`cw_keys`/`cw_paste`），启动日志 warning 一次“runner 未升级，打字走旧路径”；
- 运行中新端点返回 `E_NOT_FOUND`/`E_UNSUPPORTED` → 本次会话永久降级，避免反复失败；
- `alert_ready` 为假 → `cw_alert` 返回 `{"text":"runner 不支持弹窗接口","error":true}`。

### 3.3 工具契约（PC → LLM）

**`cw_find`**

```json
{"using":"label","value":"手机号","limit":10}
```

返回文本（不返回图片）：

```
找到 2 个（y 排序）：
e2 TextField “手机号” rect=(40,512,600,88) focused=1
e3 SecureTextField “密码” rect=(40,624,600,88)
```

- 无结果 → 建议“先 `cw_observe(ocr)` 确认界面，或换 `using=text`”；
- `limit` 默认 10，最大 50。

**`cw_type`**

```json
{"text":"13800138000","target":{"label":"手机号"},"clear_first":true,"submit":false}
```

或

```json
{"secret_id":"qq_password","target":{"label":"密码"},"submit":true}
```

- `text` 与 `secret_id` **互斥**，同时给 → `E_BAD_REQUEST`；
- `secret_id` 时 PC 从凭据库取值，**明文不进 transcript、不进 journal**；
- 工具返回：`已输入（keys，secure=0，回读一致）` / `已输入（keys，secure=1，已填充）`；
- 失败原样给错误码 + 建议（见 §3.5）。

**`cw_alert`**

```json
{"action":"accept|dismiss|query","button":"允许"}
```

- `query` 只返回标题与按钮列表，不点；
- 建议 agent 在 `launch_app` 之后、以及任何 `E_NOT_FOCUSED` 时先 `query` 一次。

### 3.4 凭据库（最小实现）

- 存储：Windows **DPAPI** 加密文件（`.temp/cw_secrets.dpapi`）或 `keyring`（服务名 `meowlisis.catpaws`）；**不要**放 `config.yml` 明文。
- 接口：`secrets.put(id, text)`、`secrets.get(id)`、`secrets.list()`（只给 id 与备注）。
- 录入：离线 CLI `scripts/cw_secret.py set qq_password`（stdin 读，不回显），不进 agent 上下文。
- `config.yml` 只放开关：
  ```yaml
  catpaws:
    typing:
      prefer: auto            # auto | keys | setvalue | paste
      secret_confirm: true    # 密码/验证码类目标先问用户
      max_text: 4096
    secrets:
      backend: dpapi          # dpapi | keyring
      file: .temp/cw_secrets.dpapi
  ```
- `secret_id` 找不到 → 工具返回 `E_SECRET_MISSING`（PC 自定义）并提示“先运行 `scripts/cw_secret.py set <id>`”。

### 3.5 观测、日志、失败回执

- `cw_observe` 在 OCR/图片后面补一行：
  `焦点：TextField “手机号” 键盘=数字（可见）` —— 让模型知道“现在可以直接 type，不用先点”。
- journal 记录：`tool / target / strategy / elapsed_ms / ok / secure / filled`；`text` 永远 `"***"`。
- 失败回执要可行动：
  - `E_NOT_FOCUSED` → “先 `cw_find` 拿 id，再 `cw_type(target:id)`”
  - `E_SECURE_FIELD` → “这是密码框，改用 `secret_id`；不要用 paste”
  - `E_NOT_FOUND` → “先 `cw_alert query`，再 `cw_observe`”
  - `E_DEVICE_LOCKED` → “先解锁/回桌面再看一眼”

### 3.6 回归与兼容

- 现有 `cw_single/sequence/action/observe/ask_user` 行为不变；
- 旧工具保留一个版本，标 `deprecated`，仅在 `typing_ready == false` 或用户显式要求时使用；
- `cw_sequence` **不支持** `type` / `tap_element`（保持纯手势/按键），不要偷偷塞进去；
- 设备端 1.0.7 上跑新 PC：自动降级，旧路径全通（验收项 §4.3）。

---

## 4. 验收

### 4.1 设备端契约自测（curl，runner 1.1.0）

```bash
# 1) 能力
curl -s http://127.0.0.1:8100/cw/v1/device | jq '.data.capabilities'
# 期望包含 focus/find/type/alert/tap_element/press_key_ext

# 2) 焦点
curl -s http://127.0.0.1:8100/cw/v1/focus | jq '.data.focus.found'

# 3) 找输入框
curl -s -X POST http://127.0.0.1:8100/cw/v1/find \
  -H 'Content-Type: application/json' \
  -d '{"using":"label","value":"手机号","limit":5}' | jq '.data.elements[0]'

# 4) 输入数字（手机号）
curl -s -X POST http://127.0.0.1:8100/cw/v1/type \
  -H 'Content-Type: application/json' \
  -d '{"text":"13800138000","target":{"label":"手机号"},"clear_first":true}' | jq '.data'

# 5) 密码（secure）
curl -s -X POST http://127.0.0.1:8100/cw/v1/type \
  -H 'Content-Type: application/json' \
  -d '{"text":"Passw0rd!","target":{"label":"密码"},"submit":true}' | jq '.data'
# 期望 secure=true、readback=""、filled=true、无明文

# 6) 弹窗
curl -s http://127.0.0.1:8100/cw/v1/alert | jq '.data.present'
curl -s -X POST http://127.0.0.1:8100/cw/v1/alert/accept -d '{}' | jq '.data'
```

### 4.2 PC 端场景（真机）

| # | 场景 | 期望 |
|---|---|---|
| 1 | 手机号登录：`cw_find label=手机号` → `cw_type` | `match=true`，1.5 s 内 |
| 2 | 中文昵称（搜索框） | `strategy=setvalue`，回读一致 |
| 3 | 密码：`cw_type secret_id` | `secure=true, filled=true`，transcript/journal 无明文 |
| 4 | 验证码：自定义键盘 | `cw_find` 找到数字键 → `tap_element` 逐位，或 `cw_type` 直输 |
| 5 | 弹窗：首次启动权限 | `cw_alert accept` 后界面可操作 |
| 6 | 失败恢复 | 找不到字段 → `alert query` → `home` → 重来，不卡死 |
| 7 | 旧 runner 降级 | 1.0.7 上跑新 PC：旧路径全通，只 warning 一次 |

### 4.3 指标

- 单次 `type`（不含网络）≤ 1.5 s；`find` ≤ 400 ms；`focus` ≤ 150 ms；
- 密码流程成功率 ≥ 8/10；手机号 ≥ 9/10；
- 明文泄漏 = 0（检查 transcript、journal、控制台）。

---

## 5. 迁移顺序

| 阶段 | 设备端 | PC 端 | 可回滚 |
|---|---|---|---|
| P0 | — | 加客户端方法 + 能力探测，**行为不变** | 是 |
| P1 | `focus` + `find` + `type`（auto/keys/setvalue） | 注册 `cw_find`/`cw_type`，旧工具保留 | 是（capabilities 一关就回旧路） |
| P2 | `alert` + `press_key` 扩展 + `tap_element` | 注册 `cw_alert`，`observe` 加焦点行 | 是 |
| P3 | — | 旧工具标 deprecated，默认只走新路径 | 是（保留开关） |

---

## 6. 明确不做

- 不做 `/source` 全量控件树（太大，`find` 足够）；
- 不做 XPath、元素截图、多指手势扩展；
- 不保证 WebView 内元素（WKWebView 依赖 WDA 的 webview 支持，另行评估）；
- 不改进 OCR（OCR 只保留为“兜底观察”，不再用于输入校验）；
- 不碰 `.cam` / CatCam。

---

## 7. 设备端实现指引（WDA 工作区）

新增文件（`CustomCode/WebDriverAgentLib/CW/`）：

| 文件 | 内容 |
|---|---|
| `CWFocus.h/m` | 第一响应者 + 键盘状态（`GET /focus`） |
| `CWFind.h/m` | 元素查询 + id 缓存（`POST /find`） |
| `CWType.h/m` | 聚焦/清空/输入/回读/提交（`POST /type`） |
| `CWAlert.h/m` | 弹窗读取与接受/取消 |
| `CWApiPaths.h/m` | 加 4 组路径常量 |

改动：

- `CWServer.m`：注册路由；`capabilities` 加 6 项；
- `CWActionStep.m/.h`：`tap_element`（读 `id`）；
- `CWKeyboard.m`：`pressKey:` 扩 7 个键（`XCUIKeyboardKeyEscape/Tab/Space/UpArrow/...`）；
- `CWSessionManager`：会话重建时清空元素缓存；
- `WebDriverAgentRunner/Info.plist`：版本 → `1.1.0`。

实现要点：

1. **元素缓存**：`NSMutableDictionary<NSString *, XCUIElement *>` + `NSMutableDictionary<NSString *, NSDate *>`；
   id 用 `e1/e2/...` 自增；30 s 清理；`/actions` 开始与会话重建时全清。
2. **焦点**：`XCUIApplication.fb_focusedElement`；判定 `snapshot.hasKeyboardFocus`；
   没有焦点时不要用 `app.textFields.firstMatch` 猜。
3. **secure**：`elementType == XCUIElementTypeSecureTextField`；读回只取长度（掩码字符数），不取内容。
4. **输入**：`keys` 用 `FBTypeText`；`setvalue` 用 `/element/:id/value` 同一实现（`handleSetValue:`）；
   `paste` 复用 `CWPasteboard`；每步后校验 `hasKeyboardFocus` 与 `value`（非 secure）。
5. **超时/停止**：复用 `CWActionRunner` 的串行队列与 stop 标志，在 clear / 输入 / 回读之间检查。
6. **错误映射**：无焦点 → `E_NOT_FOCUSED`；secure 粘贴/明文 → `E_SECURE_FIELD`；
   参数 → `E_BAD_REQUEST`；id 过期 → `E_NOT_FOUND`；锁屏 → `E_DEVICE_LOCKED`。
7. **不要**把明文写进 `wda.log`；secure 的 text 只记 `len`。

---

## 8. 参考（现有实现位置）

设备端：

- 端点注册：`CustomCode/WebDriverAgentLib/CW/CWServer.m`
- 动作执行：`CW/CWActionRunner.m`、`CW/CWActionStep.m`
- 键盘：`CW/CWKeyboard.m`；粘贴：`CW/CWPasteboard.m`；OCR：`CW/CWOCREngine.m`
- 几何：`CW/CWGeometry.m`（像素/点/scale 同源）
- 上游参考：`WebDriverAgentLib/Routing/FBWebServer.m`、`Commands/FBElementCommands.m`、`Commands/FBDebugCommands.m`

PC 端：

- `src/cw/device_client.py`、`src/cw/agent_tools.py`、`src/cw/wda.py`、`src/cw/guard.py`、`src/cw/journal.py`
- 现有交接：`.vendor/.CatPaws/docs/HANDOFF_TO_MEOWLISIS.md`（本文件是它的增量，不替代）
