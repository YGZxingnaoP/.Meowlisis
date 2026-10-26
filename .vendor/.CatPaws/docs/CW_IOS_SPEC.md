# CatPaws iOS 端实现规范 v1

本文给 macOS 上的 Xcode agent。读完应能独立搭出工程、实现全部接口、通过验收清单。

配套文档：`CW_PLAN.md`（PC 侧方案与整体架构）。两者冲突时以本文的接口契约与坐标规则为准。

---

## 0. 边界与硬约束

| 项 | 要求 |
|---|---|
| 设备 | iPhone，iOS 17 及以上，**不越狱**，不上架 App Store |
| 触摸注入 | 只用 XCTest（XCUICoordinate / XCUIApplication / XCUIDevice），禁止私有 API、禁止 IOHIDEvent 注入 |
| 坐标 | 对外一律**截图像素**（左上原点、整数）；像素→逻辑点的换算**只在设备端**发生 |
| 代码 | 零注释；所有类名 `CW` 前缀；单文件 ≤800 行；模块化拆分 |
| 空闲开销 | 无连接、无操作时 CPU 接近 0（禁止轮询循环、禁止常驻定时器扫屏） |
| 断连 | PC 断开、Unix 隧道断开、屏幕锁定，App 与 Runner 都不得崩溃 |

本文里"标准动作"指 PC 侧 `/cw/v1/actions` 里的 `action` 名，**不是** WDA/W3C 的动作名。PC 永远看不到 W3C actions 结构，也永远不传逻辑点。

---

## 1. 工程结构

一个 workspace，两个可运行 target，一个扩展。

```
CatPaws.xcworkspace
├── CatPaw/                       常规 App（UI、相机、音频、屏幕推流）
│   ├── App/                      CWAppDelegate.swift, CWRootViewController.swift
│   ├── Web/                      CWWebViewController.swift（WKWebView 载入 .cam）
│   ├── Settings/                 CWSettingsViewController.swift
│   ├── Stream/                   CWStreamClient.swift（WS 客户端）, CWStreamController.swift
│   ├── Ops/                      CWOpLogViewController.swift（操作记录）
│   ├── Common/                   CWConfig.swift（UserDefaults 读写）
│   ├── Info.plist
│   └── CatPaw.entitlements
├── BroadcastExtension/           ReplayKit 广播上传扩展
│   ├── CWSampleHandler.swift
│   ├── CWVideoEncoder.swift      VideoToolbox H.264
│   ├── CWAnnexB.swift            AVCC→Annex-B
│   ├── CWStreamSocket.swift      扩展内独立 WS 客户端（不走主 App 内存）
│   └── Info.plist
├── CatPawRunner/                 改自 WebDriverAgentRunner
│   ├── main.m
│   ├── CW/                       ← 本次新增的全部服务端代码
│   │   ├── CWApiRouter.{h,m}     注册 /cw/v1/* 路由
│   │   ├── CWResponse.{h,m}      统一 envelope
│   │   ├── CWGeometry.{h,m}      像素→点、越界校验、屏幕元数据
│   │   ├── CWActionRunner.{h,m}  动作序列执行器 + cancel 标志
│   │   ├── CWOCREngine.{h,m}     Vision
│   │   ├── CWScreenshot.{h,m}    截图 + 缩放/编码
│   │   └── CWSource.{h,m}        精简元素树（可选能力）
│   └── WebDriverAgentRunner-Prefix.pch（沿用）
├── CatPawRunnerTests/            XCTest bundle（runner 的宿主）
├── WebDriverAgentLib/            原样保留（含 PrivateHeaders、RoutingHTTPServer）
└── WebDriverAgentLibTests/       原样保留（可删）
```

### 1.1 Bundle ID 与签名

| target | 建议 bundle id | 签名 |
|---|---|---|
| CatPaw | `com.<team>.catpaw` | 同一开发者证书 |
| CatPawRunner | `com.<team>.catpawrunner` | 同一开发者证书 |
| CatPawRunnerTests | `com.<team>.catpawrunner.xctrunner` | 自动 |
| BroadcastExtension | `com.<team>.catpaw.broadcast` | 同上 |

免费 Apple ID 证书 7 天过期；付费账号 1 年。这两个 bundle id 必须与 PC 端 `config.yml → catpaws.runner_bundle_id` / `catpaws.app_bundle_id` 一致。

### 1.2 命名本地化（"在手机端翻译"）

