# catpaws-launcher —— 设备就绪管理器

一个**自包含**的目录：把它整个复制到任意位置就能用（也可以直接放进主项目）。
自动完成「插上 USB → 起隧道 → 端口转发 → 拉起 WDA → 等就绪」，并在掉线后自动恢复。
**不需要管理员权限**（隧道走 `--userspace`）。

## 目录内容（只有 9 个文件，复制时别带 `run\`）

| 文件 | 作用 |
|---|---|
| `start.cmd` | 启动守护进程（Ctrl+C 退出） |
| `stop.cmd` | 结束它启动的所有子进程（tunnel / forward / runwda） |
| `status.cmd` | 一次性查看：设备、隧道、已装 CatPaws、WDA 探活 |
| `launcher.ps1` | 主逻辑（守护循环 + 自动恢复） |
| `status.ps1` / `stop.ps1` | 上面两个辅助脚本的实现 |
| `ios.exe` | go-ios 1.3.2（随目录分发，23.7 MB） |
| `config.json` | 配置（可在复制后按需改） |
| `README.md` | 本文件 |
| `run\` | **运行时自动生成**：日志与 PID 记录，不含代码，复制时可忽略/删除 |

## 用法

```bat
start.cmd          :: 常驻守护（开一个窗口放着就行）
status.cmd         :: 另开窗口随时查看状态
stop.cmd           :: 收工清理
```

`config.json`：

```json
{
  "runner_id": "",          // 留空 = 每次从设备动态探测（推荐：重签后 id 会变）
  "device_ip": "",          // 可选：填手机局域网 IP，探活时额外用 Wi-Fi 试一次
  "wda_port": 8100,
  "health_interval_s": 3,
  "tunnel_wait_s": 25,
  "max_restarts": 50
}
```

## 它内部做了什么（每一步都有实测依据）

1. `ios.exe list` —— 确认设备在 USB 上；
2. `ios.exe tunnel start --userspace` —— iOS 17+ 的 testmanagerd 只能经隧道访问；
3. `ios.exe apps --list` —— 查出实际安装的 CatPaws runner id。
   **必须动态查**：签名器（iloader）会给 id 加后缀，例如
   `com.facebook.WebDriverAgentRunner.xctrunner` → `…xctrunner.D79NHBM8JL`，重签后还可能变；
4. `ios.exe forward <port> <port>` —— 建立 PC → 手机的端口转发（`runwda` 本身不做转发）；
5. `ios.exe runwda --bundleid=<id> --testrunnerbundleid=<同一个 id> --xctestconfig=WebDriverAgentRunner.xctest --log-output="…\run\wda.log"`
   —— 两个 id 必须是同一个（go-ios 自身的默认值就是同一个）；
6. 轮询 `http://127.0.0.1:8100/cw/v1/ping`，200 即就绪（填了 `device_ip` 还会试局域网直连）。

## 掉线/异常时的行为（均已实测）

| 情况 | 守护进程表现 |
|---|---|
| **拔掉 USB** | 打 `[WAIT] USB 上没有设备`，并结束 tunnel/forward/runwda；手机上的 WDA 约 28 秒后被设备端回收 |
| **插回 USB** | 约 6 秒内自动恢复（TUNNEL → FWD → runwda → `[OK]`） |
| 手机重启 / 锁屏 | runwda 退出 → 自动重新拉起（锁屏时能起，但动作会返回 `E_DEVICE_LOCKED`） |
| 7 天证书过期 | 一直 `[WAIT] 没找到已安装的 CatPaws`；需用 iloader 重装 |
| App 被卸载/改名 | 同上；`apps --list` 里找不到 `CatPaws*` |

> ⚠️ **拔线不能继续用**：XCTest 会话依赖 USB 隧道，拔线后 runner 只能活约 28 秒就会
> 被设备端 `testmanagerd` 回收（实测 16:53:05 拔线 → 16:53:33 失效）。这不是 go-ios 杀的，
> 所以**改 go-ios 也解决不了**。
> 但**线插着的时候**，PC 可以用手机局域网 IP 访问 `:8100`（实测 200），`forward` 不是必须的。

## 排错

| 现象 | 处理 |
|---|---|
| `找不到 ios.exe` | 确认 `ios.exe` 与脚本在同一目录 |
| 一直 `[WAIT] USB 上没有设备` | 换线/换口；手机上点「信任」并解锁 |
| 一直 `[WAIT] 没找到已安装的 CatPaws` | 用 iloader 重装；或在 `config.json` 里手动填 `runner_id` |
| 一直 `[WDA] 尚未就绪` | 看 `run\wda.log` 与 `run\runwda.err.log`；常见是证书过期、开发者模式被关 |
| Defender 报毒（`ios.exe`） | 给本目录加排除：`Add-MpPreference -ExclusionPath "<本目录>"` |

## 复制到主项目（Meowlisis）

```bat
xcopy /E /I /Y "D:\Virtual Machines\catpaws-launcher" "D:\.Meowlisis\.vendor\.CatPaws\bin\catpaws-launcher"
```

`\.vendor` 本来就是运行时依赖目录，符合项目约定。然后在 `src\cw\server.py` 里拉起：

```python
import subprocess, pathlib, time, urllib.request

LAUNCHER = pathlib.Path(__file__).resolve().parents[2] / "bin" / "catpaws-launcher"

def ensure_device_ready(timeout=90):
    """启动守护进程并等待 WDA 就绪；已就绪则直接返回。"""
    proc = subprocess.Popen(
        [str(LAUNCHER / "start.cmd")],
        cwd=str(LAUNCHER),
        creationflags=subprocess.CREATE_NEW_CONSOLE,   # 独立窗口，便于观察日志
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
    raise RuntimeError("WDA 未就绪，检查 run\\launcher.log")
```

注意：

- `wda_port` 要与主项目 `config.yml` 的 `catpaws.device_port` 保持一致（默认 8100）；
- 守护进程是常驻的，**不要**在请求结束时 kill 它；进程崩了直接再调一次 `start.cmd` 即可（它会复用已有隧道）；
- 需要停止时调 `stop.cmd`。
