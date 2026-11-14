# scripts/MossLive-test —— MOSS-Live 全双工实时对话测试

> [English](README.en.md) | 中文

本目录是一个**独立**的 MOSS-Live 1.0 联调脚本：不启动主程序、不改 `config.yml`、不写主程序运行时目录。
目标是把四件事真正跑通：

- **全双工语音**：麦克风持续上行 16 kHz PCM，扬声器播放 48 kHz PCM，支持自然打断；
- **屏幕实时传递**：`mss` 实时抓屏，按服务端参数缩放/编码成 JPEG，逐帧推给模型（不是截图后上传）；
- **工具调用**：6 个本地工具，模型发起调用 → 本进程执行 → 回传结果 → 继续回答，其中 1 个异步工具；
- **复用全项目资产**：系统提示词直接读主项目的角色卡/前置词/价值观，参考音频直接读 `character/ref_audio`。

按需求，本轮**不写**短期记忆与长期记忆，也**不启用** client delegation（后台 Agent 委派）。

---

## 快速开始

### 1. 填 API Key

二选一：

- 编辑 `config.json` → `api.api_key`；
- 或设置环境变量 `MOSS_API_KEY`（`api.api_key_env` 可改）。

Key 只在 WebSocket 握手的 `Authorization` 头里发送。本目录不带任何 Key。

### 2. 先跑不连网的自检

```bat
:: 在项目根目录
runtime\311\python.exe scripts\MossLive-test\mosslive_test.py --selftest
```

会检查：提示词能否从项目里拼出来、参考音频能否处理成可上传的 WAV、屏幕能否抓帧、麦克风/扬声器能否打开、工具能否执行。
全部通过后再正式连服务。

只看提示词和音色、不碰设备也不连网：

```bat
runtime\311\python.exe scripts\MossLive-test\mosslive_test.py --dry-run
```

### 3. 正式联调

```bat
:: 双击也行
scripts\MossLive-test\run.bat

:: 或
runtime\311\python.exe scripts\MossLive-test\mosslive_test.py
```

启动后会依次打印：会话 ID、音色、媒体格式、工具列表。看到「会话就绪」就可以说话。

可以这样试：

| 说什么 | 验证什么 |
|---|---|
| 「你能看到我的屏幕吗？屏幕上现在是什么？」 | 屏幕帧 + 实时视觉理解 |
| 「现在几点了？」 | 同步工具 `get_time` |
| 「帮我在项目里找一下 MossLiveSession」 | 异步工具 `search_files`（不阻塞说话） |
| 「打开 https://example.com」 | 工具副作用 `open_url` |
| 「切到浏览器」 | `activate_window` |
| 在助手说话时直接插话 | 打断 → `response.audio.stop` → `playback.stopped` |

---

## 目录结构

```
scripts/MossLive-test/
├─ mosslive_test.py     入口：参数、dry-run、selftest、启动会话
├─ config.json          正式联调配置（要填 Key）
├─ mock_config.json     本地假服务用的配置（假 Key，不需要网络）
├─ mock_server.py       本地假 MOSS-Live 服务，只验证协议时序
├─ run.bat              双击启动（固定用 runtime\311\python.exe）
├─ mosslive/
│  ├─ config.py         配置合并/校验、项目路径与测试路径解析
│  ├─ prompt.py         从项目文件拼 persona / instructions
│  ├─ voice.py          参考音频 → 复刻音色 → 缓存
│  ├─ audio.py          麦克风采集 + 播放队列 + 播放回执
│  ├─ screen.py         mss 实时抓屏 → JPEG 帧
│  ├─ tools.py          工具定义与执行
│  ├─ session.py        MOSS-Live 协议主循环
│  └─ console.py        终端输出 + sessions/*.jsonl 转录
└─ sessions/ notes/ frames/ voice_cache.json   （运行时产物，已 gitignore）
```

---

## 数据流

```
麦克风 16 kHz PCM16 ──(0x00 前缀)──┐
屏幕 JPEG（mss 实时抓帧）──(0x02 前缀)──┤──> wss://api.mosi.cn/v1/realtime
                                      │
下行文本事件 <─────────────────────────┤
下行 48 kHz PCM16 ──> 播放队列 ──> 扬声器 │
  每块播完 ──> playback.chunk.completed ┘
  整轮播完 ──> playback.completed
  被 stop ──> playback.stopped + played_audio_ms
```