* 保持 `WebDriverAgentLib` 内部类名不变（`FB*`），**只在路由层翻译**。
* `CWApiRouter` 里每个 handler 的职责固定三步：校验参数 → `CWGeometry` 把像素转成点 → 调现有 WDA 实现（W3C actions / XCUIApplication / 截图）。禁止在 handler 里写业务逻辑。
* 不给 PC 暴露任何 `/session`、`/wda/*` 原始路由的使用方式；原始路由保留但仅供本机调试（监听 127.0.0.1）。若实现成本高，可加启动参数 `CW_ONLY=1` 只注册 `/cw/v1/*`。
* 路由常量集中在一个头文件 `CWApiPaths.h`，避免散落的字符串。

---

## 2. 设备端 HTTP 契约

* 基地址：`http://<device>:8100/cw/v1`（iOS 17 经 `go-ios forward 8100 8100` 映射到 PC 127.0.0.1:8100）
* 鉴权：`Authorization: Bearer <token>`，token 与 PC 配置一致；错误返回 `E_UNAUTHORIZED`
* 编码：请求/响应 `application/json; charset=utf-8`，字段名一律 snake_case
* 时间单位：所有 `*_ms` 为毫秒整数；坐标单位像素整数

### 2.1 统一响应 envelope

```json
{
  "protocol": "cw/1",
  "ok": true,
  "code": "OK",
  "message": "",
  "elapsed_ms": 38,
  "data": {}
}
```

失败也返回 HTTP 200（唯一例外：鉴权失败 HTTP 401、路径不存在 404），body 里 `ok:false`：

```json
{"protocol":"cw/1","ok":false,"code":"E_OUT_OF_RANGE","message":"x=2000 超出屏宽 1179","elapsed_ms":1,"data":{}}
```

### 2.2 错误码

| code | 含义 | PC 行为 |
|---|---|---|
| `OK` | 成功 | 继续 |
| `E_BAD_REQUEST` | 参数缺失/类型错 | 不重试，回灌给 agent 修正 |
| `E_UNAUTHORIZED` | token 错 | 终止链路，提示检查配置 |
| `E_UNSUPPORTED` | 该设备/系统不支持此能力 | 读 capabilities 降级 |
| `E_OUT_OF_RANGE` | 坐标越界 | 不重试，重新观察 |
| `E_DEVICE_LOCKED` | 锁屏 | 提示人工解锁 |
| `E_SESSION_LOST` | XCTest 会话失效 | PC 自动重建一次 |
| `E_TIMEOUT` | 单动作超时 | 重试一次 |
| `E_BUSY` | 已有动作在执行 | 排队 |
| `E_CANCELLED` | 被 `/stop` 打断 | 静默 |
| `E_NOT_FOUND` | action/bundle 不存在 | 报错 |
| `E_INTERNAL` | 其它 | 报错并附 message |

### 2.3 端点清单

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/cw/v1/ping` | 存活探测，不建会话 |
| GET | `/cw/v1/device` | 屏幕元数据 + 系统信息 + 能力列表 |
| POST | `/cw/v1/session` | 建立/重建 XCTest 会话 |
| DELETE | `/cw/v1/session` | 释放会话 |
| POST | `/cw/v1/actions` | **核心**：顺序执行 1..N 个原子动作 |
| POST | `/cw/v1/stop` | 打断当前动作序列（步间生效） |
| GET | `/cw/v1/screenshot` | 二进制图片 |
| POST | `/cw/v1/ocr` | Vision 文本识别，返回像素框 |
| POST | `/cw/v1/paste` | 写剪贴板（中文输入兜底） |
| GET | `/cw/v1/source` | 精简元素树（可选能力） |

### 2.4 `GET /cw/v1/ping`

```json
{"protocol":"cw/1","ok":true,"code":"OK","message":"","elapsed_ms":2,
 "data":{"app":"CatPawRunner","version":"1.0.0","build":"1","session":true}}
```

`session:false` 时 PC 会先调 `POST /session`。

### 2.5 `GET /cw/v1/device`

```json
{"protocol":"cw/1","ok":true,"code":"OK","message":"","elapsed_ms":5,
 "data":{
   "screen":{"pixel":[1179,2556],"point":[393,852],"scale":3.0,"orientation":"portrait",
             "safe_area":{"top":59,"bottom":34}},
   "system":{"model":"iPhone15,2","ios":"17.4.1","name":"喵呜的iPhone"},
   "capabilities":["tap","long_press","swipe","pinch","type_text","paste_text",
                   "press_key","launch_app","activate_app","terminate_app",
                   "screenshot","ocr","source"],
   "session":true}}
