# 验收脚本 & PC 对接说明（README）

> 对象：`temp\scripts\*.ps1`（本地验收脚本）、`catpaws-launcher\`、PC 端 CatPaws 服务。
> 结论：**脚本与 PC 端完全兼容**——它们和 PC 的 `src/cw/device_client.py` 打的是同一套 `/cw/v1/*`，
> 只是绕过了 PC 服务（8080）和中继（8081）直连设备。**不要和 PC 端同时跑**，动作会互相打断、抢焦点。

---

## 1. 脚本清单

| 文件 | 作用 |
|---|---|
| `temp\scripts\tour106.ps1` | 设备元数据 + 动作时延（swipe/drag/10 步/tap/long_press/pinch）+ Safari 打字 + 越界 + `/stop` + CatCam UI 截图 |
| `temp\scripts\apps106b.ps1` | 生活类 App 实测：支付宝 / 美团 / 微信 / Safari / CatCam（启动→OCR→上滑→点一个 OCR 框→截图对比） |
| `temp\scripts\*.ps1` 里 copy 的 `Act/Shot/OCRBox` | 三个通用函数，PC 侧写 smoke test 可以直接照搬 |

运行前提（缺一不可）：

```bat
:: 1) 设备插 USB、解锁、launcher 在跑
D:\Virtual Machines\catpaws-launcher\start.cmd
D:\Virtual Machines\catpaws-launcher\status.cmd     :: 看到 ping -> 200

:: 2) 单脚本运行（不要两个一起跑）
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\Virtual Machines\temp\scripts\tour106.ps1"
```

输出在 `temp\out\<run>\`：`*.png` 截图 + `results.json`（每个动作的 `ok/code/elapsed/wall`）。

---

## 2. 与 PC 端的兼容关系

| 项 | 验收脚本 | PC 端（`src/cw`） |
|---|---|---|
| 基地址 | `http://127.0.0.1:8100/cw/v1` | 同（`device_ip/device_port`，launcher 的 forward） |
| envelope | 直接读 `ok/code/message/data` | `device_client.py` 相同 |
| 动作 | `tap/long_press/swipe/drag/pinch/press_key/launch_app/terminate_app/wait/type_text/paste_text` | 同一套（`protocol.py` 的 SPECS） |
| 坐标 | 截图像素 | 同 |
| token | 不传 | 不启用 |
| 观察 | `/screenshot`、`/ocr` | `observe()` 同一接口 |

差异只有两点：

1. 脚本不过 PC 的 `guard/session/ops` 层——**没有敏感词确认、没有速率限制、没写操作日志**；
   正式跑请走 PC 端，脚本只用于验收/排障。
2. 脚本用固定坐标点按（OCR 定位辅助），PC 端用 OCR/agent 决策；因此脚本里写死的坐标只对 iPhone 12 Pro Max（1284×2778）有效。

---

## 3. 踩过的坑（照这个避）

| # | 坑 | 处理 |
|---|---|---|
| 1 | 两个脚本同时跑 | 动作互相打断、**输入打到别的 App**（真把文字打进过微信输入框，未发送） | 一次只跑一个；跑前 `press_key home` 复位 |
| 2 | 盲点坐标 | 点错按钮（Safari 点出分享菜单、美团点进店铺页） | 先 `/screenshot`+`/ocr` 拿 box，再点 box 中心；点完截图对比确认 |
| 3 | `type_text` 打中文 | 只支持 ASCII | 中文用 `paste_text`，且先确认焦点（点输入框后截图确认键盘/光标） |
| 4 | 动作后立刻截图 | 1.0.7 后 swipe≈0.8s，但界面可能还在动画 | 动作后等 150–300ms 再观察，或最后一步 `wait_idle:true` |
| 5 | 截图太大 | 原图 3 MB | 一律用 `?max_edge=640/720` |
| 6 | `.ps1` 中文乱码/语法错 | Windows PowerShell 5.1 读无 BOM 的 UTF-8 会按 ANSI 解析 | 脚本存成 **UTF-8 with BOM**；变量名避开 `$home/$input/$args/$error` |
| 7 | `Tee-Object` 报路径不存在 | 输出目录还没建 | 先 `New-Item -ItemType Directory` 再跑 |
| 8 | 大文件拉取慢 | VM→主机下行会掉到 2–5 KB/s | `pull-ipa.cmd -ChunkMiB 1 -Parallel 8`（实测 8.8 MB / 59 s） |
| 9 | 个人 App | 微信/支付宝/美团里有隐私与付费入口 | 只做启动/滚动/点非支付区域；测完 `terminate_app`；截图不外传 |
| 10 | `/stop` 的语义 | 只打断动作序列 | 不杀 App/Runner；PC 收到 `E_CANCELLED` 静默丢弃剩余步骤 |

---

## 4. PC 端写 tool 的入口

- 端点/动作/错误码/组合配方：见 [`PC_INTEGRATION.md`](PC_INTEGRATION.md)。
- 生活类 App 的“脚本化动作”模板：见 [`templates/qq_send/`](templates/qq_send/)（QQ 发消息）。
- PC 的 action 脚本 API（`cw_script`）：`tap/long_press/swipe/wait/observe/observe_texts/observe_image/emit/ask/log/done/should_stop`，
  `emit({"action": "launch_app", "bundle_id": "com.tencent.mqq"})` 这类“没封装的动作”也能直接发。

---

## 5. 当前版本行为（1.0.7）

| 动作 | 时延（真机 iPhone 12 Pro Max / iOS 18.3.2） |
|---|---|
| swipe 500ms | ~0.8 s |
| drag 600ms + hold 300ms | ~1.1 s |
| tap / long_press | ~0.2–0.3 s / ~0.8 s（1.0.7 起走直连事件） |
| 10×300ms 连续滑动 | ~7.1 s（接近 8 s 上限，PC 侧别再加步数） |
| pinch | 1.0.7 起走双指直连事件（目标 <1.5 s，待本轮实测） |
| press_key home | ~0.5 s |
| `/screenshot` 原图 | ~0.6–1 s（3 MB） |
