# catpaws-launcher — device readiness manager

> [中文](README.md) | English

A **self-contained** directory: copy the whole thing anywhere and it works (you can also drop it straight into the main project).
It automates "plug in USB → start tunnel → forward port → launch WDA → wait until ready", and recovers automatically after a disconnect.
**No administrator rights needed** (the tunnel uses `--userspace`).

## Directory contents (only 9 files; don't copy `run\`)

| File | Purpose |
|---|---|
| `start.cmd` | Start the daemon (Ctrl+C to quit) |
| `stop.cmd` | Kill every child process it started (tunnel / forward / runwda) |
| `status.cmd` | One-shot look at: device, tunnel, installed CatPaws, WDA liveness |
| `launcher.ps1` | Main logic (guard loop + automatic recovery) |
| `status.ps1` / `stop.ps1` | Implementations behind the two helpers above |
| `ios.exe` | go-ios 1.3.2 (shipped with the directory, 23.7 MB) |
| `config.json` | Config (edit as needed after copying) |
| `README.md` | This file |
| `run\` | **generated automatically at runtime**: logs and PID records, no code; ignore/delete it when copying |

## Usage

```bat
start.cmd          :: long-running daemon (just leave one window open)
status.cmd         :: open another window and check status anytime
stop.cmd           :: clean up when you're done
```

`config.json`:

```json
{
  "runner_id": "",          // leave empty = detect dynamically from the device each time (recommended: the id changes after re-signing)
  "device_ip": "",          // optional: phone LAN IP; liveness checks will also try Wi-Fi once
  "wda_port": 8100,
  "health_interval_s": 3,
  "tunnel_wait_s": 25,
  "max_restarts": 50
}
```

## What it does internally (every step is backed by real testing)

1. `ios.exe list` — confirm the device is on USB;
2. `ios.exe tunnel start --userspace` — on iOS 17+ testmanagerd is only reachable through the tunnel;
3. `ios.exe apps --list` — find the CatPaws runner id that is actually installed.
   **This must be queried dynamically**: the signer (iloader) appends a suffix to the id, e.g.
   `com.facebook.WebDriverAgentRunner.xctrunner` → `…xctrunner.D79NHBM8JL`, and it can change again after re-signing;
4. `ios.exe forward <port> <port>` — set up the PC → phone port forward (`runwda` itself does not forward);
5. `ios.exe runwda --bundleid=<id> --testrunnerbundleid=<the same id> --xctestconfig=WebDriverAgentRunner.xctest --log-output="…\run\wda.log"`
   — both ids must be the same (go-ios's own default is the same id);
6. poll `http://127.0.0.1:8100/cw/v1/ping`, 200 means ready (with `device_ip` set it also tries a direct LAN connection).

## Behaviour when disconnected / in trouble (all measured)

| Situation | What the daemon does |
|---|---|
| **USB unplugged** | Logs `[WAIT] USB 上没有设备` (no device on USB) and stops tunnel/forward/runwda; WDA on the phone is reclaimed by the device side after about 28 seconds |
| **USB plugged back in** | Recovers automatically within about 6 seconds (TUNNEL → FWD → runwda → `[OK]`) |
| Phone reboot / screen lock | runwda exits → relaunched automatically (it starts while locked, but actions return `E_DEVICE_LOCKED`) |
| 7-day certificate expires | Stuck on `[WAIT] 没找到已安装的 CatPaws` (no installed CatPaws found); reinstall with iloader |
| App uninstalled/renamed | Same as above; `CatPaws*` is missing from `apps --list` |

> ⚠️ **You can't keep it running after unplugging**: the XCTest session depends on the USB tunnel; once unplugged the runner
> survives only about 28 seconds before `testmanagerd` on the device reclaims it (measured: unplugged at 16:53:05 → dead at 16:53:33). go-ios
> isn't the one killing it, so **patching go-ios won't fix it either**.
> But **while the cable is plugged in**, the PC can reach `:8100` over the phone's LAN IP (measured 200), so `forward` isn't strictly required.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `找不到 ios.exe` (can't find ios.exe) | Make sure `ios.exe` is in the same directory as the scripts |
| Stuck on `[WAIT] USB 上没有设备` (no device on USB) | Try another cable/port; tap "Trust" on the phone and unlock it |
| Stuck on `[WAIT] 没找到已安装的 CatPaws` (no installed CatPaws) | Reinstall with iloader; or set `runner_id` manually in `config.json` |
| Stuck on `[WDA] 尚未就绪` (not ready yet) | Check `run\wda.log` and `run\runwda.err.log`; usually an expired certificate or Developer Mode turned off |
| Defender flags `ios.exe` | Add an exclusion for this directory: `Add-MpPreference -ExclusionPath "<this directory>"` |

## Copying into the main project (Meowlisis)

```bat
xcopy /E /I /Y "D:\Virtual Machines\catpaws-launcher" "D:\.Meowlisis\.vendor\.CatPaws\bin\catpaws-launcher"
```

`\.vendor` is a runtime dependency directory anyway, so this fits the project conventions. Then launch it from `src\cw\server.py`:

```python
import subprocess, pathlib, time, urllib.request

LAUNCHER = pathlib.Path(__file__).resolve().parents[2] / "bin" / "catpaws-launcher"

def ensure_device_ready(timeout=90):
    """Start the daemon and wait for WDA to be ready; return immediately if it already is."""
    proc = subprocess.Popen(
        [str(LAUNCHER / "start.cmd")],
        cwd=str(LAUNCHER),
        creationflags=subprocess.CREATE_NEW_CONSOLE,   # separate window, easier to watch the logs
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8100/cw/v1/ping", timeout=2) as r:
                if r.status == 200:
                    return proc
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("WDA not ready, check run\\launcher.log")
```

Notes:

- `wda_port` must match `catpaws.device_port` in the main project's `config.yml` (default 8100);
- the daemon is long-running — **do not** kill it when a request finishes; if the process dies, just call `start.cmd` again (it reuses the existing tunnel);
- call `stop.cmd` when you need to stop it.