```

* `pixel` 必须是**截图**的像素尺寸（`XCUIScreen.main.screenshot().image.size` 或 `UIScreen.main.nativeBounds.size`，两者应一致；不一致时以截图为准）。
* `point` 是逻辑尺寸（`UIScreen.main.bounds.size`）。
* `scale = pixel.width / point.width`，保留 1 位小数。
* `capabilities` 必须如实上报：不支持的能力不要列，PC 会据此降级。

### 2.6 `POST /cw/v1/actions`（核心）

请求：

```json
{
  "steps": [
    {"action": "tap", "x": 585, "y": 1266},
    {"action": "wait", "duration_ms": 300},
    {"action": "swipe", "from": [100, 1500], "to": [900, 1500], "duration_ms": 300},
    {"action": "long_press", "x": 590, "y": 1600, "duration_ms": 1200},
    {"action": "pinch", "x": 590, "y": 1200, "scale": 2.0, "duration_ms": 400},
    {"action": "type_text", "text": "hello123"},
    {"action": "paste_text", "text": "你好，喵呜"},
    {"action": "press_key", "key": "delete"},
    {"action": "press_key", "key": "home"},
    {"action": "launch_app", "bundle_id": "com.tencent.xin"},
    {"action": "activate_app", "bundle_id": "com.apple.mobilesafari"},
    {"action": "terminate_app", "bundle_id": "com.tencent.xin"}
  ],
  "delay_ms": 90
}
```

字段语义：

| 字段 | 说明 |
|---|---|
| `steps` | 1..64 个，顺序执行 |
| `delay_ms` | **每个动作之间**的固定延迟。缺省 90；小于 90 一律按 90 执行；大于 2000 按 2000 截断 |
| `tap` | `count` 可选（1..3），间隔 90ms |
| `long_press` | `duration_ms` 200..5000，默认 800 |
| `swipe` | `duration_ms` 100..2000，默认 300；轨迹插值**在设备端**做（约 60fps 采样） |
| `pinch` | `scale` 0.2..5.0（>1 放大，<1 缩小），`duration_ms` 100..2000 |
| `type_text` | **仅 ASCII**（字母/数字/常用符号），超时 3s |
| `paste_text` | 任意 UTF-8：写 UIPasteboard 后走"长按→粘贴"菜单，超时 5s |
| `press_key` | `home` / `volume_up` / `volume_down` / `delete` / `return` |
| `launch_app` / `activate_app` / `terminate_app` | `bundle_id` 必填；`launch_app` 失败返回 `E_NOT_FOUND` |
| `wait` | `duration_ms` 0..10000，用于等待界面动画 |

响应：

```json
{"protocol":"cw/1","ok":true,"code":"OK","message":"","elapsed_ms":4123,
 "data":{"executed":3,
         "results":[{"index":0,"action":"tap","ok":true,"code":"OK","elapsed_ms":38},
                    {"index":1,"action":"wait","ok":true,"code":"OK","elapsed_ms":300},
                    {"index":2,"action":"swipe","ok":true,"code":"OK","elapsed_ms":318}]}}
```

规则：

* 任一步失败 → **立即中止后续步骤**，整个响应 `ok:false`，`code` 取该步错误码，`data.results` 保留已完成部分。
* `/stop` 触发后，当前步做完即中止，剩余步骤不执行，`code="E_CANCELLED"`。
* 同一时刻只允许一个 `/actions` 在跑，第二个进来直接 `E_BUSY`（PC 侧串行，这里只做兜底）。
* 越界坐标在**执行前**整批校验，有任一越界就整批拒绝（避免半执行）。

### 2.7 `POST /cw/v1/stop`

```json
{"protocol":"cw/1","ok":true,"code":"OK","message":"","elapsed_ms":1,
 "data":{"cancelled":true,"remaining_steps":4}}
