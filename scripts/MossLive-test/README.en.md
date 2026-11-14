# scripts/MossLive-test — MOSS-Live full-duplex realtime test

> English | [中文](README.md)

A **standalone** playground for MOSS-Live 1.0. It does not start the main app, does not edit `config.yml`,
and does not write the app's runtime directories. It tries to get four things working for real:

- **Full-duplex voice** — 16 kHz PCM mic uplink, 48 kHz PCM playback, natural barge-in;
- **Live screen sharing** — `mss` grabs the screen continuously, scales/encodes JPEG frames, and streams them;
- **Tool calls** — the model calls local tools, this process executes them, results go back, the reply continues;
- **Project assets** — persona/instructions come straight from the project's character card and front prompt,
  and the voice is cloned from the project's reference audio.

Out of scope for this round (by request): short-term memory, long-term memory, and client delegation.

---

## Quick start

### 1. API key

Either set `api.api_key` in `config.json`, or export `MOSS_API_KEY` (change `api.api_key_env` if needed).
No key ships with this directory.

### 2. Offline checks first

```bat
:: from the project root
runtime\311\python.exe scripts\MossLive-test\mosslive_test.py --selftest
```

It checks prompt assembly, reference-audio preparation, screen capture, mic/speaker devices, and tools.
To inspect prompts/voice without touching devices or the network:

```bat
runtime\311\python.exe scripts\MossLive-test\mosslive_test.py --dry-run
```

### 3. Run

```bat
scripts\MossLive-test\run.bat

:: or
runtime\311\python.exe scripts\MossLive-test\mosslive_test.py
```

Things to try:

| Say | What it exercises |
|---|---|
| "Can you see my screen? What's on it?" | live screen frames + vision |
| "What time is it?" | sync tool `get_time` |
| "Find MossLiveSession in the project" | async tool `search_files` |
| "Open https://example.com" | `open_url` side effect |
| "Switch to the browser" | `activate_window` |
| Talk over the assistant | barge-in → `playback.stopped` |

---

## Layout

```
scripts/MossLive-test/
├─ mosslive_test.py     entry point (args, dry-run, selftest, session)
├─ config.json          real config (needs a key)
├─ mock_config.json     config for the local fake server
├─ mock_server.py       fake MOSS-Live server for protocol regression
├─ run.bat              double-click launcher (runtime\311\python.exe)
├─ mosslive/
│  ├─ config.py         config merge/validate, project vs. test path resolution
│  ├─ prompt.py         builds persona / instructions from project files
│  ├─ voice.py          reference audio → cloned voice → cache
│  ├─ audio.py          mic capture + playback queue + playback receipts
│  ├─ screen.py         mss live screen capture → JPEG frames
│  ├─ tools.py          tool definitions and execution
│  ├─ session.py        MOSS-Live protocol loop
│  └─ console.py        terminal output + sessions/*.jsonl transcript
└─ sessions/ notes/ frames/ voice_cache.json   (generated, gitignored)
```

---

## Data flow

```
mic 16 kHz PCM16 ──(0x00 prefix)──┐
screen JPEG (mss) ──(0x02 prefix)─┤──> wss://api.mosi.cn/v1/realtime
                                  │
text events <─────────────────────┤
48 kHz PCM16 ──> playback queue ──> speaker
  each chunk played ──> playback.chunk.completed
  whole reply played ──> playback.completed
  stopped ──> playback.stopped + played_audio_ms
```

Handshake order: `attach_session` → `change_voice` → `session.update` → `media.mode` → `media.configure`.
Only after `media.configured` does it start sending audio/frames and emit `client_context.update`,
`video.state`, and `mic_state`.

---

## Configuration

Two path bases:

- **Project-relative** (`prompt.*`, `voice.ref_audio.*`): relative to the repo root, may point anywhere in the project;
- **Test-relative** (`voice.clone.cache_file`, `tools.notes_file`, `log.sessions_dir`, `screen.frames_dir`): relative to this folder.

