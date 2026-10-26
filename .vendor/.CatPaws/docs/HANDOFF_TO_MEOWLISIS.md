# 交接：CatPaws 设备侧 → Meowlisis 主项目（QQ 发消息闭环）

> 给 Meowlisis 工作区的 AI。设备侧（CatPaws Runner 1.0.7 + CatCam 1.0.4）已经验收完，
> 这份文档只讲：**现状、契约、你要做什么、坑、验收标准**。目标是把“QQ 发消息”跑成
> 真·agent 闭环（看→操作→看→操作），并把这条链路固化成可复用的功能（func）。

---

## 1. 设备侧现状（已装、已实测）

| 项 | 值 |
|---|---|
| Runner | CatPaws **1.0.7**，`com.facebook.WebDriverAgentRunner.xctrunner.D79NHBM8JL`，桌面名 `CatPaws 1.0.7` |
| 手机 App | CatCam **1.0.4**，`com.meowlisis.catcam.D79NHBM8JL` |
| 设备 | iPhone13,4 / iOS 18.3.2 |
| 屏幕 | pixel **1284×2778**，point **428×926**，scale **3**，safe_area **47/34** |
| 入口 | `catpaws-launcher`（`start.cmd` / `status.cmd` / `stop.cmd`），转发 `127.0.0.1:8100` |
| 能力 | tap, long_press, swipe, drag, pinch, type_text, paste_text, press_key, launch_app, activate_app, terminate_app, screenshot, ocr |

1.0.7 实测时延（真机，单步）：

| 动作 | 实测 |
|---|---|
| swipe 500ms | 851 ms |
| drag 600ms + hold 300ms | 1244 ms |
| tap | 338 ms |
| long_press 700ms | 945 ms |
| pinch scale=2 | 849 ms |
| press_key home | 481 ms |
| 10×300ms 连滑 | 7186 ms（**上限 8s，PC 侧一次别超过 10 步**） |
| /screenshot 原图 | ~0.6–1 s（3 MB，记得 `max_edge`） |
| /ocr | ~1–2 s |

错误码：`E_OUT_OF_RANGE`、`E_CANCELLED`、`E_DEVICE_LOCKED`、`E_NO_SESSION`、`E_BAD_STEP`、
`E_UNSUPPORTED`、`E_INTERNAL`、`E_BUSY`。越界点按直接拒，不会静默偏移。

---

## 2. 契约（PC 的 `src/cw/device_client.py` 已对齐）

- 基地址：`http://127.0.0.1:8100/cw/v1`
- 信封：`{ "protocol": "cw/1", "ok": bool, "code": "...", "message": "", "elapsed_ms": n, "data": {...} }`
- 端点：
  - `GET /ping` → `{app, version, session, build}`
  - `GET /device` → `screen.pixel/point/scale/safe_area`、`device`、`warnings[]`
  - `GET /capabilities` → 动作名数组
  - `GET /screenshot?max_edge=&region=x,y,w,h&format=png|jpeg&quality=` → 图片字节；`X-CW-Size` 头是原图像素
  - `POST /ocr {region}` → `texts:[{text, box:[x,y,w,h], confidence}]`（像素坐标）
  - `POST /actions {steps:[...], delay_ms, wait_idle}` → `{results:[{action, ok, code, elapsed_ms}]}`
  - `POST /stop` → 急停当前序列（`E_CANCELLED`，不杀 App）
- 坐标：**截图像素**，左上原点；`point = pixel / scale`。
- 无 token（PC 端也没有）。

---

## 3. 你需要先配的（我这边不能动 `.vendor`）

1. `config.yml → catpaws`：
   - `device_ip: 127.0.0.1`、`device_port: 8100`
   - **`llm.api_key`（必填，deepseek-chat）**；看图模式再填 `vision_api_key`（qwen-vl）
   - `allow_ocr: true`
   - `runner_bundle_id` / `catcam_bundle_id` 用带 `.D79NHBM8JL` 的现值
   - `app_denylist` 保留默认（Preferences 等）；QQ 不在里面
2. 手机：QQ 9.3.75 **已登录**；目标联系人用 **“我的电脑”**（发给自己，零风险）；解锁、插 USB、别锁屏
3. 启动：`catpaws-launcher\start.cmd` → `status.cmd` 看到 `/cw/v1/ping -> 200`
4. `start.bat` 起主项目服务 → Web 控制台 → 开始链路（session）

---

## 4. QQ 发消息：走 agent 闭环，**不要写成 action**

主链路是 `cw/agent.py` 的 LLM 循环，工具：
`cw_observe(mode=ocr|image, region, max_edge)`、`cw_single`、`cw_sequence`、`cw_action`、`cw_ask_user`。

直接给 agent 的目标文本（可复制）：

```
打开 QQ，在顶部搜索框里搜索“我的电脑”，进入会话，发送一条消息：
“CatPaws 测试 <当前时间>”。
发送前先看一眼屏幕确认在正确的会话里；发送后截图确认消息气泡出现，然后回桌面并告诉我结果。
```

