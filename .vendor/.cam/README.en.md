# Meow Phone Interface (.cam)

> [中文](README.md) | English

A standalone phone client plus a desktop viewer. Open the page in a phone browser and you get: **the phone camera filling the screen**, the desktop pet floating on top, speech/replies shown as bubbles attached to the pet, and three button balls at the bottom (camera / microphone / messages). The main project is **untouched** — everything bridges into `api.py` through the existing HTTP endpoints.

Code location: `.vendor/.cam/` (formerly `.phone/`; moved wholesale into `.vendor/` and renamed).

## How It Works

- `.vendor/.cam/serve.py` starts an HTTPS server (**single port 8443**, self-signed certificate):
  - Serves the phone page from `static/` (`/`), the desktop viewer page (`/cam`), and the audio diagnostics page (`/debug`)
  - Exposes `.vendor/.desktopet` as `/pet/` so the phone page can load the pet in an iframe (same origin, avoiding mixed content)
  - Handles the WebSocket (`/ws`) on **the same port with the same certificate**: the phone sends video/audio up, the desktop receives video down. No second port, no second certificate approval.
  - Reverse-proxies to the main program's `api.py` (127.0.0.1:1800): `/chat`, `/msg`, `/say`, `/audio/send`, `/audio/end`, `/mic`, `/chatreply`, `/phone/audio`, `/tts/audio`
  - Receives phone-side TTS PCM pushed by the main program (`/api/tts/phone`), which the phone polls and plays (`/api/tts/pending`)
  - `/api/who` forwards to the config GUI's (127.0.0.1:1801) identity endpoint, turning a uid into a nickname for the phone page

## 1. Camera (Phone → Desktop)

1. On the phone, `getUserMedia` grabs the camera (default **rear / outward-facing**; the tiny ⇄ at the top right switches front/rear; requests 1280×720 at ≤30fps).
2. The phone encodes with **WebCodecs `VideoEncoder` (H.264 / avc1.42E01E, preferring hardware encoding)**, emits Annex-B, `latencyMode=realtime`, and forces a keyframe every **2 seconds**.
3. Encoded chunks go up as `/ws` binary frames (`[0x01][flags][ts_us u64][h264]`).
4. On the `.cam` side, `ws_hub` caches the latest GOP and forwards it to all viewers; a new viewer gets the latest keyframe immediately on connect, so it opens instantly. The GOP cache is only a small emergency buffer (`VIDEO_GOP_MAX`) — viewers mostly fetch a fresh keyframe themselves via `reqkey`.
5. On the desktop, open `https://<computer-IP>:8443/cam`: WebCodecs `VideoDecoder` decodes → canvas playback, with a minimal **REC frame** (red REC dot + corner brackets + status/fps).
6. Turning the camera off calls `track.stop()` to release the device (saves power), and viewers show "phone camera is off".

