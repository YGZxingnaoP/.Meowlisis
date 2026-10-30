# 观影陪伴（movie_watch）

安静陪你看片：每隔 3~4 分钟随机截一帧、顺手把这几分钟听到的台词一起记下来，**全程不出声**；
你开口问的时候用它自己的记录回答；你说结束后，它说一段**影评（不道谢）**，然后把整场归档。

> **本插件零主项目依赖**：不 `import func.*` 任何模块。插件基线自带（`plugin_base.py`），
> 视觉/回环采集/ASR 全部自包含，只按 YAML 读主程序 `config.yml` 里的 key 与地址（读数据，不读代码）。
> 整个 `plugins/movie_watch/` 目录可以单独拷走。

> 与主程序「长期盯屏（watching）」的区别：watching 每帧都评价并当场说给你听；
> 本插件全程闭嘴只写笔记，等你问才开口，结束后给一段影评。

## 怎么用

| 你说 | 发生什么 |
|---|---|
| 「陪我看电影」「一起看片」「观影模式」 | 绑定播放器窗口（会先确认像不像在放片）→ 说一句开播话 → 进入静音记录 |
| 「刚才演到哪了」「剧情」「台词说了什么」「你觉得怎么样」 | 用自己记下的画面+台词+感想回答（60~120 字） |
| 「看完了」「结束观影」「不看了」 | 说一段整体影评（不道谢）→ 归档 → 退出静音状态 |
| （什么都不说） | 一句都不说，只默默记录 |

- 语音链路与 QQ 链路都能触发（QQ 用文字回复，不占本地喇叭）。
- 观影中自动关闭弹幕朗读 / 礼物播报 / 主动回复 / 待办提醒，避免一直说话。
- 播放器窗口消失（连续 `capture.window_gone_confirm` 秒）或到达 `capture.max_duration`，自动收尾。
- 观影结束后再问「刚才那部讲什么了」，会去读最近一场的归档回答。

## 开播前的窗口确认（防误触发，浏览器也能绑）

默认 `capture.mode=window`：优先按 `capture.window_title` 匹配，留空则绑开播那一刻的**前台窗口**，然后：

1. **找不到窗口** → 不开播，角色自己问你窗口名（`capture.allow_fullscreen_fallback=true` 才退回整屏）；
2. **窗口标题不像在放片**（浏览器标签页、IDE、聊天窗口）→ **试听 2.5 秒扬声器回环**：
   - 有声音（RMS ≥ `capture.confirm_audio_level`）→ 当作在放片，正常开播（浏览器看片就走这条路）；
   - 没声音 → 不开播，角色报出绑到的窗口名等你确认；
3. 说「**就盯这个窗口**」「**看整屏**」可显式跳过上面的判定；
4. 开播那句（由角色自己组织，见下）会顺口提到绑到的窗口名，绑错了当场能改。

标题判定依据：进程名（vlc/potplayer/mpv/…）+ 标题关键词（B站/爱奇艺/YouTube/电影/第N集/视频…）+ 视频后缀（.mkv/.mp4/…）。
试听复用台词识别那条回环，只开一次设备。

## 台词怎么来的

`dialogue.enabled=true`（默认）时会**单开一条识别会话**：扬声器回环（WASAPI loopback）→
SenseVoice 服务（默认 `ws://127.0.0.1:10095/`）→ 台词文本，然后和截图一起发给视觉模型：

```
第 1 张画面 + 「刚才这几分钟听到的台词（语音识别，无角色名、可能有错字）：…」
```

- 识别结果**只进本插件**，不进主对话链路 —— 看电影时它不会跟着台词搭话。
- **台词窗口和截屏时机是吻合的**：每帧取的是「上一帧到现在」这一段（`notes.span` 记录实际秒数），
  不是固定回看 N 秒 —— 所以 180 秒一帧就配 180 秒台词，240 秒一帧就配 240 秒台词，
  画面和台词永远对得上；`dialogue.window`（默认 300）只是上限，防机器休眠后一次灌太多。
- **没有角色名**：语音识别只给连续文本，模型按语境自己判断谁在说话；提示词明确要求「认不准就说『有人』，别硬编人名」。
- 台词可能是**外语原文**（日语番/英语片），提示词要求模型理解意思、用中文说感想。
- 背景音乐常年高于能量阈值，VAD 很难自然断句，所以加了 `dialogue.segment_seconds`（默认 8 秒）**强制分句**——
  实测 8 秒约出 1 句，3 分钟窗口能攒 20~30 句。
