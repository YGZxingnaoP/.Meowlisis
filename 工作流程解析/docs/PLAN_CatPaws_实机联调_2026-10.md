# CatPaws 实机联调（主链路：触发 → 操作手机 → 完成 → 自动退出）

> 面向：Meowlisis 主项目 + `.vendor/.CatPaws`。
> 状态：代码已落地并通过静态/单元自检；真机只做了只读验证（截图、设备信息），动作链路待你实跑。

---

## 0. 现在就可以用的四条命令

```bat
:: 1) 控制台服务（当前未运行；起法，或 GUI「服务」卡片里的 CatPaws(iOS)）
runtime\311\python.exe .vendor\.CatPaws\src\cw\server.py
::    控制台 http://127.0.0.1:18110

:: 2) 状态 / 截图（只读，不动手机）
runtime\311\python.exe scripts\catpaws_chain_test.py status
runtime\311\python.exe scripts\catpaws_chain_test.py device

:: 3) 只跑 catpaws 链路（不启 TTS、不走主 LLM）
runtime\311\python.exe scripts\catpaws_chain_test.py run "操作手机：打开QQ，给我的电脑发一条消息：猫爪联调"

:: 4) 文字版角色对话（不启主程序、不启 TTS，能一直打字聊）
runtime\311\python.exe scripts\catpaws_chain_test.py chat
```

设备侧前置不变：插线、解锁、`catpaws-launcher\start.cmd`（看到 `/cw/v1/ping` 200）。

---

## 1. 端口：8080 确实和字幕服务冲突，已挪走

`func/subtitle/subtitle_server.py` 的默认 `http_port=8080`（WS 8765），是浏览器字幕服务。
CatPaws 原默认 `8080 + 8081` 与本项目既有分配直接撞车：

| 端口 | 归属 |
|---|---|
| 1800 | 主项目 Flask |
| **8080 / 8765** | **字幕服务 HTTP / WS** |
| 8090 / 8767 | flux_painter HTTP / WS |
| 9880 / 10095 | .Sovits / .SenseVoice |
| 18100 | MeowLLM（方案已定） |

所以 CatPaws 改为 **18110（控制台+API，仅 127.0.0.1）/ 18111（中继 WS，0.0.0.0）**，
落在项目既有的 18xxx 本地服务段，不碰 8080/8081/8090/8765/18100。

改到的位置：`config.yml → catpaws.port/relay_port`、`src/cw/config.py` 默认值、`.CatPaws/README.md`。
前端控制台用的是 `/cw/status` 里下发的 `relay.port`，不需要改 JS。

---

## 2. 这轮改了什么

### 2.1 `.vendor/.CatPaws/src/cw`（主要改动）

| 文件 | 改动 |
|---|---|
| `config.py` | 端口默认 18110/18111；新增 `exit_to_home`、`swipe_min_px`、`swipe_margin_px`、`swipe_speed_px_ms`、`tap_margin_px` |
| `geometry.py` | 新增 `safe_px/box/clamp/swipe`：按 `safe_area`(pt)×scale 换算成像素安全框；按 `direction+ratio` 算起止点 |
| `protocol.py` | `swipe` 支持 `direction+ratio`（与旧的 `from/to` 并存）；`duration_ms` 可省略（由 PC 推导）；短距离直接报错 |
| `ops.py` | 执行前统一 `prepare()`：swipe 归一化/夹安全区/推时长；tap/long_press/pinch 夹进安全区；`observe(image)` 回传真实图像尺寸 |
| `guard.py` | `check_rate` 改为「按批限速」：`cw_sequence` 不再因 ≥6 步被判「操作过快」 |
| `agent_tools.py` | `cw_single` 增加 `direction/ratio` 参数；image 模式明确告知「发给你的是 591×1280，坐标基准是原图 1284×2778，按图上估的要乘 2.17」 |
| `agent.py` | 提示词改写（滑动用 direction+ratio、滑完 wait 400ms、结束按 home、末行 `RESULT: OK/FAIL`）；新增收尾 `_exit_home()`；新增「模型主动收尾」标记 |
| `web.py` / `server.py` | `/cw/status` 增加 `final_ok`；服务启动把 stdout 切 UTF-8（避免 GBK 控制台崩在 emoji 上） |

