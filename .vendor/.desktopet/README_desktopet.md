# 喵呜桌宠 (desktopet)

一个兼容 **VTube Studio Public API** 的 Live2D 桌宠。无背景透明窗口、鼠标穿透（不影响游戏/正常操作）、独显渲染、可缩放、可拖动、支持鼠标跟随。任何 VTS 客户端（如 Meowlisis）都能直接对接控制它。

## 特性

- 🪟 **透明无边框置顶窗口**：只显示人物，背景透明
- 🖱 **鼠标穿透**：鼠标移到人物上，事件全部透传给下层窗口（游戏/正常操作完全无感）
- 👀 **鼠标跟随**：鼠标移到桌宠附近时，人物头部/眼睛平滑跟随（只读鼠标坐标，不拦截事件）
- 🎮 **独立显卡渲染**：`force_high_performance_gpu`，核显卡顿问题不再
- 📏 **缩放 / 拖动**：托盘菜单 + 控制面板实时调整，支持拖动模式直接用鼠标拖人物
- 🔀 **模型切换**：托盘 / 控制面板选择 `Live2d_resource/` 下任意 Live2D 模型
- 🔌 **VTS API 兼容**：`ws://127.0.0.1:8001`，无认证，复用模型自带 `vtube.json` 的参数映射与表情热键

## 快速开始

```bat
:: 首次运行：自动安装依赖 + 下载 Electron 运行时并启动
setup.bat

:: 之后启动
start.bat   （或 setup.bat，会自动检测依赖直接启动）
```

**控制面板**：双击任务栏托盘图标打开，可实时调整缩放、位置、模型、方向修正。

## 配置（config.json）

| 字段 | 说明 |
|------|------|
| `api.host` / `api.port` | VTS API 监听地址，默认 `127.0.0.1:8001` |
| `model.dir` | 模型目录（`Live2d_resource/` 下的子目录） |
| `window.padding` | 窗口边距（默认 1.15，防物理摆动内容被裁剪） |
| `paramFix.swapAngleXY` | 方向修正：交换左右↔上下 |
| `paramFix.flipAngleX` / `flipAngleY` | 方向修正：左右/上下反向 |

方向修正也可在控制面板实时勾选，作用于 VTS 注入参数与鼠标跟随。

## VTS API 接口

### 连接

- 地址：`ws://127.0.0.1:8001`
- 协议：`VTubeStudioPublicAPI` `1.0`
- **认证**：无。`AuthenticationRequest` 无论传什么 token 都返回 `authenticated: true`

### 支持的消息类型

| messageType | 说明 |
|-------------|------|
| `APIStateRequest` | 返回 API 状态（active / 版本） |
| `AuthenticationRequest` | 无认证，直接返回 authenticated: true |
| `StatisticsRequest` | 返回运行统计 |
| `CurrentModelRequest` | 返回当前模型信息与 `modelPosition`（含 size） |
| `AvailableModelsRequest` | 返回模型列表（固定单模型） |
| `ModelLoadRequest` | 返回当前 modelID（桌宠固定单模型，不实际切换） |
| `MoveModelRequest` | **缩放/移动**：`data.size`（-100~+100）映射到渲染缩放 |
| `HotkeyTriggerRequest` | 触发表情：`data.hotkeyID` 支持热键 ID 或表情名 |
| `HotkeysInCurrentModelRequest` | 返回当前模型的表情热键列表 |
| `InjectParameterDataRequest` | **参数注入**：`data.parameterValues[{id,value,weight}]`，按 `vtube.json` 映射到 Live2D 参数 |
| `Live2DParameterListRequest` | 返回 Live2D 参数列表（来自 `cdi3.json`） |
| `InputParameterListRequest` | 返回 VTS 输入/追踪参数列表 |
| `ExpressionStateRequest` | 返回表情状态 |
| `ExpressionActivationRequest` | 按 `expressionFile` 激活/停用表情 |
| `EventSubscriptionRequest` | 接受订阅（当前不主动推送事件流） |

### 缩放（MoveModelRequest）

```
data.size: -100 ~ +100
映射：渲染缩放 = 2^(size/100)，即 size=0 为默认 1x，+100 为 2x，-100 为 0.5x
```

### 参数注入（InjectParameterDataRequest）

按模型自带 `vtube.json` 的 `ParameterSettings` 做 VTS 输入参数 → Live2D 参数映射（含范围映射），并补充别名：

| VTS 输入参数 | Live2D 参数 |
|--------------|-------------|
| `FaceAngleX` | `ParamAngleX` + `ParamBodyAngleX` |
| `FaceAngleY` | `ParamAngleY` + `ParamBodyAngleY` |
| `FaceAngleZ` | `ParamAngleZ` + `ParamBodyAngleZ` |
| `VoiceVolumePlusMouthOpen` | `ParamMouthOpenY`（嘴部开合） |
| `MouthOpen`（别名） | `ParamMouthOpenY` |
| `EyeOpenLeft/Right` | `ParamEyeLOpen/ParamEyeROpen` |
| `EyeRightX/Y` | `ParamEyeBallX/Y` |
| `Brows` | `ParamBrow*` |
| `VoiceFrequencyPlusMouthSmile` | `ParamMouthForm` |

注入的 `FaceAngleX/Y` 方向可用 `paramFix` 修正。

### 表情热键

模型自带 8 个表情（对应 `HotkeysInCurrentModelRequest` 返回列表），`HotkeyTriggerRequest` 的 `hotkeyID` 可用热键 ID（32 位 hex）或表情名：

`angry` `confused` `embarrassed` `shy` `singing` `stareyes` `sweating` `wordless`

## 目录结构

```
desktopet/
├── setup.bat            # 一键安装 + 启动（首选用）
├── start.bat            # 纯启动
├── config.json          # 配置
├── main.js              # Electron 主进程（透明穿透窗口 + 托盘 + 鼠标跟随 + IPC）
├── preload.js           # 桌宠渲染进程 IPC 桥
├── control/             # 控制面板（双击托盘打开）
├── vts/
│   ├── model.js         # 解析 vtube.json/cdi3.json，参数映射
│   └── server.js        # VTS WebSocket 服务端（无认证）
├── renderer/            # Live2D 渲染（pixi-live2d-display）
├── libs/                # pixi.js + Live2D Cubism Core + pixi-live2d-display
└── Live2d_resource/     # Live2D 模型目录
```

## 依赖

- `ws`：VTS WebSocket 服务端
- `electron`：桌面运行时

Live2D 渲染库已放在 `libs/`，无需额外安装。