```

无在执行序列时返回 `cancelled:false`，不算错误。

### 2.8 `GET /cw/v1/screenshot`

查询参数：`format=png|jpeg`（默认 png）、`max_edge=1280`（可选，长边限制，等比缩放）、`quality=85`（jpeg 有效）。

响应：`Content-Type: image/png` 或 `image/jpeg`，二进制原始字节（不是 base64）。

响应头：

```
X-CW-Size: 1179x2556
X-CW-Scale: 3.0
X-CW-Ts: 1735689600123
```

* 必须**原分辨率**截图（不缩放、不降采样），除非传了 `max_edge`。
* 截图要包含状态栏（后续 OCR 需要）。

### 2.9 `POST /cw/v1/ocr`

请求：`{"region": [x, y, w, h], "languages": ["zh-Hans","en-US"]}`，`region` 可省（默认整屏）。

响应：

```json
{"protocol":"cw/1","ok":true,"code":"OK","message":"","elapsed_ms":180,
 "data":{"image_size":[1179,2556],
         "texts":[{"text":"微信","box":[100,760,180,60],"confidence":0.98},
                  {"text":"发送","box":[880,2200,140,64],"confidence":0.95}]}}
```

* `box = [x, y, w, h]`，**截图像素空间**，左上原点。
* Vision 的 boundingBox 是归一化且原点在左下，必须转成像素左上原点（`y_px = (1 - maxY) * height`）。
* 只返回行级结果（不用单词级）；`confidence` 取该行最小值。
* 同一帧 300ms 内重复请求直接返回缓存（防 agent 抖动）。

### 2.10 `POST /cw/v1/paste`

请求：`{"text":"你好","submit":false}`。写 UIPasteboard 并立即执行一次长按粘贴，`submit=true` 时再发一次 `return`。

---

## 3. 坐标与几何

```
像素（PC 与世界）: x_px ∈ [0, pixel_w), y_px ∈ [0, pixel_h)
点  （XCUITest）: x_pt = x_px / scale, y_pt = y_px / scale
```

* 换算在 `CWGeometry` 内完成，**唯一的除法发生在这里**。
* 方向固定竖屏：`GET /device` 的 `orientation` 必须是 `portrait`；检测到横屏时 PC 会先调 `press_key`+`rotate` 或直接拒绝（本期不支持横屏操作，返回 `E_UNSUPPORTED`）。
* 越界判定：`x ∈ [0, pixel_w-1]`、`y ∈ [0, pixel_h-1]`；越界返回 `E_OUT_OF_RANGE`。
* 圆整：转点后 `round()`，但**不要**二次转回像素做校验（会因圆整产生假越界）。

---

## 4. 动作实现映射

保留 WDA 现有 W3C actions 实现，`CWActionRunner` 只负责把标准动作翻译成内部调用。

| 标准动作 | 设备端实现 |
|---|---|
| `tap` | `XCUICoordinate.tap()`；`count>1` 时循环 + 90ms 间隔 |
| `long_press` | `XCUICoordinate.press(forDuration:)` |
| `swipe` | 走 WDA W3C pointer 序列（多点 pointerMove + 时长插值），保持现有手感；或 `press(forDuration:0, thenDragTo:withVelocity:)` 二选一，以验收清单为准 |
| `pinch` | W3C 双 pointer，两指沿过 center 的对角线对称移动；`scale>1` 相离、`<1` 相向 |
| `type_text` | WDA 的 `keys` 实现（HID 键盘事件） |
| `paste_text` | `UIPasteboard.general.string = text` → 长按当前位置 → 点"粘贴" |
| `press_key` | `home/volume_up/volume_down` → `XCUIDevice.shared.press(...)`；`delete` → HID delete；`return` → HID enter |
| `launch_app` | `XCUIApplication(bundleIdentifier:).launch()` |
| `activate_app` | 同上 `.activate()` |
| `terminate_app` | 同上 `.terminate()` |
| `wait` | 设备端 `usleep`，但必须可被 `/stop` 打断（分段 sleep 每 50ms 检查 cancel 标志） |

不要在设备端做"等待界面就绪""重试直到元素出现"这类的智能判断，那是 PC 侧 agent 的事。

---

## 5. 会话与并发

* Runner 启动时自动建一次会话；`GET /ping` 返回 `session` 真实状态。
* 会话失效（切换到某些 App、锁屏后）→ 下一次动作前检测并**自动重建一次**，仍失败返回 `E_SESSION_LOST`。
* 单动作队列：`/actions` 串行；`/stop` 只置 cancel 标志，不 kill 线程。
* 所有 handler 跑在独立串行队列，禁止阻塞主线程（UI 卡顿会导致 XCTest 动作超时）。

---

## 6. OCR（Vision）

| 项 | 值 |
|---|---|
| API | `VNRecognizeTextRequest` |
| recognitionLevel | `.accurate` |
| recognitionLanguages | `["zh-Hans","en-US"]` |
| usesLanguageCorrection | `true` |
| 输入 | 全屏截图（与 `/screenshot` 同一来源，保证坐标系一致） |
| 串行 | 单例 + 串行队列，避免并发吃满 CPU |
| 降级 | Vision 不可用时传 `E_UNSUPPORTED`，PC 会退回"图片直传多模态"模式 |

---

## 7. 屏幕推流（ReplayKit + VideoToolbox）

**视频只给人和前端看，永远不进模型。** AI 的观察通道只有 `/screenshot` 与 `/ocr`。

### 7.1 链路

```
BroadcastExtension.processSampleBuffer
    → 抽帧（按目标 fps 丢帧）
    → VideoToolbox 硬件 H.264 编码（Baseline, RealTime, no B-frames, GOP 2s）
    → AVCC 转 Annex-B
    → WS 二进制帧 → PC 中继 8081
