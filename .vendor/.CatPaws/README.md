# 🐾 CatPaws

基于 WDA（WebDriverAgent）的 iOS 设备远程控制框架。电脑通过 WDA 原生 HTTP 接口直接向手机发送手势指令，无需手机端自定义代码。

## 架构

```
┌─────────────────────────────────────┐
│           电脑端 (Python)             │
│                                      │
│  ┌──────────────────────────────┐ │
│  │      wda_native_client        │ │
│  │    WDA 原生 W3C Actions API  │ │
│  └─────────────┬────────────────┘ │
│                │                     │
│       action_manager              │
│    (加载并执行动作脚本)              │
└─────────────────┬───────────────────┘
                  │ HTTP
                  ▼
         ┌──────────────────┐
         │  手机 (WDA)       │
         │  HTTP Server      │
         │  (端口 8100)       │
         └──────────────────┘
```

手机端只需运行标准 WDA 服务，无需任何自定义代码。

## 项目结构

```
CatPaws/
├── src/
│   ├── server.py                # 启动入口
│   ├── server/
│   │   ├── config.py            # 端口与 IP 配置
│   │   ├── wda_native_client.py # WDA 原生客户端（W3C Actions API）
│   │   ├── http_server.py       # HTTP 服务（控制面板 / API）
│   │   ├── action_manager.py    # 动作脚本加载与执行
│   │   ├── protocol.py          # 消息协议定义
│   │   └── static/index.html    # 控制面板前端
│   └── screen/
│       ├── screen_receiver.py   # 截图接收与缓存
│       ├── coordinate_system.py # 坐标系管理（像素↔逻辑点转换）
│       ├── coordinate_grid.py   # 屏幕坐标布点页面
│       └── ocr.py               # PaddleOCR 文字识别
├── actions/                     # 可执行动作脚本（放入 .py 即可）
│   ├── example.py               # 示例：点击、滑动、长按
│   ├── jump_jump.py             # 微信跳一跳自动化（纯 CV 算法）
│   └── jump_jump_tf.py          # 跳一跳 TensorFlow 版本（需独立 Python 环境）
├── env/models/                  # OCR 模型（运行环境与主项目共用 runtime/311）
├── requirements.txt
├── start.bat                    # Windows 一键启动
└── check_env.py                 # 环境检测脚本
```

## 文档

| 文档 | 内容 |
|---|---|
| [docs/CW_PLAN.md](docs/CW_PLAN.md) | 当前方案：三类操作、agent 阶段机、action 存储与审查、保护措施、目录结构、里程碑 |
| [docs/CW_IOS_SPEC.md](docs/CW_IOS_SPEC.md) | iOS 端实现规范（交付给 Xcode/macOS agent）：双 target 工程、`/cw/v1/*` 接口契约、坐标规则、推流协议、验收清单 |

## 快速开始

### 1. 安装依赖

运行环境与主项目共用：`<项目根>/runtime/311/python.exe`（`start.bat` 已直接指向它，不再使用本目录的 `env/python`）。
`requests` / `Pillow` / `numpy` / `websockets` 主项目已带，无需另装；只有 OCR 需要补装：

```bash
runtime\311\python.exe -m pip install paddlepaddle paddleocr
```

### 2. 环境检测（可选）

```bash
# Windows 双击
start_check_env.bat

# 或命令行
python check_env.py
```

### 3. 手机端准备

1. **启动 WDA**：在 iPhone 上运行 WebDriverAgent，确保 HTTP Server 监听 `8100` 端口
2. 确保手机和电脑处于**同一局域网**

> **注意**：HTTP 模式下无需启动额外的 WebSocket 服务，直接使用 WDA 即可。

### 4. 启动电脑端

**方式一：Windows 双击启动**

```
start.bat
```

**方式二：命令行启动**

```bash
python src/server.py
```

启动后会自动打开浏览器，进入控制面板页面（`http://本机IP:8080`）。

控制台会输出以下信息：
```
🌐 控制面板       http://192.168.x.x:8080
🖥️  状态页面     http://192.168.x.x:8080/status
📱 屏幕控制台    http://192.168.x.x:8080/screen
🐾 CatPaws WDA 模式已启动
```

### 5. 连接手机

1. 输入手机的 IP 地址（如 `192.168.1.100`）和 WDA 端口（默认 `8100`）
2. 点击 **🔌 初始化连接** 按钮
3. 等待状态标签变为绿色的 **✅ WDA 已连接**
4. 连接成功后，控制台会打印 `✅ WDA 会话已创建: xxx`