连接后的顺序：`attach_session` → `change_voice` → `session.update` → `media.mode` → `media.configure` →
收到 `media.configured` 后才开始推音频/画面，并发送 `client_context.update`、`video.state`、`mic_state`。

---

## 配置说明

配置分两套路径：

- **项目相对路径**（`prompt.*`、`voice.ref_audio.*`）：相对 `D:\.Meowlisis`，可以指向项目里任何文件；
- **测试目录相对路径**（`voice.clone.cache_file`、`tools.notes_file`、`log.sessions_dir`、`screen.frames_dir`）：相对本目录。

### api

| 字段 | 说明 |
|---|---|
| `realtime_url` | 固定 `wss://api.mosi.cn/v1/realtime` |
| `http_base` | 复刻音色用 `https://api.mosi.cn` |
| `api_key` / `api_key_env` | Key 或读取的环境变量名 |
| `model` | `moss-live-1.0`（也可用带日期的快照 ID） |
| `user` | 稳定终端用户 ID，会 URL 编码后拼到连接地址 |
| `proxy` | `null` 直连；需要代理时填 `http://127.0.0.1:7890` |

### session

| 字段 | 说明 |
|---|---|
| `memory_scope` | `session`（本轮不写记忆，保持会话级） |
| `playback` | `client`：按实际播放进度回执；`server`：服务端代确认 |
| `profile` | `standard`（16k 上行 / 48k 下行）或 `low` |
| `output_audio` / `input_audio` | 本测试只做 `pcm16` 下行 |
| `video` | 请求画面参数，最终以 `media.configured.video` 为准 |
| `time_zone` | 发给模型的设备时区 |
| `location` | 可选 `{latitude, longitude}` |

### prompt

| 字段 | 说明 |
|---|---|
| `mode` | `project`（默认，角色卡+前置词+价值观） / `files` / `inline` |
| `persona_name` | 留空时取角色卡名字 |
| `persona_inline` | `mode=inline` 时的人设文本 |
| `display_name` | 替换前置词里的 `{display_name(uid)}` |
| `card_file` | 留空时读 `config.yml` 的 `character_card.card_file`，默认 `prompt` |
| `include_front_prompt` | 是否把 `character/front/prompt.json#prompt` 放进 instructions |
| `include_active_prompt` | 是否也放 `prompt_active`（主动说话场景用，默认关） |
| `include_values` | 是否把 `character/info/values/latest.json` 放进 persona |
| `extra_sources` | 任意项目文件追加进 persona / instructions，见下 |
| `instructions` | 额外的会话指令 |
| `instructions_files` | 指令文件列表（项目相对路径） |
| `max_persona_chars` | 默认 8000，超了截断并告警 |
| `max_instructions_chars` | 默认 16000 |

`extra_sources` 示例（`config.json` 里加）：

```json
"extra_sources": [
  {
    "path": "工作流程解析/docs/某个说明.md",
    "label": "项目说明",
    "target": "instructions"
  },
  {
    "path": "character/front/armor-piercing-prompt.json",
    "json_key": "prompt",
    "label": "破甲词",
    "target": "instructions"
  }
]
```

`target` 为 `persona` 或 `instructions`；`json_key` 支持 `a.b.c` 嵌套取值。

### voice

| 字段 | 说明 |
|---|---|
| `mode` | `clone`（默认，用参考音频复刻）/ `name`（直接用 voice_id）/ `default` |
| `name` | `mode=name` 时的 voice_id |
| `fallback_name` | 复刻失败或没有参考音频时的现成音色 ID |
| `ref_audio.source` | 参考音频配置，默认 `character/ref_audio/config.json` |
| `ref_audio.character` | 角色名，留空用角色卡名字 |
| `ref_audio.emotion` | 取哪条情绪音频，默认 `neutral` |
| `ref_audio.file` | 直接指定 wav（优先于 source） |
| `clone.voice_name` | 平台上的音色名称 |
| `clone.cache_file` | 复刻结果缓存，默认 `voice_cache.json` |
| `clone.recreate` | `true` 时强制重新复刻 |
| `clone.max_seconds` | 裁剪上限，默认 29（接口上限 30 秒 / 10 MB） |