```

### 7.2 帧格式（与 `.cam` 完全一致）

设备→中继（二进制）：

```
byte 0      : 0x01  视频
byte 1      : flags bit0=1 表示关键帧
byte 2..9   : ts_us，uint64 大端
byte 10..   : H.264 Annex-B access unit
```

中继→观看端（二进制）：去掉 byte0：

```
byte 0      : flags
byte 1..8   : ts_us 大端
byte 9..    : H.264 Annex-B
```

控制消息（文本帧，JSON）：

| 方向 | 消息 |
|---|---|
| 设备→中继 | `{"t":"hello","role":"device","src":"screen","app":"1.0.0"}` |
| 设备→中继 | `{"t":"vcfg","codec":"avc1.42E01E","w":1179,"h":2556,"fps":10}`（开始推流后立刻发一次） |
| 设备→中继 | `{"t":"vstop"}`（停止推流时） |
| 设备→中继 | `{"t":"stats","fps":10,"kbps":1150,"dropped":3}` |
| 设备→中继 | `{"t":"stop_request"}`（App 内红色停止按钮） |
| 中继→设备 | `{"t":"start","fps":10,"max_edge":1280,"bitrate":1500000}` |
| 中继→设备 | `{"t":"stop"}` |
| 中继→设备 | `{"t":"reqkey"}` |
| 中继→设备 | `{"t":"ping","id":17}` / 设备回 `{"t":"pong","id":17}` |
| 中继→设备 | `{"t":"op","entry":{...}}`（PC 侧操作日志事件，App 用它渲染操作记录） |

连接地址：`ws://<pc>:8081/ws?role=device&src=screen&token=<token>`

* `role` 与 `src` 既可从查询串带，也可在 `hello` 里带（中继两者都认）。
* token 非空时，查询串里必须带同一个 token，否则中继回 `{"t":"error","code":"E_UNAUTHORIZED"}` 并断开。
* 中继在收到设备 `vcfg` 后转发给所有观看端；没有 `vcfg` 时前端不解码，所以**开始推流后必须发**。

### 7.3 编码参数（默认值，可由 `start` 覆盖）

| 参数 | 默认 | 范围 |
|---|---|---|
| 目标 fps | 10 | 5..20 |
| 长边 | 1280 | 720..原生 |
| 码率 | 1.5 Mbps | 0.5..4 Mbps |
| 关键帧间隔 | 2s 或收到 `reqkey` | — |
| Profile | Baseline（兼容性优先） | — |

### 7.4 性能与内存（扩展只有 50MB）

* **没有观看端就不编码**：只在收到 `start` 后启动编码器；收到 `stop` 立刻停并释放。
* 不缓存历史帧；发送队列上限 8 帧，满了丢最旧。
* 抽帧在编码前做（按时间戳比较），不要"编码完再丢"。
* 编码输出直接转 Annex-B 发送，不做二次装箱。
* 单帧失败只跳过该帧，不重置编码器。

### 7.5 重连

WS 断开后指数退避重连（1s/2s/5s/10s，上限 30s），重连成功立刻请求关键帧。

---

## 8. CatPaw App（常规 target）

### 8.1 主界面：.cam 页面