> **Size and orientation follow the actual video frame**: the phone encodes frames taken **straight from the `<video>` element** (`new VideoFrame(video)` — no canvas redraw, no scaling), and the preview is that same `<video>`, so "what you see on the phone is what the desktop gets" — no flipped or stretched output. But `VideoFrame(video)` gives you the **raw decoded frame without the rotation applied at render time** (a portrait camera's raw frame is landscape, while `videoWidth/Height` are post-rotation), so every stream does a one-time **geometry self-check**: if the raw frame size doesn't match the display size it automatically falls back to normalized canvas encoding (`drawImage` renders the post-render picture, rotation included) so nothing is distorted; if they match it takes the direct fast path. Encode size comes from `video.videoWidth/videoHeight` (a cached property, so `track.getSettings()` isn't called every frame — on iOS it can also return sensor dimensions); the viewer derives canvas size and display ratio from the decoded `VideoFrame.displayWidth/displayHeight`, scales to fit the window keeping aspect ratio, and rebuilds encoder and decoder automatically when the device rotates or the camera flips mid-stream.

> Frontend static assets are served with `Cache-Control: no-store, must-revalidate` (phone page, viewer page, and OBS page alike), so edits take effect on refresh and the browser won't cling to an old version.

> Note: by request there is no fallback (devices without WebCodecs H.264 support simply get an "unavailable" message).

### Backpressure

- `VIDEO_ENC_MAX_QUEUE`: encoder/send queue cap; frames are dropped once exceeded (the first layer of smart frame dropping);
- `AUDIO_SEPARATE_SOCKET`: on the phone, audio and video use **two separate WS connections**, so audio is never held up by video backlog.

### Self-Healing After Screen Lock / Backgrounding / Process Kill

When the phone screen locks, the browser is backgrounded, or the process is killed by the system, the browser freezes timers and drops the connection without sending a FIN, which easily leaves three kinds of stale state behind.
All three now self-heal — **under normal conditions you never need to restart a process or refresh a page**:

| Area | What used to happen | What happens now |
|---|---|---|
| Phone playback `player.js` | `_lastSeq` stayed at its old position, so coming back replayed speech from tens of seconds ago; `_nextStart` hung in the future → `isPlaying()` stayed true for ages → **the mic was held shut by the gate** | `resync()` on foreground return / `pageshow` / WS reconnect: `_firstBatch` realigns to the newest, timeline resets to zero; `_poll()` gained a watchdog that resets when it is "more than 4 seconds ahead"; polling stops while the page is hidden |
| Relay `tts_relay.py` | Trimmed only by block count/bytes, so **after a minute away the phone still played a minute-old sentence** | Every block carries its write time; anything older than `TTS_MAX_AGE_SECS` (3 seconds by default) is dropped outright; `TTS_MAX_BLOCKS` lowered to 120 to bound memory |
| Connection `ws_hub.py` | Never pinged, so half-open connections blocked read threads forever and connections/threads only ever grew → weirder and weirder until the service was restarted | Sends a protocol-level ping after 15 seconds idle (the browser pongs automatically), and reclaims the connection if not a single frame arrives for 60 seconds; when a phone connection is reclaimed it tells `audio_gateway` to flush the uplink residue, so half of the previous sentence doesn't get glued onto the next one |

Fallback: open in a browser, or `curl -k https://<IP>:8443/api/reset`, to flush the relay buffer plus uplink residue without restarting `serve.py`.

## 2. Microphone (Phone → Main Project SenseVoice)

1. Tap 🎤 on the phone to unmute: `getUserMedia` audio → `AudioWorklet` → **int16 mono PCM at native sample rate** → `/ws` uplink (`[0x02][pcm]`).
2. On the `.cam` side, `audio_gateway` **stream-resamples the native rate down to 16k mono** (`samplerate`, `sinc_medium`, matching the main project).
3. It replicates the main project's `InterruptDetector` **energy VAD** to cut the continuous stream into utterances:
   - While speaking: batched `POST /audio/send?username=<nickname>`
   - At utterance end (silence reaches threshold / utterance exceeds 30s / stream drops): `POST /audio/end`
   - `AUDIO_SEND_BATCH_SECS`: batches 30ms frames before POSTing, cutting request count and surviving timeouts.
4. That way the main project's `inject` source sees exactly the same utterance boundaries as push-to-talk, which is the only way recognized text reaches the LLM.

Capture parameters are **overridden** by the main project's `config.yml` (`config.py::apply_project_config()`, read once at startup):

| Constant here | Read from main project config.yml | Default |
|---|---|---|
| `AUDIO_TARGET_RATE` | `audio.rate` | 16000 |
| `AUDIO_RESAMPLE_CONVERTER` | `audio.resample_converter` | `sinc_medium` |
| `AUDIO_FRAME_BYTES` | `audio.chunk_size_ms` → `sensevoice.chunk_size_ms` (clamped to 20~100ms) | 960 |
| `AUDIO_ENERGY_THRESHOLD` | `sensevoice.vad_energy_threshold` | 300.0 |
| `AUDIO_SILENCE_SECS` | `sensevoice.silence_threshold` | 2.0 |

> You need to **enable the main project's inject source** on the desktop (`config.yml → sensevoice.sources.inject.enabled: true`, already true by default).

## 3. Synthesized Speech Back to the Phone (Playback Fixes)

Synthesized audio for the main project's `source=="phone"` (phone speech + phone typing) is pushed to `/api/tts/phone`, and the phone polls `/api/tts/pending` to play it.

Fixed: out-of-order playback / overlapping playback / dropped tails:

- Server `tts_relay.py`: a globally monotonic PCM `seq`; filtering by **mode + source**; meta isn't cleared immediately after `end` (reclaimed after `TTS_META_HOLD_SECS` seconds); oversized blocks are split, and a single pull has both a **count and a byte** cap (`TTS_PENDING_LIMIT` / `TTS_MAX_PENDING_BYTES`, `TTS_MAX_BLOCK_BYTES`) so long audio can't blow up the phone.
- Phone `player.js`: polling is **single-flight**; the `_nextStart` timeline **only moves forward and never rewinds**; scheduling strictly follows increasing `seq`.
- Main project `func/pipeline/tts_phone.py`: the send thread is now a **single strictly ordered queue** (start always precedes its data blocks, end always follows them), fixing the inherent race where "the first block of each stream could precede start" (which broke source filtering / picked the wrong sample rate / lost the tail blocks).

### AI Bubbles Only Show "Phone-Related" Replies

- `/api/chatreply` reads the main project's `ReplyTextList`, and the main project's `SubtitleWorker` stuffs TTS subtitles from **every source** into it, so it is **no longer used** for bubbles.
- AI bubbles are now driven by **`meta.text` pushed on `/api/tts/phone`** — in chat mode that channel carries only `source=="phone"`, in call mode it carries every source, so it naturally matches the mode.
- User bubbles come from phone typing (`/chat`) and phone speech recognition subtitles (`/api/phone/audio`).

## 4. Call Mode / Chat Mode

Toggled by the pill button at the top of the phone (`GET/POST /api/mode?mode=chat|call`). The mode is **persisted** to `.vendor/.cam/mode.txt` and survives a service restart (the startup log also prints the current mode).

**The default is call mode** (`config.py → DEFAULT_MODE = 'call'`).

| | Chat mode | Call mode (default) |
|---|---|---|
| What the phone hears | Only replies the phone itself initiated (speaking / typing) | **Everything the main project synthesizes** (local mic, danmaku, toolbox, proactive replies, screen-watch speech, humming…) |
| Phone bubbles | Only phone-related replies | All synthesized text |
| Desktop | Plays as usual | Plays as usual (the main project cannot be muted) |

Implementation: the PCM the main project's playback thread emits locally is **tapped off as a copy** to `.cam` (with `source` attached), and `.cam`'s `tts_relay` decides "keep or drop" based on the current mode. Therefore:

- In call mode the desktop and the phone hear **the same PCM** (sample-for-sample identical); the phone lags by only about 0.4s;
- **No duplication**: `source=phone` takes the native channel and everything else takes the bypass; the two paths are mutually exclusive in `.cam`'s playback thread;
- **Zero extra synthesis cost** (nothing is synthesized twice).

Companion: while "AI audio is playing", the phone **pauses mic uplink** (`audio.js`'s gate; restored 150ms after playback ends) so the phone's own speaker output isn't picked up by its mic and then treated by the main project as the user speaking, which would create a **self-conversation loop**. Disable it with `config.py → AUDIO_MIC_GATE` (and let iOS echo cancellation handle it).

## 5. OBS / Tailscale / Troubleshooting

**OBS browser source (desktop cam view)**: use the **plain HTTP** address, not HTTPS (OBS's browser core rejects self-signed certificates and shows a blank screen):

```
http://127.0.0.1:8445/cam
```

That port also serves `/cam`, `/static/*`, and **`ws://127.0.0.1:8445/ws`** (the page derives it from `location`, same port as HTTP, so it sidesteps the certificate problem); the pet page is on the same port too: `http://127.0.0.1:8445/pet/renderer/index.html` (you can add `?autofit=1&fit=0.13`).

> After changing frontend files you **must restart `.vendor/.cam/serve.py`**, and make sure no old process still holds 8443/8445 (it will keep serving the old code on that port).

**Tailscale**: the server listens on `0.0.0.0`, so point the phone at the Tailscale address, `https://<100.x.x.x>:8443` (or the MagicDNS name `https://<machine>.<tailnet>.ts.net:8443`); you still tap "proceed" once to accept the self-signed certificate. Camera/microphone need a secure context, and HTTPS satisfies that once the certificate is accepted.
To get rid of the certificate warning entirely: overwrite `.vendor/.cam/cert/cert.pem` and `key.pem` with a certificate issued by `tailscale cert <name>.ts.net` (if present they are reused and never regenerated).

**No audio / wrong audio**: open the diagnostics page in a browser (auto-refreshes every second):

```
https://<IP>:8443/debug
```

Or fetch the JSON directly: `https://<IP>:8443/api/tts/debug`

```json
{"mode":"call","buffered_blocks":1,"buffered_bytes":300,
 "meta":{"source":"phone","text":"…","seg_index":1,"sample_rate":32000},
 "log":[{"source":"toolbox_danmaku","kept":false,"bytes":500},
        {"source":"phone","kept":true,"bytes":300}]}
```
`kept:false` = that source was filtered out in the current mode (chat mode keeps only `phone`).

**Same-turn follow rule**: if the first segment of a `traceid` is kept, **all of its later segments are kept too** (even if they carry a different source tag), which avoids "only the first sentence arrives". The record is cleared when the mode changes, and expires after 90 seconds of inactivity.

**Note**: chat mode is **strictly** limited to conversations the phone itself initiated (`source=phone` plus its same-turn segments); there is no whitelist of any kind. To hear all speech, switch to **call** mode (which is the default). On switching, a one-line notice with the current mode appears at the bottom of the phone; the mode is persisted to `.vendor/.cam/mode.txt`.

## 6. UI Conventions

- Bubbles **show only AI replies**, white background with dark text, **auto-width** (short content stays short, never wider than the screen, wrapping when it overflows).
- User input (phone typing + speech recognition results) **never goes into a bubble**; it shows as one small line at the bottom (fades out after 6 seconds).
- Top pill: `通话·全部` (Call · All) / `聊天·仅我` (Chat · Only Me);
- Top left `🔊/🔇` + volume slider: volume for AI speech played on the phone (remembered in localStorage, survives a refresh);
- Top right mini ⇄: front/rear camera switch.
- After opening for the first time or refreshing you **must tap the screen once** before there is sound (browser autoplay policy); until it's unlocked the bottom shows "tap the screen to enable sound".

## 7. Phone Audio Back to the Viewer (So the Stream Can Hear You)

- While 🎤 is on, uplink audio goes **one way to SenseVoice for recognition and another way forwarded as-is** to all viewers (WS binary `0x03` frames: `[0x03][rate u32 BE][s16le mono]`);
- The `/cam` page plays it automatically (top-right `🔊/🔇` toggle + volume slider; both mute state and volume are remembered in localStorage); a normal browser needs one tap to unlock autoplay the first time, while the OBS browser source has no such restriction;
- In OBS: tick "Control audio via OBS" on the browser source and route it to its own track → "your voice" and "AI speech (desktop audio)" can be leveled/muted separately;
- The phone briefly mutes uplink while AI is speaking (`audio.js`'s gate), so the AI's voice isn't captured again;
- Viewers can turn this playback off/on with `{"t":"audio","on":0|1}` (on by default).

## 8. Humming / Covers Reach the Phone Too

`func/meowsinger/singerplayer.py` used a separate player (bypassing the TTS playback queue, so the phone never heard it); it now has a mirror:

- `play_audio()` (RVC numpy output) → converted straight to mono int16 PCM and pushed;
- `play_file()` (requested-song mp3/wav) → decoded with `soundfile` on the thread, then pushed (without blocking local playback);
- Pushed at **1x realtime**: about 1 second is sent ahead as a jitter buffer, then one chunk every 0.25 seconds, so the whole song isn't dumped on the phone at once;
- Source tag `source=hum` → **reaches the phone only in call mode** (chat mode filters it by rule; `/debug` shows `keep=0`);
- `stop()` stops both local playback and the mirror.

## 9. Minimal Changes to the Main Project (All in Existing Bridge Files)

| File | Change |
|---|---|
| `func/pipeline/tts_phone.py` | `start_stream` now carries `source`/`seg_index`; the send thread became a single strictly ordered queue; logs one warning when the endpoint is unreachable |
| `func/tts/tts_core.py` | `_play_worker` passes the segment text to `_play_stream_source`; `_play_stream_source` gained a "mirror to the phone" side path (falls back to phone-only playback when local mpv is unavailable); `_play_stream_phone` now passes `source`/`seg_index`; the mirror logs a `[TTS->phone]` line for debugging; **replies to phone conversations also play locally by default** (new switch `tts.gpt-sovits.phone_local_play`, see below) |
| `func/meowsinger/singerplayer.py` | New phone mirror (`source=hum`); local playback and phone push run in parallel |
| `config.yml` | `phone_local_play: true` added under `tts.gpt-sovits` |

### Switch: Do Phone-Conversation Replies Also Play Locally?

```yaml
tts:
  gpt-sovits:
    phone_local_play: true    # true by default
```
- `true` (default): replies to phone conversations **also play locally on the desktop** (through mpv → desktop audio → OBS can capture it) while still being pushed to the phone → the stream hears the AI's side of the conversation;
- `false`: back to the old behavior — **pushed to the phone only, nothing plays on the desktop** (for when you're indoors and don't want double audio, or when you're worried the desktop mic will pick up and re-recognize the AI's speech);
- The change affects only `source=phone` (phone speech / phone typing); other sources have always played "both locally and on the phone".
- ⚠️ With this on the desktop makes sound, so if `config.yml` has `audio.sources.mic.enabled: true`, the desktop mic may pick the AI's speech back up → turn that off when you're not using the desktop mic, or wear headphones.

The rest of the main project code (`llm_active` / `api.py` / `config.yml`) is **completely unchanged**.

## Starting

From the project root, `D:\.Meowlisis`:

```bat
runtime\python.exe .vendor\cam\serve.py
```

The first start generates a self-signed certificate into `.vendor/.cam/cert/`. You can also start it from the 接口 ("Interfaces") ball in the main GUI.

## Access

1. Put the phone and the desktop on the **same LAN** (or the same Tailscale network).
2. Open this in the phone browser:

```
https://<computer-IP>:8443
```

3. The first time you'll see "Your connection is not private"; tap **Advanced → Proceed** (Android) or **Show Details → Visit this website** (iOS). **You only have to authorize once** (the WebSocket shares the page's port and certificate, so it won't prompt again).
4. Desktop viewer: open `https://<computer-IP>:8443/cam` in a browser (again, proceed once).
5. Audio diagnostics page: `https://<computer-IP>:8443/debug`.

### LAN / Tailscale

- The server listens on `0.0.0.0:8443`, so **both the LAN IP and the Tailscale IP work directly** with no extra steps (Tailscale is just one more network interface).
- Traffic is bounded: video is fixed at 2 Mbps (720p30), see `VIDEO_BITRATE / VIDEO_FPS / VIDEO_WIDTH / VIDEO_HEIGHT` in `config.py`; audio uplink is roughly native-rate int16 (≈96 KB/s), and the VAD only sends upstream during speech segments and at the stop decision.

## Usage

- **📷 camera ball**: tap to turn on, tap again to turn off. On = live full-screen picture; off = black screen.
- **⇄ top key**: switches front/rear camera (**rear / outward-facing by default**; one tap goes to the front camera).
- **🎤 microphone ball**: tap to unmute (continuous capture until you tap again to stop). While unmuted, speech goes through the main project's SenseVoice recognition (subject to the main project's voiceprint settings).
- **💬 message ball**: opens a text box; type and press Enter/send to go through `/chat` (`source=phone`, and the spoken reply comes back to the phone the same way).
- **Top pill "Call / Chat"**: switches mode. In call mode (the default) the phone hears **all** of the main project's synthesized speech (the desktop keeps playing as usual at the same time).
- **Nickname**: the "I am …" label at the top left is tappable and editable, stored in this browser's localStorage; uid → nickname goes through `/api/who`.
- **Desktop pet**: about 13% of screen height by default, **pinch with two fingers to scale (clamped to 0.35×~2.5×, no infinite zoom)**, drag with one finger, double-tap to recenter.
- **Bubbles**: the current speech (recognition subtitles) and **phone-related** AI replies appear as bubbles above the pet (the AI text comes from the phone-only TTS channel and excludes local-mic/danmaku/toolbox replies).
- **AI speech**: after entering the page, **tap anywhere once** to unlock audio playback (iOS requires a user gesture); AI speech then plays from the phone continuously.

## Directory Layout

```
.vendor/.cam/
├── serve.py            # HTTPS server + /ws handling + reverse proxy + certificate generation
├── config.py           # Port / A/V parameters (audio params overridden by the main project's config.yml at startup)
├── ws_hub.py           # Same-port WebSocket (handshake/framing/roles/video routing/GOP/keyframe requests)
├── audio_gateway.py    # Uplink audio resampling + energy VAD + forwarding to /audio/send, /audio/end
├── tts_relay.py        # Phone TTS PCM relay (monotonic seq + delayed meta reclaim + mode filtering)
├── mode.txt            # Persisted current mode (call / chat)
├── static/
│   ├── index.html      # Phone client
│   ├── cam.html        # Desktop viewer
│   ├── debug.html      # Audio diagnostics page
│   ├── css/
│   │   ├── phone.css
│   │   ├── cam.css
│   │   └── debug.css
│   └── js/
│       ├── main.js     # Phone client wiring
│       ├── config.js   # Frontend constants (endpoint paths / storage keys)
│       ├── ws.js       # WebSocket client (auto-reconnect)
│       ├── camera.js   # Camera + WebCodecs H.264 encoding
│       ├── audio.js    # Microphone capture
│       ├── pcm-worklet.js
│       ├── player.js   # AI speech playback (monotonic timeline)
│       ├── chat.js     # Text conversation and polling
│       ├── mode.js     # Chat/call mode switch
│       ├── say.js      # Bottom one-liner (user input / recognition results)
│       ├── monaudio.js # Viewer-side phone audio playback (used by /cam)
│       ├── bubble.js   # Bubbles (attached to the pet)
│       ├── viewer.js   # Desktop decode and display
│       └── debug.js    # Diagnostics page
└── cert/               # Self-signed certificate (generated on first start)
```

## Endpoint Overview

| Method | Path | Description |
|---|---|---|
| GET | `/` | Phone home page |
| GET | `/cam` | Desktop viewer page |
| GET | `/debug` | Audio diagnostics page |
| GET | `/static/<p>` | Frontend static assets (`no-store`) |
| GET | `/pet/<p>` | Pet files (from `.vendor/.desktopet`) |
| GET/POST | `/api/chat` | Phone typing conversation (proxies `api.py`) |
| POST | `/api/msg` | Send a message |
| POST | `/api/say` | TTS repeat |
| POST | `/api/audio/send` `/api/audio/end` | Uplink audio chunks / end of utterance |
| GET | `/api/phone/audio` | Phone speech recognition subtitles |
| GET | `/api/chatreply` | Main project reply text (**no longer used for bubbles**) |
| GET/POST | `/api/tts/phone` `/api/tts/pending` | Phone TTS push / pull |
| GET/POST | `/api/mode` | Query / switch chat·call |
| GET | `/api/tts/debug` | Relay diagnostics JSON |
| GET/POST | `/api/reset` | Fallback: flush relay buffer and uplink residue (no process restart needed) |
| GET | `/api/who` | uid → nickname (forwards to the GUI 1801 identity endpoint) |

## FAQ

- **Camera/mic can't be authorized**: you must use `https://` and have tapped "proceed"; on iOS you also need to allow it in Settings → Safari → Camera/Microphone.
- **No picture on the phone (viewer stuck on "waiting for phone video")**: check that 📷 has been tapped on the phone page and that the system hasn't throttled it; iOS needs **Safari 16.4+** (WebCodecs).
- **AI doesn't react after unmuting**: make sure the main project's `api.py` is running, the `inject` source is enabled, and SenseVoice is running; recognition results are also filtered by the main project's `target_speakers` voiceprint.
- **No AI audio on the phone**: check the mode first — **the default is call mode** (hears everything); if you switched to chat mode it only hears what the phone itself initiated. Then confirm you tapped the screen once after entering the page to unlock the player.
- **Port already in use**: change `HTTPS_PORT` in `config.py` (the HTTP port used by OBS is `PET_HTTP_PORT`).
- **Frontend changes have no effect**: caching is already disabled, but you still need to **restart serve.py** and make sure no old process holds 8443/8445.