关键数字（iPhone 12 Pro Max，1284×2778，scale 3，safe_area 47/34pt）：
- 安全框 = `(60, 201) ~ (1223, 2615)`（含 60px 余量），tap 再夹 8px；
- 半屏上滑 → `(641, 2011) → (641, 805)`，距离 1206px，时长按 1.2px/ms 推成 1000ms；
- 距离下限 90px（≈30pt），低于下限直接 `E_BAD_REQUEST` 并提示改用 direction+ratio。

### 2.2 `func/catpaws`（重写为真实实现）

`config / client / state / if_start / core / stop / voice`，其中：
- `core.receive()`：触发判定 + 起链路（**不消费消息**，让角色正常回一句）；
- `core.start()`：先查 `/cw/status`，`device.mock` 或 `device.error` 直接拒绝，不空跑；
- `_run()`：1.5s 轮询；`pending_question` → `voice`（TBExcuse）语音追问 → `/cw/answer`；
  超 `max_run_sec` 自动停；结束按 `RESULT: OK/FAIL` 判定 `ok`；
- 结束后 `_report()`：写短期记忆（`type=toolbox_catpaws`）+ 经 `ToolboxLLMBridge` 把结果回传给角色。

### 2.3 主链路接线

- 新增桥接 `func/pipeline/msg_catpaws.py`（`MsgCatPawsBridge.send_to_catpaws`），
  与 `msg_singer` 同级、同位置；
- 接入三个入口：`api.py` 的 `sensevoice_callback`（语音）、`/msg`、`/chat`，都在「点歌拦截」之后、「海龟汤」之前；
- `func/pipeline/system_prompt.py` 增加 `_phone_block()`：告诉角色「要你操作手机时系统会接管，别推辞」，只进主链路提示词；
- `config.yml`：`catpaws.llm` 指向 `deepseek-flash`（多模态，看图可用），端口/超时/步数/滑动参数全部落地；`config_gui.py` 里旧的 `src/server.py` 改成 `src/cw/server.py`。

主链路时序：

```
语音/文本 → api.py → 点歌拦截 → MsgCatPawsBridge（命中触发词 → 后台起链路，返回 False）
        → llm_core 正常回一句（角色：「好，我去弄」）
        → CWCatPawsCore._run 轮询 /cw/status
              ├ pending_question → TBExcuse 语音问 → /cw/answer
              └ phase=idle → final/final_ok → 判定 ok
        → 写记忆 + ToolboxLLMBridge 回传 → 角色播报结果
```

「自动退出」= agent 结束时按 home 回桌面（`exit_to_home`）+ 服务端 phase 自动回 idle + func 结束轮询/清状态；
**不杀** 18110 服务，也不强杀 QQ。

### 2.4 模型 API 配在哪里

唯一位置是 `config.yml → catpaws.llm`（控制台服务启动时读一次，**改完要重启 `src/cw/server.py`**）：

```yaml
catpaws:
  llm:
    base_url: https://api.deepseek.com/v1
    api_key: sk-...            # 没填 → agent 第一步就 llm_error
    model: deepseek-flash      # 多模态：截图/看图都走它
    vision_base_url: https://api.deepseek.com/v1
    vision_api_key: sk-...
    vision_model: deepseek-flash
    temperature: 0.2
    max_tokens: 2048
```

- 读取：`src/cw/config.py` 的 `_apply()`（`llm` 段）；使用：`src/cw/llm_client.py`；
- agent 的看图走 `llm.model`（`cw_observe(mode=image)` 不再单独切模型），`vision_*` 只是显式 `vision=True` 时的兜底；
- 自检：`GET /cw/config` 看 `llm.has_key` 与 `llm.model`；
- 主项目 `func/catpaws` **不需要** key：它只跟本地 `catpaws.host/port/token`（18110）说话；
- catpaws 目前没有 GUI 配置面板，只能改 `config.yml`；需要的话我再在「工具箱/服务」里加一张卡片。

---

## 3. 怎么触发（说人话）

命中 `start_prefixes`（前缀）或 `intent_keywords`（关键词），判定在 `func/catpaws/if_start.py`：

- 前缀：`操作手机` `用手机` `在手机上` `帮我用手机` `帮我把手机` `手机上`
- 关键词：`操作手机` `手机操作` `点外卖` `点个外卖` `用手机做` `手机上帮我` `用手机发` `手机上发` `手机发消息` `手机上发消息`
- 停止：`停止操作` `停止` `停下` `别操作了` `取消操作` `退出操作` `算了` `不玩了`