期望的工具序列（给模型参考，不强制）：

1. `cw_observe{ocr}` → 找“搜索 / Search”
2. `cw_single{launch_app, bundle_id: "com.tencent.mqq"}` + `wait 2500`
3. `cw_observe{ocr}` → `cw_single{tap}` 搜索框
4. `cw_single{paste_text, text: "我的电脑"}`（**中文只能 paste_text**）
5. `cw_observe{ocr}` → 点搜索结果第一行
6. `cw_observe{ocr}` → 点输入框（“发送消息 / Aa / 输入”）
7. `cw_single{paste_text, text: "CatPaws 测试 ..."}`
8. `cw_observe{ocr}` → 点“发送”，找不到就 `press_key{return}`
9. `cw_observe{ocr}` 确认气泡 → `press_key{home}`

节奏：**每步之后 `wait 200–300ms` 再 observe**（界面动画/键盘弹出）。坐标用 OCR 的
`box` 中心（`x+w/2, y+h/2`），不要用写死的点。

---

## 5. 把“功能”固化（func）

QQ 发消息不要只做一次 demo，建议固化成主项目里的一层：

- **模板**：把上面的目标文本参数化成 `{contact}`、`{message}`，作为一条 task/prompt 模板；
- **工具层**：优先用 `cw_single/cw_sequence` 组合，不新增设备接口；
- **回归用例**：`contact=我的电脑`、`message=CatPaws 回归 <ts>`，每次跑完截图存档；
- **可选确定性兜底**：`Docs/templates/qq_send/` 是 action 版（不依赖 LLM），只用于排障，不是验收主路径；
- **失败兜底**：OCR 找不到“搜索”→ 先 `press_key home` 再 launch；找不到输入框→ `ask_user`。

---

## 6. 已知坑（照抄，能省几小时）

| # | 坑 | 处理 |
|---|---|---|
| 1 | 两个客户端同时操作设备 | 动作互相打断、**输入打到别的 App**（真发生过：文字进了微信输入框） | 我这边跑验收脚本时，你别同时跑 agent；反之亦然 |
| 2 | 盲点坐标 | Safari 点出分享菜单、美团点进店铺页 | 先 `observe ocr` 拿 box 再点 |
| 3 | `type_text` 打中文 | 只支持 ASCII | 中文一律 `paste_text`，且先确认焦点（键盘弹出） |
| 4 | 动作后立刻 observe | 界面还在动画，OCR 拿到旧画面 | 等 150–300ms |
| 5 | 截图太大 | 原图 3 MB，token 爆 | `max_edge=640/720` |
| 6 | 10 步连滑超时 | 1.0.7 下 10×300ms≈7.2s，8s 上限 | 一次 ≤10 步，多了拆两批 |
| 7 | 锁屏 | 直接 `E_DEVICE_LOCKED` | 跑之前 `press_key home` + 看一眼截图 |
| 8 | `wait_idle: true` | 会等 App 静止，慢很多 | 只在最后一步用 |
| 9 | 敏感词确认 | guard 会对“支付/密码/转账”等弹确认 | 别让 agent 进支付页；确认弹窗要有人应答 |
| 10 | QQ 首次弹权限/青少年模式 | 会挡住 OCR | 先手动点掉，再跑 |

---

## 7. 验收标准（做到这些才算 func 完成）

- [ ] 会话里出现消息气泡（截图存证）
- [ ] agent transcript 完整：observe→act 至少 3 轮，无 `E_*` 未处理错误
- [ ] 单步 <1.5s、10 步 <8s
- [ ] 重复跑 3 次成功率 ≥2/3（偶发坐标漂移可接受，但不能卡死）
- [ ] 失败可恢复：OCR 找不到元素时能回桌面重来，不把手机留在半截页面
- [ ] 结果回报：截图 + transcript + 耗时

---

## 8. 我这边能提供的

- 设备日志：`catpaws-launcher\run\wda.log`（每一步的快照/事件都有）
- 复测脚本：`temp\scripts\final107.ps1`、`apps106b.ps1`
- 文档：`Docs/TESTING.md`（脚本兼容 + 坑）、`Docs/PC_INTEGRATION.md`（端点/动作/配方）
- 包：`temp\out\catpaws-1.0.7.ipa`（sha `320ac0ec…`）、`temp\out\catcam-1.0.4.ipa`

---

## 9. 交接 checklist

- [ ] `config.yml` 填了 LLM key，`allow_ocr: true`
- [ ] `catpaws-launcher\status.cmd` → ping 200
- [ ] `start.bat` 服务起来，Web 能打开
- [ ] QQ 已登录、目标“我的电脑”、手机解锁
- [ ] agent 目标文本已发，链路在跑
- [ ] 按 §7 验收，图片/日志回传
