# 🐾 CatPaws

> [中文](README.md) | English

An iPhone control service that lets the main project "see the phone screen with its eyes and operate the phone with its hands".

On the PC side it is a Python service (with a lightweight built-in agent: observe → decide → act → review); on the phone side it is a dual-target app derived from WDA.
For the protocol, coordinates, streaming and acceptance criteria see [docs/CW_IOS_SPEC.md](docs/CW_IOS_SPEC.md); for the overall plan see [docs/CW_PLAN.md](docs/CW_PLAN.md).

## Shape

```
iPhone
├── CatPawRunner   :8100  /cw/v1/*   touch/screenshot/OCR/element tree (derived from WebDriverAgent)
└── CatPaw app                       UI + camera + audio + ReplayKit screen streaming

Windows
├── go-ios tunnel/forward            127.0.0.1:8100 → phone (required on iOS 17)
├── CatPaws service   :18110         console + control API + agent + action + operation log
└── CatPaws relay     :18111         WS video relay (same binary frame format as .cam)
```

The AI's observation channels are only screenshots and OCR; the video stream is for humans to watch and never enters the model.

## Directories

```
CatPaws/
├── src/cw/                 PC service: protocol/driver/actions/agent/action/relay/frontend service
├── src/cw_script.py        the cw_script module injected into action scripts
├── actions/<action_id>/    one folder per action (manifest.json + *.py)
│   └── jump_jump/          jump-jump example (user script, unverified)
├── web/                    console: phone screen on the left, operation trace on the right
├── docs/                   CW_PLAN.md (plan) / CW_IOS_SPEC.md (iOS spec)
├── start.bat               start it (runtime shared with the main project, runtime/311)
├── env/models/             OCR models (OCR has moved to iOS Vision on the phone; keep or delete)
└── src/server/ src/screen/ old WDA-direct implementation (legacy, entry point replaced)
```

## Running (PC)

```bash
# Double-click start.bat on Windows, or:
runtime\311\python.exe .vendor\.CatPaws\src\cw\server.py

# Run the whole chain with a mock device when no phone is available:
runtime\311\python.exe .vendor\.CatPaws\src\cw\server.py --mock
```

Console: <http://127.0.0.1:18110>

* The runtime is shared with the main project at `<project root>/runtime/311/python.exe`; no need to install paddle separately.
* Config comes from the `catpaws:` section of the main project's `config.yml` (already pre-set); put the LLM `api_key` there.
* When the device is unreachable the service automatically degrades to mock and prints a notice in the console.

## Running (iOS)

Follow [docs/CW_IOS_SPEC.md](docs/CW_IOS_SPEC.md) to create the workspace on a Mac and implement both targets; for day-to-day use on Windows:

```bat
ios list
ios runwda --bundleid com.meowlisis.catpawrunner ^
           --testrunnerbundleid com.meowlisis.catpawrunner.xctrunner ^
           --xctestconfig CatPawRunnerTests.xctest
ios forward 8100 8100
```

## Three kinds of operations

| Class | Tool | Description |
|---|---|---|
| Observe | `cw_observe` | `mode=ocr` returns text + pixel boxes; `mode=image` returns a screenshot for a multimodal model |
| Single | `cw_single` | tap, long press, swipe, pinch, input, key press, launch app, wait |
| Sequence | `cw_sequence` | many steps in one request, executed serially on the device by `delay_ms` (default and minimum 90ms) |
| action | `cw_action` | spawns a subprocess to run the script in `actions/<id>/`; the script can only talk to the executor via `cw_script` |

The agent has three stages:

| Stage | Visible tools | Constraints |
|---|---|---|
| `running` | observe / single / sequence / action / ask_user / update_action | **creating new actions is forbidden**; only small fixes to unverified or updatable actions are allowed |
| `reflecting` | observe / write_action / update_action / ask_user | post-run review: distill a fixed procedure into an action |

Stages are enforced by code (the tool table is generated per stage + re-validated at execution time), not by prompts.

## action conventions

`actions/<id>/manifest.json`:

```json
{
  "id": "wechat_pay",
  "title": "WeChat payment",
  "scene": "complete a small payment on the WeChat pay/receive page",
  "status": "unverified",
  "updatable": false,
  "author": "ai",
  "version": 1,
  "entry": "main.py:run",
  "params": {"max_amount": 50},
  "steps": ["open the chat", "tap + and choose transfer", "enter the amount", "confirm"],
  "last_run": {"ok": false, "at": "", "elapsed_ms": 0}
}
```

| Rule | Behaviour |
|---|---|
| Create | only in `reflecting`; a new action is `unverified` and is not trial-run automatically |
| One successful run | automatically set to `verified` |
| `unverified` / `updatable` | the AI may make small changes (≤60 lines, existing files only); afterwards it goes back to `unverified` |
| `verified` and not updatable | failures are reported as-is; **no editing, no copying the file** |
| Static review | must pass `ast`, whitelisted imports only, `eval/exec/open/os/subprocess/socket` etc. forbidden |

Script API: `emit/tap/long_press/swipe/wait/observe/observe_texts/observe_image/ask/params/log/done/should_stop`.
Scripts have no network or tokens; every action goes through PC-side safeguards.

## Ports

| Port | Purpose |
|---|---|
| 18110 | console + control API (127.0.0.1 only) |
| 18111 | video relay WS (0.0.0.0 + token) |
| 8100 | phone-side CatPawRunner (forwarded via go-ios) |
| 8443 | `.cam` phone page (existing service, loaded in a WKWebView inside the phone app) |

## Safeguards

Out-of-range coordinates reject the whole batch, action interval ≥90ms, ≤20 steps per run of consecutive operations, ≤200 steps per chain, ≤15 minutes per chain, app allow/deny lists, second confirmation on sensitive words, three stop entry points (PC console / phone app / voice stop word), full operation log in `logs/catpaws_ops/`.

## Integration with the main project

`func/catpaws/`: `config / client / if_start / state / stop / voice / core`.
Chain-entry detection uses prefixes + keywords, and a stop-word hit aborts immediately; the voice channel only exposes an interface (`voice.py`), waiting for the main project's `msg` + `sensevoice` to hook up.

## Environment

* Runtime shared with the main project at `runtime/311` (requests / Pillow / websockets / openai already in place).
* OCR uses iOS Vision on the phone; local PaddleOCR is no longer required.
* The legacy `src/server/`, `src/screen/`, `actions/jump_jump_tf_cv.py` etc. are the previous WDA-direct implementation, kept for reference only and no longer the current entry point.