- 前提：装了 `pyaudiowpatch`（本机已装）+ SenseVoice 服务在跑（GUI 服务面板 / `.vendor/.SenseVoice/start.bat`）。
  任一不满足 → 自动退回「只看画面」，开播那句会补一句说明，不会卡住观影。
- 回环默认跟随系统默认输出；本机有 8 个回环设备（Voicemeeter/VAC/耳机…），`dialogue.device_index` 可指定。
- **不做联网搜索**：只信画面、台词和自己的记录。

## 说话全部由角色自己组织（没有预设台词）

插件里没有任何写死的台词：开播那句、找不到窗口、窗口要确认、重复开播、看不了画面、还没记到画面……
都只给模型一条「**这次要传达的意思**」（`prompts.SAY_SYSTEM`），由它用自己的口吻说出来。
`voice.start_hint` 只是可选的「意思补充」，不是台词模板。文本模型不可用时才退回一句极简兜底，保证不至于哑掉。

## 数据在哪

运行中（缓存，归档后默认清理）：

```
.temp/movie_watch/<场次>/
├── meta.json      场次信息（窗口、视觉模型、台词来源、间隔）
├── notes.jsonl    每帧一条：{ts, clock, time, shot, scene, dialogue, comment, size}
├── shots/         截图（record.keep_shots=false 则调用后即删）
└── ending.txt     收尾影评
```

结束后（归档，永久保留）：

```
character/plugin_data/movie_watch/<内部编号>/
├── latest.json    最近一场索引（供结束后提问）
├── index.jsonl    全部场次索引
└── <场次>/{meta.json, notes.jsonl, ending.txt, summary.md, shots/}
```

## 配置（GUI 插件卡 → 观影陪伴）

配置落在 `plugins/movie_watch/config.yml`，改完重启主程序生效。

| 键 | 说明 |
|---|---|
| `capture.mode` | `window`=只截播放器画面（推荐）/ `fullscreen`=整块屏幕 |
| `capture.window_title` | 窗口标题包含匹配；留空=开播那一刻的前台窗口 |
| `capture.confirm_video_window` | 窗口不像在放片时先试听再决定（默认开，防误触发） |
| `capture.confirm_by_audio` | 用回环试听确认「电脑在出声」（浏览器看片靠这个放行） |
| `capture.confirm_audio_level` / `confirm_audio_seconds` | 试听阈值（RMS 默认 80）/ 试听时长（默认 2.5 秒） |
| `capture.allow_fullscreen_fallback` | 找不到窗口时退回整屏（默认关） |
| `capture.min_interval` / `max_interval` | 每帧间隔的随机区间，默认 180~240 秒 |
| `capture.max_duration` | 单场上限（默认 4 小时），到点自动收尾 |
| `capture.max_side` / `jpeg_quality` | 截图等比缩小与压缩（默认长边 1280、质量 82） |
| `capture.window_gone_confirm` | 窗口消失多少秒算「电影结束」，0=关闭该检测 |
| `vision.source` | `meowvision`=复用主程序视觉配置（默认）/ `custom`=插件独立配置 |
| `vision.*` | `custom` 时生效：平台 / key / base_url / 模型 / max_tokens / 温度 |
| `vision.thinking` | 视觉思考模式，默认关（实测同一帧会多花 900~4500 输出 token） |
| `dialogue.enabled` | 用 SenseVoice 记台词（默认开） |
| `dialogue.device_index` | 回环设备索引，-1=自动 |
| `dialogue.window` | 台词回看**上限**（实际按「上一帧到现在」，默认 300） |
| `dialogue.max_chars` | 每帧台词最多多少字（默认 600，超出从最早的开始丢） |
| `dialogue.segment_seconds` | 强制分句间隔（默认 8 秒；靠它才能在背景音乐里拿到台词） |
| `dialogue.vad_threshold` | 语音能量阈值，0=跟随主程序；片源声音小就调低 |
| `dialogue.server_url` | 识别服务地址，留空用主程序 `sensevoice.server_url` |
| `record.keep_shots` | 归档是否保留截图 |
| `record.max_notes` | 单场最多记录条数 |
| `record.comment_chars` | **安全截断**：模型写多少留多少，超过才砍（默认 400） |
| `record.context_notes` | 回答提问/收尾时带最近多少条记录给模型 |
| `record.short_memory` | 收尾是否写一条短期记忆 |
| `voice.start_line` | 开播是否说一句（台词由角色自己组织） |
| `voice.start_hint` | 开播要传达的意思（可留空；不是台词模板） |
| `voice.report_window` | 开播时顺口提一句绑到的窗口 |
| `voice.emotion` | 播报声线，留空用当前情绪 |
| `archive.dir` / `keep_temp` | 归档目录 / 归档后是否保留 `.temp` |
| `temp_dir` | （手动配置项，默认 `.temp/movie_watch`）运行缓存目录 |

