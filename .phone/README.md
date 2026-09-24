# 喵呜手机界面（.phone）

独立的手机端 + 电脑观看端。手机浏览器打开网页即可：**整屏显示手机摄像头画面**、桌宠悬浮、说话/回复以气泡贴桌宠显示、底部三枚按钮球（摄像头 / 麦克风 / 消息）。主项目**零改动**，全部通过既有 HTTP 接口桥接到 `api.py`。

## 原理

- `.phone/serve.py` 起一个 HTTPS 服务（**单端口 8443**，自签名证书）：
  - 提供手机页 `static/`（`/`）、电脑观看页（`/cam`）
  - 把 `.desktopet` 暴露为 `/pet/`，供手机页 iframe 加载桌宠（同源，避免混合内容）
  - **同一端口同一证书**上承接 WebSocket（`/ws`）：手机端上行视频/音频，电脑端下行视频。无需第二个端口、无需二次证书授权。
  - 反向代理到主程序 `api.py`（127.0.0.1:1800）：`/chat`、`/msg`、`/audio/send`、`/audio/end`、`/mic`、`/chatreply`、`/phone/audio`、`/tts/audio`
  - 接收主程序推送的手机端 TTS PCM（`/api/tts/phone`），供手机轮询播放（`/api/tts/pending`）

## 一、摄像机（手机 → 电脑）

1. 手机端 `getUserMedia` 取摄像头（默认**后置 / 外界**，顶部右上角迷你 ⇄ 切换前后；请求 1280×720、≤30fps）。
2. 手机端用 **WebCodecs `VideoEncoder`（H.264 / avc1.42E01E，优先硬件编码）** 编码，按 Annex-B 输出，`latencyMode=realtime`，每 **2 秒**强制一个关键帧。
3. 编码块经 `/ws` 二进制帧上行（`[0x01][flags][ts_us u64][h264]`）。
4. `.phone` 侧 `ws_hub` 缓存最新 GOP 并转发给所有观看端；新观看端接入即补发最新关键帧，秒开。
5. 电脑端打开 `https://<电脑IP>:8443/cam`：WebCodecs `VideoDecoder` 解码 → canvas 播放，带极简 **REC 取景框**（红点 REC + 四角框 + 状态/帧率）。
6. 关闭摄像头会 `track.stop()` 释放设备（省电），观看端提示「手机摄像头已关闭」。

> **尺寸/方向以实际视频帧为准**：手机端**先把摄像头画面画进 canvas，再从这个 canvas 编码**，且这块 canvas 就是手机上的预览画面 —— 所以"手机上看到什么，电脑端就收到什么"，不会出现横竖颠倒或拉伸。编码尺寸取 `video.videoWidth/videoHeight`（不用 `track.getSettings()`，它在 iOS 上可能返回传感器尺寸）；观看端用解码后 `VideoFrame.displayWidth/displayHeight` 决定画布尺寸与显示比例，并按窗口等比自适应，中途旋转/切换前后摄像头也会自动重建编码器与解码器。
>
> 前端静态资源以 `Cache-Control: no-store` 提供，改动后刷新即生效，不会被浏览器缓存住旧版本。

> 说明：按需求不做降级（不支持 WebCodecs H.264 的设备会直接提示不可用）。

## 二、麦克风（手机 → 主项目 SenseVoice）

1. 手机端点击 🎤 开麦：`getUserMedia` 音频 → `AudioWorklet` → **int16 原生采样率单声道 PCM** → `/ws` 上行（`[0x02][pcm]`）。
2. `.phone` 侧 `audio_gateway` 把原生采样率**流式重采样到 16k 单声道**（`samplerate`，`sinc_medium`，与主项目一致）。
3. 复刻主项目 `InterruptDetector` 的**能量 VAD**（阈值读 `config.yml → sensevoice.vad_energy_threshold`，静音 `silence_threshold` 秒判停），把连续流切成一段段话：
   - 说话中：逐块 `POST /audio/send?username=昵称`
   - 段末（静音达阈值 / 段超 30s / 断流）：`POST /audio/end`
4. 这样主项目的 `inject` 源拿到与「按住说话」完全一致的句边界，识别文本才会进入 LLM。

> 需要在电脑端**打开主项目的 inject 源**（`config.yml → sensevoice.sources.inject.enabled: true`，默认已是 true）。

## 三、合成语音回手机（播放修复）

主项目 `source=="phone"`（手机说话 + 手机打字）的合成音频推送到 `/api/tts/phone`，手机轮询 `/api/tts/pending` 播放。

本次修复了「乱序 / 同时播放 / 丢尾」：

