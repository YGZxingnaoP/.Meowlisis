# 🐾 CatPaws

让主项目"用眼睛看手机屏幕、用手操作手机"的 iPhone 控制服务。

PC 侧是一个 Python 服务（内置轻量 agent：观察 → 决策 → 操作 → 复盘），手机侧是改自 WDA 的双 target App。
协议、坐标、推流、验收标准见 [docs/CW_IOS_SPEC.md](docs/CW_IOS_SPEC.md)，整体方案见 [docs/CW_PLAN.md](docs/CW_PLAN.md)。

## 形态

```
iPhone
├── CatPawRunner   :8100  /cw/v1/*   触摸/截图/OCR/元素树（改自 WebDriverAgent）
└── CatPaw app                       界面 + 相机 + 音频 + ReplayKit 屏幕推流

Windows
├── go-ios tunnel/forward            127.0.0.1:8100 → 手机（iOS 17 必需）
├── CatPaws 服务   :18110            控制台 + 控制 API + agent + action + 操作日志
└── CatPaws 中继   :18111            WS 视频中继（.cam 同款二进制帧格式）
```

AI 的观察通道只有截图与 OCR，视频流只给人看，永远不进模型。

## 目录

```
CatPaws/
├── src/cw/                 PC 服务：协议/驱动/操作/agent/action/中继/前端服务
├── src/cw_script.py        注入给 action 脚本的 cw_script 模块
├── actions/<action_id>/    每个 action 一个文件夹（manifest.json + *.py）
│   └── jump_jump/          跳一跳示例（用户脚本，unverified）
├── web/                    控制台：左边手机画面，右边操作过程
├── docs/                   CW_PLAN.md（方案）/ CW_IOS_SPEC.md（iOS 规范）
├── start.bat               启动（运行环境与主项目共用 runtime/311）
├── env/models/             OCR 模型（OCR 已改到手机端 Vision，可留可删）
└── src/server/ src/screen/ 旧版 WDA 直连实现（legacy，入口已换）
```

## 运行（PC）

```bash
# Windows 双击 start.bat，或：
runtime\311\python.exe .vendor\.CatPaws\src\cw\server.py

# 没有手机时用 mock 设备跑通全链路：
runtime\311\python.exe .vendor\.CatPaws\src\cw\server.py --mock
```

控制台：<http://127.0.0.1:18110>

* 运行环境与主项目共用 `<项目根>/runtime/311/python.exe`，不需要再装 paddle。
* 配置读主项目 `config.yml` 的 `catpaws:` 段（已预置），LLM 的 `api_key` 填在那里。
* 设备不可达时服务会自动降级到 mock，并在控制台打印提示。

## 运行（iOS）

按 [docs/CW_IOS_SPEC.md](docs/CW_IOS_SPEC.md) 在 Mac 上建 workspace 并实现两侧 target；Windows 日常用：

```bat
ios list
ios runwda --bundleid com.meowlisis.catpawrunner ^
           --testrunnerbundleid com.meowlisis.catpawrunner.xctrunner ^
           --xctestconfig CatPawRunnerTests.xctest
ios forward 8100 8100
```

## 三类操作

| 类 | 工具 | 说明 |
|---|---|---|
| 观察 | `cw_observe` | `mode=ocr` 返回文本 + 像素框；`mode=image` 返回截图给多模态模型 |
| 单次 | `cw_single` | 点、长按、滑动、捏合、输入、按键、启动应用、等待 |
| 连续 | `cw_sequence` | 一次下发多步，设备端按 `delay_ms`（默认且最小 90ms）串行执行 |
| action | `cw_action` | 起子进程跑 `actions/<id>/` 脚本，脚本只能通过 `cw_script` 与执行器通信 |

agent 分三个阶段：

| 阶段 | 可见工具 | 约束 |
|---|---|---|
| `running` | observe / single / sequence / action / ask_user / update_action | **禁止新建 action**；只允许对 unverified 或可更新的 action 做小规模修正 |
| `reflecting` | observe / write_action / update_action / ask_user | 操作结束后的复盘：把固定流程沉淀成 action |

阶段由代码强制（工具表按阶段生成 + 执行时二次校验），不靠提示词。

## action 约定

`actions/<id>/manifest.json`：

```json
{
  "id": "wechat_pay",
  "title": "微信付款",
  "scene": "在微信收付款页完成一笔小额付款",
  "status": "unverified",
  "updatable": false,
  "author": "ai",
  "version": 1,
  "entry": "main.py:run",
  "params": {"max_amount": 50},
  "steps": ["进入聊天", "点 + 选转账", "输入金额", "确认"],
  "last_run": {"ok": false, "at": "", "elapsed_ms": 0}
}
```

| 规则 | 行为 |
|---|---|
| 新建 | 只能在 `reflecting`，新建即 `unverified`，不自动试跑 |
| 跑通一次 | 自动置 `verified` |
| `unverified` / `updatable` | AI 可小规模修改（≤60 行、只改已存在文件），改后回到 `unverified` |
| `verified` 且不可更新 | 失败直接上报，**不许改、不许复制副本** |
| 静态审查 | `ast` 通过、只允许白名单 import、禁止 `eval/exec/open/os/subprocess/socket` 等 |

脚本 API：`emit/tap/long_press/swipe/wait/observe/observe_texts/observe_image/ask/params/log/done/should_stop`。
脚本没有网络与 token，所有动作都经 PC 侧保护措施。

## 端口

| 端口 | 用途 |
|---|---|
| 18110 | 控制台 + 控制 API（仅 127.0.0.1） |
| 18111 | 视频中继 WS（0.0.0.0 + token） |
| 8100 | 手机 CatPawRunner（经 go-ios 转发） |
| 8443 | `.cam` 手机页（已有服务，手机 App 内 WKWebView 载入） |

## 保护措施

坐标越界整批拒绝、动作间隔 ≥90ms、连续操作 ≤20 步、单链路 ≤200 步、单链路 ≤15 分钟、应用黑白名单、敏感词二次确认、三处停止入口（PC 控制台 / 手机 App / 语音停止词）、全程操作日志 `logs/catpaws_ops/`。

## 与主项目对接

`func/catpaws/`：`config / client / if_start / state / stop / voice / core`。
进链路判定用前缀 + 关键词，停止词命中即中止；语音通道只留接口（`voice.py`），等主项目 `msg` + `sensevoice` 接。

## 环境

* 运行环境与主项目共用 `runtime/311`（requests / Pillow / websockets / openai 已就绪）。
* OCR 在手机端用 iOS Vision，不再依赖本机 PaddleOCR。
* 旧版 `src/server/`、`src/screen/`、`actions/jump_jump_tf_cv.py` 等是上一代 WDA 直连实现，保留仅供对照，不再是最新入口。