> 会自动创建 session、检测 scale、注册截图 provider。
> 如果显示"WDA 不可达"，请检查手机 IP、端口是否正确，以及防火墙是否放行。

### 5.5 配置 TensorFlow 环境（可选）

如果需要运行 `jump_jump_tf`（基于 TensorFlow Object Detection API），需要额外配置：

1. **准备 Python 3.7 环境**
   ```bash
   # 安装 Python 3.7 到 D:\.CatPaws\env_tf_full
   # 验证: D:\.CatPaws\env_tf_full\python.exe -c "import tensorflow; print(tensorflow.__version__)"
   ```

2. **编辑配置文件** `src/server/env_config.py`
   ```python
   PYTHON_ENVS = {
       "jump_jump_tf": r"D:\.CatPaws\env_tf_full\python.exe",
   }
   ```

3. **准备模型文件**（放在 `actions/` 目录）
   - `frozen_inference_graph.pb` - 训练好的检测模型
   - `wechat_jump_label_map.pbtxt` - 标签映射文件

详细步骤请参考 [TF_SETUP.md](TF_SETUP.md)

### 6. 运行脚本

1. 在 **🎮 动作脚本** 区域，从下拉列表选择一个脚本（如 `example`）
2. 点击 **▶ 开始运行** 按钮
3. 脚本会通过 WDA W3C Actions API 发送动作指令到手机

> **注意**：HTTP 模式下不支持中途停止脚本，脚本将在所有动作执行完成后自然结束。

### 7. 查看手机屏幕

访问 `http://本机IP:8080/screen` 可查看通过 WDA `/screenshot` 接口获取的最新截图，并支持点击获取坐标。

### 8. 启动应用

可通过 WDA 接口启动手机上的应用：

```python
client = get_wda_client()
client.launch_app("com.apple.calculator")  # 启动计算器
```

### 9. 退出程序

按 `Ctrl+C` 退出整个程序。

## 编写动作脚本

在 `actions/` 目录下新建 `.py` 文件，即可被控制面板识别。支持两种入口函数：

### 方式一：`main(send=...)` 回调风格（推荐）

```python
import asyncio
import json

async def main(send=None):
    """send: 异步回调，传入 JSON 字符串发送动作到手机"""
    if send is None:
        return

    # 点击坐标 (200, 300) —— 像素坐标，后端自动转换为逻辑点
    await send(json.dumps({
        "type": "action",
        "action": "tap",
        "params": {"x": 200, "y": 300}
    }))
    await asyncio.sleep(0.5)

    # 从 (100,500) 滑动到 (300,500)
    await send(json.dumps({
        "type": "action",
        "action": "swipe",
        "params": {"from_x": 100, "from_y": 500, "to_x": 300, "to_y": 500, "duration": 0.3}
    }))
```

### 方式二：`run(send=...)` 回调风格

```python
import asyncio
import json

async def run(send=None):
    """send: 异步回调，接收 JSON 字符串"""
    if send is None:
        return
    while True:
        await send(json.dumps({
            "type": "action",
            "action": "tap",
            "params": {"x": 200, "y": 300}
        }))
        await asyncio.sleep(1.0)
```

### 支持的动作类型

| 动作 | 参数 | 说明 |
|------|------|------|
| `tap` | `x`, `y` | 单击 |
| `long_press` | `x`, `y`, `duration` | 长按（秒） |
| `swipe` | `from_x`, `from_y`, `to_x`, `to_y`, `duration` | 滑动 |
| `repeated_tap` | `x`, `y`, `times`, `interval` | 连续点击 |
| `activate_app` | `bundle_id` | 激活应用（确保在前台） |
| `launch_app` | `bundle_id` | 启动应用 |

### 使用截图和 OCR

脚本中可以通过 `screen` 模块获取截图和进行文字识别：

```python
from screen import get_screenshot, ocr_text, coord_system

async def main(send=None):
    # 获取当前截图（PIL Image）
    img = get_screenshot()
    if img is None:
        print("无法获取截图")
        return

    # OCR 识别文字
    results = ocr_text(img)
    for r in results:
        print(f"文字: {r.text}, 中心: {r.center}")

    # 坐标转换：像素 → 逻辑点
    pt_x, pt_y = coord_system.to_point(585, 1266)
    print(f"逻辑坐标: ({pt_x}, {pt_y})")
```

### 子进程脚本（特殊依赖隔离）

对于需要特定 Python 版本或依赖的脚本（如 TensorFlow 1.x），可以使用子进程模式：