### api

| Key | Meaning |
|---|---|
| `realtime_url` | `wss://api.mosi.cn/v1/realtime` |
| `http_base` | `https://api.mosi.cn` (voice cloning) |
| `api_key` / `api_key_env` | key or env var name |
| `model` | `moss-live-1.0` or a snapshot ID |
| `user` | stable end-user ID, URL-encoded into the query |
| `proxy` | `null` for direct, or an HTTP proxy URL |

### session

| Key | Meaning |
|---|---|
| `memory_scope` | `session` (no memory in this test) |
| `playback` | `client` (real progress receipts) or `server` |
| `profile` | `standard` (16k up / 48k down) or `low` |
| `output_audio` / `input_audio` | only `pcm16` is implemented downstream |
| `video` | requested frame params; `media.configured.video` wins |
| `time_zone` | device time zone sent to the model |
| `location` | optional `{latitude, longitude}` |

### prompt

| Key | Meaning |
|---|---|
| `mode` | `project` (card + front prompt + values) / `files` / `inline` |
| `persona_name` | blank → card name |
| `persona_inline` | persona text for `mode=inline` |
| `display_name` | replaces `{display_name(uid)}` in the front prompt |
| `card_file` | blank → `character_card.card_file` from `config.yml` |
| `include_front_prompt` | include `character/front/prompt.json#prompt` |
| `include_active_prompt` | also include `prompt_active` (off by default) |
| `include_values` | include `character/info/values/latest.json` |
| `extra_sources` | append any project file to persona/instructions |
| `instructions` / `instructions_files` | extra session instructions |
| `max_persona_chars` | 8000 (truncated with a warning) |
| `max_instructions_chars` | 16000 |

`extra_sources` example:

```json
"extra_sources": [
  {
    "path": "工作流程解析/docs/some-notes.md",
    "label": "Project notes",
    "target": "instructions"
  },
  {
    "path": "character/front/armor-piercing-prompt.json",
    "json_key": "prompt",
    "label": "Armor prompt",
    "target": "instructions"
  }
]
```

### voice

| Key | Meaning |
|---|---|
| `mode` | `clone` (default) / `name` / `default` |
| `name` | voice ID for `mode=name` |
| `fallback_name` | built-in voice used if cloning is unavailable |
| `ref_audio.source` | `character/ref_audio/config.json` |
| `ref_audio.character` / `emotion` | which character/emotion sample to use |
| `ref_audio.file` | explicit wav, overrides `source` |
| `clone.voice_name` | name on the platform |
| `clone.cache_file` | clone cache, `voice_cache.json` |
| `clone.recreate` | force a fresh clone |
| `clone.max_seconds` | trim limit, 29 s (API: 30 s / 10 MB) |

Flow: read reference audio → mono 16-bit WAV trimmed to 29 s → `POST /v1/audio/voices`
(multipart `audio_sample`) → use the returned `id` in `change_voice` → cache it by file fingerprint.

### audio

| Key | Meaning |
|---|---|
| `input_device` / `output_device` | PyAudio indices, `-1` = system default (`--list-devices`) |
| `input_rate` / `output_rate` | desired rates; fallback + local resampling if unsupported |
| `frame_ms` | uplink frame size, 20 ms |
| `input_enabled` | disable capturing |
| `output_enabled` | disable local playback (receipts are still paced) |
| `volume` | playback gain |

### screen

| Key | Meaning |
|---|---|
| `enabled` | stream screen or not |
| `monitor` | mss monitor: 0 = all, 1 = primary, 2 = second |
| `region` | `{left, top, width, height}`, takes priority |
| `interval_ms` | 200–10000, default 1000 |
| `max_long_side` | 128–1920, default 512 |
| `jpeg_quality` | 0.1–1, default 0.75 |
| `save_frames` | debug: save every 30th frame to `frames/` |

### tools / log