- 服务端 `tts_relay.py`：PCM 全局单调 `seq`；按 **模式 + 来源** 过滤；`end` 后不立即清空 meta（静音 4s 回收）；大块自动拆分、单次拉取有 **条数 + 字节** 双上限（防止长音频把手机撑爆）。
- 手机端 `player.js`：轮询**单飞**；时间线 `_nextStart` **只向前不回拨**；严格按 `seq` 递增调度。
- 主项目 `func/pipeline/tts_phone.py`：发送线程改为**单队列严格保序**（start 必先于其数据块、end 必后于其数据块），修掉了"每个流第一块可能先于 start"的固有乱序（会导致来源过滤失效 / 采样率取错 / 尾块丢失）。

### AI 气泡只显示“手机相关”的回复

- `/api/chatreply` 走的是主项目 `ReplyTextList`，而主项目 `SubtitleWorker` 会把**所有来源**的 TTS 字幕都塞进去，因此**不再使用**它做气泡。
- AI 气泡改由 **`/api/tts/phone` 推送的 `meta.text`** 驱动 —— 聊天模式下该通道只承载 `source=="phone"`，通话模式下承载全部来源，天然与模式一致。
- 用户气泡来自手机打字（`/chat`）与手机语音识别字幕（`/api/phone/audio`）。

## 四、通话模式 / 聊天模式

手机顶部的胶囊按钮切换（`GET/POST /api/mode?mode=chat|call`）。模式会**持久化**到 `.phone/mode.txt`，重启服务后保持不变（启动日志也会打印当前模式）。

| | 聊天模式（默认） | 通话模式 |
|---|---|---|
| 手机能听到 | 只有"手机自己发起"的回复（说话 / 打字） | **主项目合成的一切**（本地麦、弹幕、工具箱、主动回复、盯屏说话、哼唱…） |
| 手机气泡 | 只显示手机相关回复 | 显示全部合成文本 |
| 电脑端 | 照常播放 | 照常播放（主项目无法静音） |

实现：主项目播放线程本地播出的那份 PCM 会**旁路复制**一份给 `.phone`（`source` 一并带上），`.phone` 的 `tts_relay` 按当前模式决定"保留还是丢弃"。因此：

- 通话模式下电脑和手机听的是**同一份 PCM**（逐样本一致），手机仅滞后约 0.4s；
- **不会重复**：`phone` 来源走原生通道，其余走旁路，`.phone` 播放线程里这两条路互斥；
- **零额外合成算力**（不二次合成）。

配套：手机在"正在播放 AI 音频"期间会**暂停麦克风上行**（`audio.js` 的 gate，播放结束后 150ms 恢复），避免手机外放被自己的麦克风拾到、上行后被主项目当成用户说话而形成**自我对话循环**。

## 五、OBS / Tailscale / 排查

**OBS 浏览器源（电脑 cam 画面）**：用**纯 HTTP** 地址，别用 HTTPS（OBS 的浏览器内核不接受自签名证书，会白屏）：

```
http://127.0.0.1:8445/cam
```
该端口同时提供 `/cam`、`/static/*` 与 **`ws://127.0.0.1:8445/ws`**（页面用 `location` 自动推导，与 HTTP 同端口，所以不踩证书问题）；桌宠页也在同端口：`http://127.0.0.1:8445/pet/renderer/index.html`（可加 `?autofit=1&fit=0.13`）。

> 改动前端后**必须重启 `.phone/serve.py`**，并确认没有旧进程占着 8443/8445（旧进程会让端口继续提供老代码）。

**Tailscale**：服务监听 `0.0.0.0`，手机改用 Tailscale 地址即可 `https://<100.x.x.x>:8443`（或 MagicDNS 名 `https://<机器>.<tailnet>.ts.net:8443`），首次仍需点「继续前往」接受自签名证书；拍照/麦克风需要安全上下文，接受证书后 HTTPS 即满足。
想彻底去掉证书警告：用 `tailscale cert <名字>.ts.net` 签发的证书覆盖 `.phone/cert/cert.pem` 与 `key.pem`（存在即复用，不会重新生成）。

**听不到/听错排查**：浏览器打开诊断页（每秒自动刷新）：

```
https://<IP>:8443/debug
```
或直接取 JSON：`https://<IP>:8443/api/tts/debug`

```json
{"mode":"chat","buffered_blocks":1,"buffered_bytes":300,
 "meta":{"source":"phone","text":"…","seg_index":1,"sample_rate":32000},
 "log":[{"source":"toolbox_danmaku","kept":false,"bytes":500},
        {"source":"phone","kept":true,"bytes":300}]}
```
`kept:false` = 该来源在当前模式下被过滤（聊天模式只保留 `phone`）。

**同轮回复跟随规则**：某个 `traceid` 的第一段若被保留，则**它的后续分段一律保留**（即使分段带了不同的 source 标记），避免"只收到第一句"。切模式时该记录清空，90 秒无活动自动过期。