注意：光说「发个QQ消息给妈妈」**不会**走手机——那是 `napcat_send` 工具的地盘（机器人账号发）。要手机代发必须带显式前缀，例如
「**用手机发**QQ消息：给我的电脑发一句测试」。这是有意的，避免两条发送链路抢活。

推荐说法（前缀 + 目标，目标会被原样当 goal 传给手机 agent）：

> 「操作手机：打开 QQ，在顶部搜索框搜「我的电脑」，进去发一条消息：猫爪联调测试。」

链路在跑的时候：
- 说「停下 / 停止操作」→ 立刻 `/cw/stop`；
- 说别的 → 角色照常聊天，不影响手机；
- 手机 agent 需要你补充信息时会主动问你，**下一句话就是答案**（问话窗口 90s）。

触发不消费消息：命中后仍走正常对话，角色会先应你一句（「好，我去弄」），链路结束后再由角色把结果说出来。
只喊「操作手机」不带目标不会启动（当闲聊处理，角色会追问要做什么）。

---

## 4. 实测步骤（建议按顺序）

### A. 环境
1. 手机解锁、插线、`catpaws-launcher\start.cmd` → `status.cmd` 看到 ping 200；
2. 起控制台服务（第 0 节命令 1），浏览器开 `http://127.0.0.1:18110` 能看到手机画面与目标输入框；
3. `catpaws_chain_test.py status` 应显示 `mock=False`；
4. **清掉手机上的残留状态**：确认没停在聊天输入框（有草稿时回车就会发出去）；不确定就先按 home。

