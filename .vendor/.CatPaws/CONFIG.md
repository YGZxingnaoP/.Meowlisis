# CatPaws 配置（唯一真值）

`.vendor/.CatPaws` 的所有设置都在 **`config.yml`** 里，主项目 `config.yml` 不再有 `catpaws:` 节点。

| 段 | 作用 |
|---|---|
| `server` | CatPaws 服务监听地址/端口、视频中继端口、访问令牌 |
| `device` | 设备地址/端口（要跟 `catpaws-launcher/config.json` 的 `wda_port` 一致）、bundle id |
| `port` | 手机操作链路的独立 LLM 端口（deepseek / aliyun / gemini / meowllm，各带 base_url/api_key/model/温度/最大 token） |
| `vision` | 看图端口（截图长边 `max_edge`） |
| `agent` | 操作链路：`start_home`/`exit_to_home`、步数上限（0=不限）、超时（0=不掐断）、反思阶段、滑动与缩略图参数 |
| `stream` | 视频中继帧率/长边/码率 |
| `trigger` | 触发：`enabled`、`trigger_mode`（both/prefix/intent）、`prefix`（触发词）、`intent`（意图分析词）、`prompt`（意图判断提示词） |
| `stop` | 停止词（命中即立刻停手并结束链路） |
| `guard` | 应用黑白名单、应用别名、敏感词、反思阶段禁用词 |
| `sync` | 与主项目的桥接：轮询间隔、单次链路上限、等主人回答时长、是否回传记忆与播报、短期记忆轮数 |

## 谁读它

- `func/catpaws/config.py`（主项目侧：触发词、停止词、服务地址、`sync`、`port` 用于意图判断）
- `.vendor/.CatPaws/src/cw/config.py`（服务端：全部段）
- `gui/tools/catpaws_hub.py`（GUI 配置面板：读写）

## 改完什么时候生效

- 触发词/停止词/桥接参数：主项目在下一条消息就重新读取（`CWCatPawsConfig.refresh()`）；
- 服务端参数：重启 CatPaws 服务生效。

## 跑起来

1. `.vendor/.CatPaws/catpaws-launcher/start.cmd` → `status.cmd` 看到 `/cw/v1/ping -> 200`；
2. GUI 启动球「手机操作」或在日志中心选中「CatPaws(iOS)」点 ▶；
3. 聊天里说触发词，或在日志中心 CatPaws 面板里直接输目标。

## 手机息屏 / 锁屏（必须做）

XCTest 会话在锁屏后所有动作都会返回 `E_DEVICE_LOCKED`，而且 WDA 没法替主人输密码，
所以只能从设备侧根治（`docs/CW_IOS_SPEC.md` §10.3 也是这个要求）：

1. **设置 → 显示与亮度 → 自动锁定 → 永不**（最重要）；
2. **关掉「低电量模式」**：低电量模式会把自动锁定强制压到 30 秒，且「永不」不可选；
3. 建议顺手关掉「锁屏密码」，或至少保证跑任务期间别让它锁上（一锁就要人工解锁）；
4. 保持 USB 连接：拔线后 runner 约 28 秒被系统回收，链路直接断。

代码侧的兜底（已实现，不用配置）：

- 开链前 `press_key home` 撞到 `E_DEVICE_LOCKED` → 以角色口吻请主人解锁（最多问 3 次）；
- 操作中任何动作撞到锁屏 → 暂停链路喊主人解锁，解锁后自动接着做（最多 5 次，
  连续 5 次仍锁着就以 `device_locked` 结束，不会无限硬点）；
- **空闲自动点击（防息屏）**：`agent.keep_awake_sec`（**默认 0 = 关闭**）——链路进行中
  （操作中/反思中）超过这么多秒没有真实操作时，轻点一下屏幕重置系统的息屏计时；
  点哪里由 `agent.keep_awake_point: [x, y]`（截图像素）决定，**留空 = 状态栏正中**
  （键盘永远盖不到、也不会点到按钮；副作用只是可能把列表滚到顶部）。
  ⚠️ 别把点设在屏幕底部：输入法弹出时那里是空格键/发送键，会往输入框里塞字符、甚至发出去。
  这个点击不拍照、不进反思的操作记录，只算「用户交互」。

滑动（`agent.swipe_*`，真机实测过）：

- `swipe_speed_px_ms` 默认 **4.0** → 580px 只用 ≈145ms，是「甩动」，iOS 才会翻页；
- 调小会变成慢拖（1.2 时 535ms），画面只回弹不翻页——实测 535ms 不翻、145ms 翻；
- `swipe_min_px`（90）以下直接拒绝；`swipe_margin_px`（60）是距边缘的安全边距；
- 需要慢拖时由模型在步骤里显式给 `duration_ms`，会被夹在 120~700ms。


## 真机测试

```bat
runtime\311\python.exe scripts\catpaws_meituan_test.py --shots
```

不经过主项目（不写记忆、不出声），直接驱动服务端；详情见脚本头部注释。