**注意**：聊天模式**严格**只放手机自己发起的对话（`source=phone` 及其同轮分段），不做任何白名单；要听全部语音就切到**通话**模式。切换时手机底部会弹一行提示当前模式，模式持久化到 `.phone/mode.txt`。

## 六、界面约定

- 气泡**只显示 AI 回复**，且为白底深字、**自适应宽度**（内容短就短，最长不超过屏幕，超出自动换行）。
- 用户输入（手机打字 + 语音识别结果）**不进气泡**，只在底部显示一行小字（6 秒后淡出）。
- 顶部胶囊：`通话·全部` / `聊天·仅我`；
- 左上角 `🔊/🔇` + 音量滑条：手机端播放 AI 语音的音量（记忆到 localStorage，刷新后保留）；
- 右上角迷你 ⇄：前后摄像头切换。
- 首次打开/刷新后**必须点一下屏幕**才会有声音（浏览器自动播放策略），未解锁时底部会提示「点一下屏幕开启声音」。

## 七、手机声音回传到观看端（直播间能听到你本人）

- 手机开着 🎤 时，上行音频**一路给 SenseVoice 识别，另一路原样转发**给所有观看端（WS 二进制 `0x03` 帧：`[0x03][rate u32 BE][s16le mono]`）；
- `/cam` 页面会自动播放（右上角 `🔊/🔇` 开关 + 音量滑条，状态与音量都记忆在 localStorage）；普通浏览器首次需点一下页面解锁自动播放，OBS 浏览器源无此限制；
- OBS 里：浏览器源勾选「控制音频」并路由到独立音轨 → 「你的声音」与「AI 语音（桌面音频）」可分开调音量/静音；
- 手机在 AI 说话时会短暂静音上行（`audio.js` 的 gate），避免把 AI 的声音再采回去；
- 观看端可用 `{"t":"audio","on":0|1}` 关闭/开启这条回放（默认开）。

## 八、哼唱 / 翻唱也上手机

`func/meowsinger/singerplayer.py` 原先用独立播放器（绕过 TTS 播放队列，所以手机永远听不到），现加了镜像：

- `play_audio()`（RVC 输出 numpy）→ 直接转单声道 int16 PCM 推送；
- `play_file()`（点歌 mp3/wav）→ 线程内 `soundfile` 解码后推送（不阻塞本地播放）；
- 按 **1x 实时速率**推送：先快送约 1 秒做抖动缓冲，之后每 0.25 秒一块，不会把整首歌一次性塞给手机；
- 来源标记 `source=hum` → **只在通话模式下到手机**（聊天模式按规则过滤，`/debug` 能看到 `keep=0`）；
- `stop()` 同时停掉本地播放与镜像。

## 九、对主项目的最小改动（均在既有桥接文件中）

| 文件 | 改动 |
|---|---|
| `func/pipeline/tts_phone.py` | `start_stream` 多带 `source`/`seg_index`；发送线程改单队列严格保序；不可达时打一次告警日志 |
| `func/tts/tts_core.py` | `_play_worker` 把该段文本传给 `_play_stream_source`；`_play_stream_source` 增加"旁路镜像给手机"（本地 mpv 不可用时自动回退为纯手机播放）；`_play_stream_phone` 补 `source`/`seg_index`；镜像时打一行 `[TTS->phone]` 便于排查；**手机对话的回复默认也本地播放**（新开关 `tts.gpt-sovits.phone_local_play`，见下） |
| `func/meowsinger/singerplayer.py` | 新增手机镜像（`source=hum`），本地播放与手机推送并行 |
| `config.yml` | `tts.gpt-sovits` 下新增 `phone_local_play: true` |

### 开关：手机对话的回复是否也本地播放

```yaml
tts:
  gpt-sovits:
    phone_local_play: true    # 默认 true
```
- `true`（默认）：手机对话的回复**电脑本地也播**（走 mpv → 桌面音频 → OBS 能采到），同时照旧推给手机 → 直播间能听到 AI 的回话；
- `false`：回到旧行为，**只推手机、电脑不播**（人在室内不想双声、或担心电脑麦克风把 AI 的话再识别时用）；
- 改动只影响 `source=phone`（手机语音 / 手机打字）；其它来源一直是"本地 + 手机都放"。
- ⚠️ 开启后电脑会出声，若 `config.yml` 里 `audio.sources.mic.enabled: true`，电脑麦克风可能把 AI 的话再收进去 → 建议不用电脑麦时关掉它，或戴耳机。

其余主项目代码（`llm_active` / `api.py` / `config.yml`）**完全未改**。



## 启动

在项目根目录 `D:\.Meowlisis` 下：

```bat
runtime\python.exe .phone\serve.py
```