`tools.enabled` selects tools (order is preserved); `search_root`, `search_max_results`, `notes_file` tune them.
`log.level` is `DEBUG|INFO|WARN|ERROR`; `save_events` writes `sessions/*.jsonl`; `verbose_events` prints raw events;
`show_partial` shows streaming transcripts.

---

## How the screen is streamed

- `tagged-v1`: audio `0x00 + PCM`, screen `0x02 + JPEG`, sharing the same WebSocket.
- One JPEG per binary message — never Base64, MP4, or H.264. Capture/scale/encode run in a worker thread,
  so the WebSocket loop is never blocked.
- Frame parameters follow `media.configured.video` (the server may change interval/size/quality).
- `mss` is much faster than `ImageGrab`. One frame per second is plenty; higher rates burn bandwidth and context.
- Screen content is uploaded to the cloud model as-is: keep meetings, chats, and password managers off the shared screen.

---

## Tools

| Tool | Type | Purpose | Side effect |
|---|---|---|---|
| `get_time` | sync | current time/weekday/time zone | none |
| `open_url` | sync | open an http(s) URL | opens browser |
| `list_windows` | sync | list visible window titles | none |
| `activate_window` | sync | focus a window by title keyword | changes focus |
| `save_note` | sync | append a local note | writes `notes/notes.md` |
| `search_files` | async_query | search file names and text in the project | none |

`search_files` is `async_query`, so the user can keep talking while it runs.
Add/remove tools in `tools.enabled` and `mosslive/tools.py`; keep the list stable during a session.

---

## Where the prompt and voice come from

| Content | Source | Goes to |
|---|---|---|
| character card | `character/info/character_prompt/<card_file>.json` | persona |
| current personality/emotion | `.temp/latest_emotion.json` (read-only) | persona |
| values | `character/info/values/latest.json` | persona |
| front prompt | `character/front/prompt.json#prompt` | instructions |
| post prompt | `character/front/prompt.json#post_prompt` | end of persona |
| extra files | any project file listed in `prompt.extra_sources` | persona / instructions |
| reference audio | `character/ref_audio/config.json` → wav | cloned voice |

Nothing under `func.*` is imported: those builders depend on live singletons, log-file locks, and `.temp` state,
which is fragile outside the app. This test reads the same files and keeps the same field order.

---

## Offline protocol regression (no API key)

`mock_server.py` is a fake MOSS-Live endpoint; it validates timing and formats, not speech.

```bat
:: window 1
runtime\311\python.exe scripts\MossLive-test\mock_server.py

:: window 2
runtime\311\python.exe scripts\MossLive-test\mosslive_test.py --config scripts\MossLive-test\mock_config.json
```

It checks the Authorization header, handshake/config events, media settings, time zone, uplink audio frames,
screen JPEGs, playback receipts, tool round-trip, and `playback.stopped` after a barge-in.
The last line is `REPORT {...}`; an empty `fails` array means success, and the server exits 0.

---

## Troubleshooting

- **Missing API key** — set `api.api_key` or `MOSS_API_KEY`.
- **401/403** — invalid key or no MOSS-Live access.
- **`session.update` failed** — persona > 8000 chars, instructions > 16000, or an invalid tool schema.
- **Voice did not change** — cloning failed (see the error) and it fell back to `fallback_name` or the default voice.
- **No sound / no mic** — use `--list-devices`, set indices, rerun `--selftest`.
- **Assistant interrupts itself** — speaker echo. Use headphones or a virtual cable; `--no-mic` tests screen only.
- **`code=1006`** — abnormal disconnect; no auto-reconnect, just run it again.
- **Server asks for opus** — pcm16 playback is the only implementation; keep `output_audio.format=pcm16`.

## Limitations

- No memory of any kind; sessions don't share context.
- No client delegation / background agent.
- No automatic reconnect.
- pcm16 playback only (no opus/mp3 decoders).
- One screen source at a time.
- Tools are local test implementations, not the main app's toolbox.
- No AEC; speaker playback can be captured by the mic.