## 开销实测（2 小时一场）

实测口径：1280×800 截图 + 完整人设 + 约 200 字台词 + 80~200 字感想，`vision.thinking=false`。

| 项 | 单帧 / 单次 | 2 小时合计 |
|---|---|---|
| 视觉输入 | 约 3,000 tokens（人设+指令 2,000 / 图片 1,002） | ≈ 102K（34 帧） |
| 视觉输出 | 约 180 tokens | ≈ 6.2K |
| 收尾影评 / 提问（文本模型） | 约 11K 输入 / 0.12K 输出（带 34 条笔记） | 1 次 + 每问一次 |
| 合计（含 2 次提问） | — | ≈ 138K 输入 / 6.8K 输出 |
| 磁盘截图 | 40~130 KB/帧 | 约 2~4 MB |

按百炼 flash 档参考价（¥0.8/百万输入、¥2.69/百万输出）+ deepseek-flash（$0.15~0.3/百万输入、
$0.6~1.2/百万输出）：一场两小时约 **¥0.14 ~ 0.18**。开思考模式约 **¥0.6**，所以默认关。

降本手段：① `record.context_notes` 从 40 降到 20（收尾/提问的笔记上下文减半，最有效）；
② `dialogue.max_chars` 从 600 降到 300；③ `capture.max_side` 降到 960；④ 间隔改 5 分钟。

## 触发判定（开始 / 结束 / 提问）

不是正则，是**子串包含匹配**（`in`）+ LLM 决策两层，谁先命中谁生效：

| 时机 | 判定层 | 说明 |
|---|---|---|
| 非观影状态 | ① `trigger_words` 关键词硬触发 | 「陪我看电影/一起看片/观影模式…」命中即直接调用，不过 LLM |
| 非观影状态 | ② LLM 意图决策 | 看工具 `description` + `prompt_hint`，能识别别的说法 |
| 开播时 | ③ 窗口确认 | 见上文，不像在放片就拒绝 |
| 观影进行中 | ④ `route_text` 会话拦截 | 每次输入先过 `STOP_WORDS` / `ASK_WORDS`，命中就接管并吞掉这条输入，零 LLM |
| 观影进行中 | ⑤ LLM 意图决策 | 没命中关键词时，仍可由 LLM 调 `movie_watch(action=ask/stop)` |
| 自动收尾 | ⑥ 窗口消失 / 时长到点 | `capture.window_gone_confirm` / `capture.max_duration` |

- 词表在 `session.py` 顶部，改词表即可调松紧；「观影进行中」才会吞输入，其它时候一律放行。
- 想更严：把 `STOP_WORDS` 里的「看完了」删掉，只留「观影结束/电影结束了」。

## 依赖

- 视觉模型：默认复用主程序 `config.yml → meowvision`（当前 `qwen3.7-flash`）。
- 台词：`pyaudiowpatch` + 主程序 SenseVoice 服务（`func/sensevoice`，FunASR 协议）。
- 文本模型：收尾影评与答疑用主程序 toolbox 文本模型（`ctx.llm()`）+ 角色人设提示词。
- 截图：`Pillow.ImageGrab`；窗口绑定用 `pywin32`（缺失时退回整屏）。
- 卡面 `card.png` 由 ComfyUI 生成，见下。

## 卡面重生成

复用 `plugins/card.png` 内嵌的同一套工作流（同一角色/画风）：

```powershell
python plugins/movie_watch/tool/gen_card.py check    # 查模型 / LoRA / 预览提示词
python plugins/movie_watch/tool/gen_card.py submit   # 提交任务
python plugins/movie_watch/tool/gen_card.py fetch    # 轮询并写回 plugins/movie_watch/card.png
```

需要 ComfyUI 在 `127.0.0.1:8188`。

## 已知限制

- 同一时刻只允许一场观影；重复开播会被拒绝。
- 台词识别依赖 SenseVoice 服务；服务没起就只有画面，没有台词。
- 台词**没有角色名**，模型只能按语境猜谁在说；识别结果可能有错字，外语片拿到的是原文。
- 用耳机看电影时回环照样能听到（采的是系统输出，不是麦克风）；但**外放 + 麦克风**那条链路属于主程序，
  本插件不接管，也不改。
- 记录只覆盖「每隔几分钟的那一帧 + 这几分钟听到的台词」，中间细节靠模型按上下文推断。
- 截图会等比缩小后发给视觉模型（与主程序 `meowvision` 行为一致）。