### B. 不启 TTS，先验链路
```bat
runtime\311\python.exe scripts\catpaws_chain_test.py run "操作手机：打开QQ，给我的电脑发一条消息：猫爪联调"
```
脚本会实时打印 `/cw/ops`（observe/tool_call/执行/错误），结束时打印 `ok/reason/final` 并截图到 `%TEMP%\catpaws_test\`。
- `--service`：服务没起时自动拉起；
- `--notify`：让结果回传给角色（默认关，避免脚本里触发 LLM/TTS）；
- `goal "..."`：绕过触发词直接下发目标；`stop` / `ops` 是辅助命令。

### C. 和角色对话（真实验收）
1. 照常起主程序（`start.bat` / GUI，1800）；需要听到角色和结果播报就把 TTS 也起起来（不起 TTS 时脚本仍可用，但角色说话听不到，只能看日志与 `final`）；
2. 对角色说：「操作手机：打开 QQ，给我的电脑发一条消息：猫爪联调测试。」
3. 预期：角色先应一句 → 手机自己动（控制台能看到每一步）→ 结束后角色把结果说出来；
4. 反复 3 次，成功 ≥2 次即可。

### C2. 不起主程序、不起 TTS 的文字对话（`chat`）

```bat
runtime\311\python.exe scripts\catpaws_chain_test.py chat
::   --meowid 000001   身份（默认 000001，主人的内部编号）
::   --ltmem           额外写长期/用户档案（默认只写短期记忆）
```

进去就是一个 REPL：`你>` 后面直接打字，角色用**同一套 system prompt + 短期记忆 + 合并工具调用**回你，回复以文字打印（不送 TTS）。

- **操作过程单独一个窗口**：启动 `chat` 会自动开一个只读日志窗（`%TEMP%\catpaws_test\chat_ops_*.log`），
  观察/工具/执行都在那边；你的窗口只留提问、角色回复和你的输入，输入行不会被日志冲掉（`--inline` 可关掉分窗，`--quiet` 连心跳都关）。
- **链路运行中可以指导**：手机在跑的时候你打的字不会被当成闲聊，而是作为**补充指令**发给手机上那个 agent，
  它下一轮会看到「主人的补充指令：…」并照做（实测可中途叫停一个子任务改路线）。想正常聊天等它结束，说「停止操作」可中止。

触发词照样生效，链路跑完会在这里打印：

```
[手机结果] ok=True  reason=done
[手机结论] ...
（下一条消息时角色会接着这条结果回复）
```

手机 agent 中途要问你东西时，**由角色转述**（和主链路 TTS 模式一致：手机只会说机器话，话由角色来说）：

```
喵利呜西斯> 主人，这条消息发给谁呀？内容你想说啥，跟我讲讲～
（直接打字回答；q = 不回答）
你> 我的电脑，内容就「猫爪测试」
（已作为手机提问的回答送过去）
```

确认类（敏感词拦截）默认**不再拦人**：`config.yml → catpaws.sensitive_confirm: false`（词表只进日志，也不会提示给 agent）。
真要恢复拦截就把它改 `true` 并重启 18110，届时确认问题同样由角色问、只认固定选项。

设备端等 150s（`catpaws.ask_timeout_sec`），func 侧窗口 90s（`catpaws.answer_timeout`），超时不答 agent 会按「用户没有回答」继续或收尾。

记忆语义（重要）：

| 项 | chat 模式 | 主程序 |
|---|---|---|
| 短期记忆（`.temp/public_short_mem.json`） | ✅ 写，且下次主程序/下次 chat 能接着读 | ✅ |
| 长期记忆 / 用户档案 / δ-mem | ❌ 默认不写（`--ltmem` 才写，避免测试污染） | ✅ |
| 情绪/心理快照、好感度 | ❌ 不触发 | ✅ |
| 工具调用（天气/QQ/绘画…） | ✅ 会真的执行（和主程序一致） | ✅ |

也就是说：`chat` 是"文字版主链路"，提示词与工具是真的，但**少了 TTS/情绪/长期记忆**这三条副作用链路；正式验收仍以 C 为准。

### D. 回归
- `logs/catpaws_ops/ops_<date>.jsonl`：每步动作、耗时、错误码；
- `logs/catpaws_thumbs/`：每步缩略图（`thumb_enabled`）；
- 失败时先看 `/cw/status` 的 `reason`：`device_error`（设备/锁屏）、`guard`（敏感词/限速/步数）、`llm_error`（模型）、`timeout`。

---

## 5. 滑动/点击适配结论

| 项 | 结论 |
|---|---|
| 点击坐标 | OCR 框中心；PC 把 tap 夹进安全框（上 141px / 下 102px），避免状态栏「滚到顶」与 home 手势 |
| 点击时长 | 不需要改：iOS 短按本就瞬时；长按走 `long_press`（默认 800ms） |
| 看图坐标 | 必须换算：image 模式发出去的是缩放图（1280/2.17≈591 宽），现在工具文本会同时给出两套尺寸和倍率 |
| 滑动距离 | 由 PC 按 `ratio × 可用高度` 算，默认 0.5；下限 90px，短了直接报错而不是静默无效 |
| 滑动速度 | 时长按 `距离 / 1.2px/ms` 推导（200~1600ms），避免默认 300ms 在大距离上变成 fling 过冲 |
| 滑动安全区 | 起止点都夹进 `(60,201)~(1223,2615)`，杜绝从底部起手触发 home、从顶部起手拉通知中心 |
| 惯性 | 提示词要求滑完 `wait 400ms` 再 observe；太快观察会拿到滑动中途的画面 |
| 批量 | `sequence_steps` 20→10（设备 8s 上限），`device_timeout` 8→10；`check_rate` 改按批，不再误杀长序列 |

标定（想更精确时再跑）：改 `config.yml → catpaws.swipe_speed_px_ms`（目标速度）与 `swipe_min_px`；
几何自检随时可跑：`runtime\311\python.exe scripts\_catpaws_geom_test.py`（不需要手机）。

---

## 6. 风险与注意

1. **一次只能一个客户端**：launcher 的 ps1 验收脚本别和主链路同时跑，会互相打断、输入打错 App；
2. 手机停在聊天输入框时最危险（草稿/回车即发）：链路开始前先按 home 复位；
3. 敏感词（支付/密码/转账…）会走确认，确认通道是 TBExcuse → 语音问你；首测别让它进支付页；
4. 中文输入只走 `paste_text`，且要先点输入框确认键盘弹出；
5. `RESULT: OK/FAIL` 缺失时按失败处理（宁可不报成功）；
6. 8 分钟以上的会话会被 `session_timeout_sec=900` 截断；`max_run_sec=300` 是 func 侧兜底；
7. 手机锁屏 → `E_DEVICE_LOCKED`，agent 会失败退出并回桌面，重新解锁再跑。