1. 在 `src/server/action_manager.py` 的 `TF_SCRIPTS` 中注册脚本
2. 在 `src/server/env_config.py` 中配置对应的 Python 解释器路径
3. 脚本通过 `print(json.dumps(action))` 输出到 stdout，主进程捕获并转发

示例参考 `actions/jump_jump_tf.py`

## 坐标系标准方案

### 两套坐标系

iOS 设备存在两套坐标系，这是正确处理手势指令的关键：

| 坐标系 | 单位 | 用途 | 示例 (iPhone 14 Pro) |
|--------|------|------|---------------------|
| **物理像素** (Screenshot Pixels) | px | 截图的原始分辨率、CV/OCR 分析 | 1170 × 2532 |
| **逻辑点** (Logical Points) | pt | WDA 手势指令、iOS UIKit | 390 × 844 |

两者关系：

```
截图像素 = 逻辑点 × scale

例如 iPhone 14 Pro (scale = 3):
  截图像素 x=585 → 逻辑点 x=195  (585 ÷ 3)
  截图像素 y=1266 → 逻辑点 y=422  (1266 ÷ 3)
```

### 自动转换流程

CatPaws 内置了自动坐标转换，流程如下：

```
脚本 CV 分析 → 像素坐标 (585, 1266)
       ↓
发送动作指令 {{"action": "tap", "params": {{"x": 585, "y": 1266}}}}
       ↓
WDAExecutor 自动转换: (585, 1266) ÷ scale → (195, 422)
       ↓
WDA 执行 tap(195, 422) ✅ 正确点击目标
```

### scale 自动检测

当创建 WDA 会话时，scale 会自动检测：
1. 通过 WDA HTTP API 获取设备逻辑尺寸（如 390×844）
2. 结合截图像素尺寸（如 1170×2532）计算 scale = 1170/390 = 3.0
3. 注入全局 `coord_system` 单例，后续所有操作自动转换

### 手动设置 scale

如果不使用 WDA，可手动设置：

```python
from screen import receiver
receiver.set_scale(3.0)   # iPhone 常见值: 2.0 或 3.0
```

常见 iOS 设备 scale 值：

| 设备 | scale | 截图尺寸 | 逻辑尺寸 |
|------|-------|---------|----------|
| iPhone SE | 2x | 750×1334 | 375×667 |
| iPhone 12/13/14 | 3x | 1170×2532 | 390×844 |
| iPhone 14 Pro Max | 3x | 1290×2796 | 430×932 |
| iPhone 15/16 | 3x | 1179×2556 | 393×852 |
| iPad Pro 11" | 2x | 1668×2388 | 834×1194 |

### 坐标布点工具

访问 `http://本机IP:8080/screen` 可查看手机截图，点击任意位置会同时显示像素坐标和逻辑点坐标，并自动复制逻辑坐标（可直接用于脚本编写）。

## 控制面板 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 控制面板页面 |
| GET | `/status` | 连接状态页面 |
| GET | `/screen` | 手机屏幕坐标布点 |
| GET | `/api/status` | 连接状态 JSON（含 `connected`、`phone_ip`） |
| GET | `/api/actions` | 可用脚本列表 |
| POST | `/api/init_sender` | 初始化连接 `{"phone_ip":"x.x.x.x", "port":8100}` |
| POST | `/api/run_action` | 启动脚本 `{"name":"脚本名"}` |
| POST | `/api/stop_action` | 停止脚本（不支持） |

## 配置

编辑 `src/server/config.py`：

```python
HTTP_PORT = 8080                   # 电脑端 HTTP 端口
DEFAULT_PHONE_IP = "127.0.0.1"    # 默认手机 IP（可在控制面板中修改）
```

## 常见问题

**Q: WDA 一直不可达？**
- 确认手机和电脑在同一局域网
- 确认 WDA 已启动并监听 8100 端口（浏览器访问 `http://手机IP:8100/status` 测试）
- 检查手机 IP 是否正确（可在手机端查看）
- 检查防火墙是否放行 8100 端口

**Q: 脚本报 "无法获取截图"？**
- 确保 WDA 正常运行
- 访问 `/screen` 页面确认是否能获取截图
- 检查控制台是否有 HTTP 请求错误

**Q: jump_jump_tf 报错 "Python 解释器不存在"？**
- 检查 `src/server/env_config.py` 中的路径是否正确
- 确认 Python 3.7 环境已安装且包含 TensorFlow 1.15
- 参考 [TF_SETUP.md](TF_SETUP.md) 完整配置指南

**Q: 如何同时控制多台手机？**
- 在控制面板中切换不同的手机 IP
- 每次切换前点击"初始化连接"即可