流程：读参考音频 → 转单声道 16bit WAV、裁到 29 秒 → `POST /v1/audio/voices`（multipart `audio_sample`）→
拿到 `id` 后在会话里 `change_voice` → 结果写进 `voice_cache.json`，下次同一文件直接复用。

### audio

| 字段 | 说明 |
|---|---|
| `input_device` / `output_device` | PyAudio 设备序号，`-1` 用系统默认；用 `--list-devices` 查 |
| `input_rate` / `output_rate` | 期望采样率；设备不支持时自动换并本地重采样 |
| `frame_ms` | 上行每帧毫秒数，默认 20 |
| `input_enabled` | 关掉后不采集、不上行 |
| `output_enabled` | 关掉后本地不播放，但仍按时间模拟并回执 |
| `volume` | 播放增益，1.0 原样 |

### screen

| 字段 | 说明 |
|---|---|
| `enabled` | 是否推屏幕 |
| `monitor` | mss 显示器序号：0=全部，1=主屏，2=第二块 |
| `region` | 可选 `{left, top, width, height}`，优先于 monitor |
| `interval_ms` | 帧间隔，接口下限 200，默认 1000 |
| `max_long_side` | 长边像素，128~1920，默认 512 |
| `jpeg_quality` | 0.1~1，默认 0.75 |
| `save_frames` | 调试用：每 30 帧存一张到 `frames/`，默认关 |

### tools

| 字段 | 说明 |
|---|---|
| `enabled` | 启用的工具名列表（顺序会原样发给服务端） |
| `search_root` | `search_files` 的默认目录，留空为项目根 |
| `search_max_results` | 默认返回条数 |
| `notes_file` | `save_note` 的写入文件，测试目录相对路径 |

### log