* 用 `WKWebView` 加载 `https://<pc>:8443/`（PC 上 `.cam` 服务）。
* 必须配置：
  * `WKWebViewConfiguration.allowsInlineMediaPlayback = true`
  * `mediaTypesRequiringUserActionForPlayback = []`
  * `preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")` 不需要；不要开
  * `Info.plist`：`NSCameraUsageDescription`、`NSMicrophoneUsageDescription`、`NSLocalNetworkUsageDescription`
  * 自签证书：`WKNavigationDelegate` 的 `didReceive challenge` 中对 `ServerTrust` 校验 `cert.pem` 指纹（不要无条件信任）
* 页面顶部/底部叠加一层原生 UI（不遮住 .cam 的按钮球）：
  * 连接状态指示灯（.cam / 中继 / Runner 三路）
  * "操作面板"入口按钮
  * **红色停止按钮**（见 8.3）

### 8.2 设置页（7 项）

| key（UserDefaults） | 说明 | 默认 |
|---|---|---|
| `cw_pc_host` | PC 地址（局域网 IP） | 空 |
| `cw_control_port` | CatPaws 服务端口 | 8080 |
| `cw_video_port` | 中继端口 | 8081 |
| `cw_token` | Bearer token | 空 |
| `cw_screen_fps` / `cw_screen_max_edge` / `cw_screen_bitrate` | 屏幕流参数 | 10 / 1280 / 1500000 |
| `cw_allow_ocr` | 允许 PC 调 OCR（隐私开关） | true |
| `cw_start_in_cam` | 启动直接进 .cam 界面 | true |

### 8.3 停止操作

* **PC 可达时**：点红色按钮 → WS 发 `{"t":"stop_request"}` → PC 中止链路并回 `{"t":"op","kind":"stop","by":"app"}`。
* **PC 不可达时**：直接通知 Runner（`127.0.0.1:8100/cw/v1/stop`）兜底。
* 按钮在任何界面常驻（.cam 页 + 设置页 + 操作面板）。
* iOS 不允许跨 App 浮窗，所以**别的 App 在前台时手机端点不到按钮**——跨 App 的停止由 PC 前端按钮与语音停止词负责（已在 `CW_PLAN.md` 的保护措施里）。

### 8.4 "退出 CatPaw"（requirement 5.1）

* 操作面板/设置页返回 .cam 页 = 正常返回，不停任何东西。
* 点"退出 CatPaw"：
  1. 发 `{"t":"stop"}` 停屏幕流，关闭编码器；
  2. Runner 与 `.cam` 页面**继续运行**（相机流、音频、TTS 全部保持）；
  3. App 进入"仅 .cam 模式"，界面回到 .cam 页；
  4. 再次进入操作面板自动重新开屏幕流（需用户已在控制中心开录屏，否则提示去开）。

### 8.5 音频

* `.cam` 页的 TTS 播放靠 WKWebView 的 audio，需要 `UIBackgroundModes = audio` + `AVAudioSession.category = .playback`（`.mixWithOthers` 视实测）才能后台继续播。
* **不新建任何音频链路上行**（麦克风仍由 .cam 页的 getUserMedia 处理）。

### 8.6 操作记录界面

* 通过 WS 从 PC 中继接收 `{"t":"op", ...}` 事件，渲染成时间线（动作名、坐标、结果、耗时）。
* 只保留最近 200 条，落 UserDefaults 可选，不写本地大日志。

---

## 9. 权限与 Info.plist 清单

| target | 键 |
|---|---|
| CatPaw | `NSCameraUsageDescription`、`NSMicrophoneUsageDescription`、`NSLocalNetworkUsageDescription`、`NSPhotoLibraryAddUsageDescription`（导出截图用，可选）、`UIBackgroundModes=[audio]`、`NSAppTransportSecurity`（自签证书域名/IP 例外） |
| BroadcastExtension | `NSExtension → RPBroadcastProcessMode`、`NSExtensionPrincipalClass = $(PRODUCT_MODULE_NAME).CWSampleHandler`、`NSExtensionPointIdentifier = com.apple.broadcast-services-upload` |
| CatPawRunner | 沿用 WDA（无需额外权限；不要加 `com.apple.developer.*` 私有 entitlement） |

---

## 10. 构建、安装、拉起

### 10.1 Mac 上一次性动作

```bash
xcodebuild build-for-testing \
  -workspace CatPaws.xcworkspace -scheme CatPawRunner \
  -destination 'id=<UDID>' \
  -derivedDataPath build
```

