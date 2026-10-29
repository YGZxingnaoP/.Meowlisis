# scripts/catpaws — phone control (CatPaws) integration-test scripts

> [中文](README.md) | English

All scripts resolve paths against the **project root**; double-click the `.bat` files, and run the `.py` files with `runtime\311\python.exe`.

| File | What it does | What it needs |
|---|---|---|
| `catpaws_device_test.bat` | **first choice for testing on a real device**: opens two windows, "dialog + trace", you type, the character operates the phone while talking, questions/answers all in the terminal | phone (8100) + auto-launched CatPaws service |
| `catpaws_device_test.py` | the Python implementation behind that .bat: goes through the main-chain modules (real `system_prompt` + real short-term memory) but **does not start the main project** | same as above |
| `catpaws_live_log.py` | log window: follows the main program's `[CatPaws]` lines + service startup lines + operation trace (tap/observe/ask/keep-awake/lock screen) | none |
| `catpaws_live.bat` / `catpaws_live_dialog.py` | **runs through the main program**: the dialog box feeds the character chain via `POST /msg` (TTS will speak out loud) | main program on 1800 + CatPaws service + phone |
| `catpaws_bridge_test.py` | **phone-free** bridge regression: a mock device runs "trigger → act → ask → reflect → end" and verifies the memory/TTS bridge | none (starts a mock service automatically; it refuses to run if a real-device service is already on 18110) |
| `catpaws_meituan_test.py` | real-device Meituan food ordering (bypasses the main project), `--shots` saves screenshots | phone + CatPaws service |
| `catpaws_chain_test.py` | early command-line tool (`status` / `device` / `run` / `chat`), **deprecated**; use `catpaws_device_test` for new tests | — |
| `catpaws_chat.bat` | old entry point paired with `catpaws_chain_test.py chat`, **deprecated** | — |
| `_catpaws_geom_test.py` | geometry self-check: safe-area clamping, swipe normalization, short-swipe rejection, rate limiting, image dimensions | none |

## Common commands

```bat
:: real-device integration test (recommended)
scripts\catpaws\catpaws_device_test.bat

:: phone-free bridge regression
runtime\311\python.exe scripts\catpaws\catpaws_bridge_test.py

:: geometry self-check
runtime\311\python.exe scripts\catpaws\_catpaws_geom_test.py
```

## Notes

- `catpaws_bridge_test.py` checks whether what's running on 18110 is **mock**; if a real-device service is running it refuses outright, so regression results don't get polluted.
- All script logs still go under the project's `logs/` (`svc_catpaw_<date>.log`, `catpaws_ops/ops_<date>.jsonl`).
- This directory writes no project files at all — it only reads config/logs and sends HTTP.