首次启动会自动生成自签名证书到 `.phone/cert/`。也可从主 GUI 的「接口」球启动。

## 访问

1. 手机与电脑连**同一局域网**（或同一 Tailscale 网络）。
2. 手机浏览器打开：

```
https://<电脑IP>:8443
```

3. 首次会提示「连接不是私密连接」，点 **高级 → 继续前往**（Android）或 **显示详细信息 → 访问此网站**（iOS）。**只需要授权这一次**（WebSocket 与页面同端口同证书，不会再弹）。
4. 电脑观看端：浏览器打开 `https://<电脑IP>:8443/cam`（同样点一次继续前往）。

### 局域网 / Tailscale

- 服务监听 `0.0.0.0:8443`，**局域网 IP 与 Tailscale IP 均可直接访问**，无需额外动作（Tailscale 只是多一张网卡）。
- 流量可控：视频码率固定 2 Mbps（720p30），可在 `config.py` 调整 `VIDEO_BITRATE / VIDEO_FPS / VIDEO_WIDTH / VIDEO_HEIGHT`；音频上行约为原生采样率 int16（≈96 KB/s），VAD 只在说话段与判停时上行。

## 使用

- **📷 摄像头球**：点一下开、再点一下关。开=整屏实时画面；关=黑屏。
- **⇄ 顶部小键**：切换前后摄像头（**默认后置 / 外界**，点一下切到前置）。
- **🎤 麦克风球**：点一下开麦（连续采集，直到再点一下关闭）。开麦后说话内容走主项目 SenseVoice 识别（受主项目声纹设置约束）。
- **💬 消息球**：打开输入框，输入并回车/发送，走 `/chat`（`source=phone`，回复语音同样回手机播放）。
- **顶部胶囊「聊天 / 通话」**：切换模式。通话模式下手机能听到主项目合成的**全部**语音（电脑端同时照常播放）。
- **昵称**：左上角「我是 …」点击可改，保存在本机浏览器 localStorage。
- **桌宠**：默认约为屏幕高度的 13%，**两指捏合可缩放（限制 0.35×~2.5×，不能无限放大）**，单指可拖动，双击回中。
- **气泡**：当前说话（识别字幕）与**手机相关**的 AI 回复以气泡贴在桌宠上方显示（AI 文本来自手机专属 TTS 通道，不含本地麦/弹幕/工具箱的回复）。
- **AI 语音**：进页面后**任意处点一下**即可解锁音频播放（iOS 要求用户手势），之后 AI 语音持续从手机播放。

## 目录结构

```
.phone/
├── serve.py            # HTTPS 服务 + /ws 接管 + 反向代理 + 证书生成
├── config.py           # 端口 / 音视频参数（读取主项目 config.yml 覆盖音频参数）
├── ws_hub.py           # 同端口 WebSocket（握手/分帧/角色/视频路由/GOP/关键帧请求）
├── audio_gateway.py    # 上行音频重采样 + 能量 VAD + 转发 /audio/send、/audio/end
├── tts_relay.py        # 手机 TTS PCM 中继（单调 seq + meta 延迟回收）
├── static/
│   ├── index.html      # 手机端
│   ├── cam.html        # 电脑观看端
│   ├── css/phone.css
│   ├── css/cam.css
│   └── js/
│       ├── main.js     # 手机端装配
│       ├── ws.js       # WebSocket 客户端（自动重连）
│       ├── camera.js   # 摄像头 + WebCodecs H.264 编码
│       ├── audio.js    # 麦克风采集
│       ├── pcm-worklet.js
│       ├── player.js   # AI 语音播放（单调时间线）
│       ├── chat.js     # 文字对话与轮询
│       ├── mode.js     # 聊天/通话模式切换
│       ├── say.js      # 底部一行小字（用户输入/识别结果）
│       ├── monaudio.js # 观看端播放手机声音（/cam 用）
│       ├── bubble.js   # 气泡（贴桌宠）
│       └── viewer.js   # 电脑端解码显示
└── cert/               # 自签名证书（首次启动自动生成）
```

## 常见问题

- **摄像头/麦克风无法授权**：必须用 `https://` 访问并点过「继续前往」；iOS 还需在「设置 → Safari → 摄像头/麦克风」允许。
- **手机端没有画面（观看端一直「等待手机画面」）**：确认手机页已点过 📷 且未被系统降级；iOS 需 **Safari 16.4+**（WebCodecs）。
- **开麦后 AI 没反应**：确认主项目 `api.py` 已启动、`inject` 源已启用、SenseVoice 已启动；识别结果还受主项目 `target_speakers` 声纹过滤。
- **手机听不到 AI 声音**：进页面后先在屏幕上点一下Anywhere解锁播放器。
- **端口被占用**：改 `config.py` 的 `HTTPS_PORT`。