会产出：
* `build/Build/Products/Debug-iphoneos/CatPaw.app`（用 Xcode 装或 `devicectl`）
* `build/Build/Products/Debug-iphoneos/CatPawRunner-Runner.app`
* `build/Build/Products/CatPawRunner_iphoneos17.x.x-arm64.xctestrun`

### 10.2 Windows 日常（不需要 Mac）

```bat
ios list
ios runwda --bundleid com.<team>.catpawrunner ^
           --testrunnerbundleid com.<team>.catpawrunner.xctrunner ^
           --xctestconfig CatPawRunnerTests.xctest
ios forward 8100 8100
```

iOS 17 需要先建隧道（`go-ios` 会自动处理 RSD；也可用 `pymobiledevice3`）。命令以 `go-ios` 当前版本为准，只要满足两点即可：**runner 被拉起** + **PC 能访问 8100**。

### 10.3 设备要求

* 开发者模式开启
* **关闭锁屏密码 / 自动锁屏**（锁屏后 XCTest 动作全部失败）
* 与 PC 同一局域网（屏幕推流走 LAN，不穿隧道）

---

## 11. 验收清单

交付按里程碑自测，每项给出实测结果（截图/日志）。

### M1 基础动作（必须先通）

- [ ] `GET /cw/v1/ping` 200，`session:true`
- [ ] `GET /cw/v1/device` 的 `pixel/point/scale` 与系统真实值一致（用 Xcode 打印 `UIScreen.main.nativeBounds/bounds` 对照）
- [ ] `tap` 命中桌面图标（截图前后对比）
- [ ] `swipe` 上下左右四个方向各一次，翻页成功
- [ ] `long_press` 触发图标抖动/删除菜单
- [ ] `pinch scale=2.0` 地图放大一档（视觉确认）
- [ ] 连续 3 个 `tap`，设备端打点间隔 90ms ±20ms
- [ ] 越界坐标返回 `E_OUT_OF_RANGE` 且**不执行任何一步**

### M2 输入与应用

- [ ] `type_text` 在备忘录输入 `hello123`
- [ ] `paste_text` 输入中文"你好，喵呜"
- [ ] `press_key home` 回到桌面；`volume_up` 音量条出现
- [ ] `launch_app com.tencent.xin` 启动微信；`terminate_app` 杀掉
- [ ] `wait 1000` 期间 `POST /stop` 能在 50ms 内中止（返回 `E_CANCELLED`）

### M3 观察通道

- [ ] `/screenshot` 返回原分辨率 PNG，`X-CW-Size` 与 `/device` 的 `pixel` 一致
- [ ] `/screenshot?max_edge=1280` 长边为 1280
- [ ] `/ocr` 在微信首页识别出 ≥5 行中文，`box` 画到截图上位置准确（误差 ≤ 4px）
- [ ] OCR 结果与截图同一坐标系（把 box 画上去肉眼验证）

### M4 推流

- [ ] 控制中心开启录屏后，PC 中继收到关键帧，10fps 稳定 ±2
- [ ] 720p/1.5Mbps 下手机 CPU 增幅 ≤ 15%，发热可接受
- [ ] 无观看端时编码器完全停止（CPU 回落）
- [ ] `.cam` 页面在 WKWebView 内能拿到相机与麦克风（失败则记录证据，转原生方案）
- [ ] 后台播放 TTS 正常；"退出 CatPaw"后相机流与音频不中断

---

## 12. 已知风险（实现时留意）

| 风险 | 说明 | 兜底 |
|---|---|---|
| WKWebView getUserMedia | iOS 17 一般可用，但 WebCodecs 编码参数受 Safari 版本限制 | 转原生 AVFoundation 复刻 `.cam` 协议（帧格式见 7.2，与现有 `.cam` 相同即可） |
| 中文输入 | HID 键盘事件对中文输入法不可靠 | `paste_text` 兜底；拼音键入由 PC 侧拼装（见 `CW_PLAN.md` 打字场景） |
| ReplayKit 手动开录屏 | 每次推流前要去控制中心开 | 强制要求；未开时 App 提示并可一键跳转 |
| 免费证书 7 天 | 到期需重装 | 建议付费账号；PC 侧检测到 `E_UNAUTHORIZED`/连不上时提示 |
| 锁屏 | 锁屏后所有动作失败 | PC 侧检测 `E_DEVICE_LOCKED` 后暂停链路并提示 |
| 单 target 幻想 | 想"一个 App 同时有 UI 和注入能力" | 已定双 target，不要尝试合并（XCTest 机制决定） |