| 字段 | 说明 |
|---|---|
| `level` | `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `save_events` | 是否把服务端事件写进 `sessions/*.jsonl` |
| `verbose_events` | 是否把原始事件打到终端 |
| `show_partial` | 是否显示逐字转写快照 |

---

## 屏幕实时传递细节

- 走 `tagged-v1`：音频 `0x00 + PCM`，屏幕 `0x02 + JPEG`，与音频共用同一条 WebSocket。
- 每帧是一张独立 JPEG，**不是** Base64、MP4 或 H.264；采集、缩放、编码都在本地线程完成，避免阻塞 WebSocket。
- 采集参数以 `media.configured.video` 返回值为准；服务端调整了间隔/尺寸/质量，客户端会跟着改。
- 抓屏用 `mss`，比 `ImageGrab` 快很多；帧率过高会浪费带宽和模型上下文，默认 1 秒一帧足够。
- 屏幕内容会原样上传到云端模型，注意隐私：开会、聊天窗口、密码管理器别留在主屏上。

---

## 工具列表

| 工具 | 类型 | 作用 | 副作用 |
|---|---|---|---|
| `get_time` | sync | 查当前时间/星期/时区 | 无 |
| `open_url` | sync | 默认浏览器打开 http(s) 网址 | 打开浏览器 |
| `list_windows` | sync | 列出可见窗口标题 | 无 |
| `activate_window` | sync | 按标题关键字切前台 | 切换窗口 |
| `save_note` | sync | 追加一条本地便签 | 写 `notes/notes.md` |
| `search_files` | async_query | 在项目里搜文件名/正文 | 无 |

`search_files` 声明为 `async_query`：查询期间用户还能继续说话，结果回来后再续答；
其余是 `sync`，模型这一轮会等结果（都很快）。

想加减工具：改 `tools.enabled`，并在 `mosslive/tools.py` 的 `_specs()` / `_tool_*` 里增删。
工具列表在一次会话里尽量保持不变（服务端要求稳定），本测试只在启动时配置一次。

---

## 系统提示词与参考音频的来源

| 内容 | 来源 | 去向 |
|---|---|---|
| 角色卡 | `character/info/character_prompt/<card_file>.json` | persona |
| 当前性格/情绪 | `.temp/latest_emotion.json`（只读） | persona 的角色性格/情绪行 |
| 价值观 | `character/info/values/latest.json` | persona |
| 前置词 | `character/front/prompt.json#prompt` | instructions |
| 后置词 | `character/front/prompt.json#post_prompt` | persona 末尾 |
| 额外文件 | `prompt.extra_sources` 指定的任意项目文件 | persona / instructions |
| 参考音频 | `character/ref_audio/config.json` → `character/ref_audio/*.wav` | 复刻成 voice_id |

没有 `import func.*`：主项目的构建器依赖运行中的单例、日志文件锁和 `.temp` 状态，独立脚本里 import 容易互相干扰。
这里只读**同样的文件**，字段顺序与主项目 `character_prompt.build` 保持一致。

---

## 本地协议自测（不需要 API Key）

`mock_server.py` 是一个假 MOSS-Live 服务，只验证协议时序和媒体格式，不理解语音内容。

```bat
:: 窗口 1
runtime\311\python.exe scripts\MossLive-test\mock_server.py

:: 窗口 2
runtime\311\python.exe scripts\MossLive-test\mosslive_test.py --config scripts\MossLive-test\mock_config.json
```

它会检查：Authorization 头、`attach_session`/`change_voice`/`session.update`、媒体配置、时区、
上行音频帧、屏幕 JPEG、播放回执、工具调用往返、以及打断后的 `playback.stopped`。
最后打印一行 `REPORT {...}`，`fails` 为空即通过；假服务进程退出码 0。

---

## 常见问题

**`未找到 MOSS API Key`**
填 `config.json` 的 `api.api_key` 或设置 `MOSS_API_KEY`。

**握手 401 / 403**
Key 无效或没有 MOSS-Live 权限。确认 Key 没多空格，账号已开通实时对话。

**`session.update 失败: ...`**
看服务端错误码。常见原因：persona 超过 8000 字符、instructions 超 16000、工具 schema 不合法或列表内重名。
本脚本会在超长时自动截断并告警，但工具参数写错不会自动修。

**音色没换成参考音频**
复刻失败会打印原因并回落到 `fallback_name`；再不行用服务端默认音色。
先跑 `--selftest` 看参考音频能否处理成 ≤10 MB / ≤30 秒的 WAV。

**没有声音 / 没有麦克风**
`--list-devices` 找设备序号，填 `audio.input_device` / `output_device`；再跑 `--selftest`。
没有输出设备或 `output_enabled=false` 时会改成按时间模拟播放，仍然回执，不会把服务端卡住。

**说话被自己的回声打断**
外放会被麦克风收回去。戴耳机，或把播放设备设成虚拟声卡；只想测屏幕可以 `--no-mic`。

**服务端返回 `code=1006` 关闭**
连接被异常断开（网络/服务端维护）。脚本不自动重连，重跑即可；会话 ID 会打印出来。

**服务端要求 opus**
本测试只实现 pcm16 播放，会直接报错。保持 `session.output_audio.format=pcm16` 或 `profile=standard`。

---

## 已知限制

- 不接短期记忆/长期记忆，会话之间不共享上下文（`memory_scope=session`）。
- 不启用 client delegation，也没有后台 Agent 执行器。
- 不做断线重连；`session.closing` 后直接结束。
- 只实现 `pcm16` 下行播放；opus/mp3 未接解码器。
- 一次只推一路画面（一个显示器或一个区域）。
- 工具是测试用的本地实现，不复用主项目工具箱（避免把主程序状态拖进来）。
- 没有回声消除（AEC），外放时可能自问自答。

---

## 本地验证记录（2026-11-14）

- `--dry-run`：persona 约 1.6k 字符、instructions 约 1.3k 字符，6 个工具定义正常。
- `--selftest`：截屏 512×320 / 17 KB，麦克风 16 kHz、扬声器 48 kHz 均可打开，参考音频 4.4 秒可转成 382 KB WAV，`get_time`/`list_windows`/`search_files` 正常。
- `mock_server.py` 端到端：音频帧约 130、屏幕帧 6（512×320）、播放回执、工具往返、打断回执全部通过，`fails: []`。
