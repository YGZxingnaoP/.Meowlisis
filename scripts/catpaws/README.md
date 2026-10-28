# scripts/catpaws —— 手机操作（CatPaws）联调脚本

全部脚本都以**项目根目录**为基准；`.bat` 双击即可，`.py` 用 `runtime\311\python.exe` 跑。

| 文件 | 干什么 | 需要什么 |
|---|---|---|
| `catpaws_device_test.bat` | **真机联调首选**：开「对话 + 流水」两个窗口，你打字，角色边操作边说话，提问/回答都在终端里 | 手机（8100）+ 自动拉起 CatPaws 服务 |
| `catpaws_device_test.py` | 上面那个 bat 的 Python 实现：走主链路模块（真 `system_prompt` + 真短期记忆），但**不启动主项目** | 同上 |
| `catpaws_live_log.py` | 日志窗口：跟主程序 `[CatPaws]` 行 + 服务启动行 + 操作流水（点按/观察/提问/防息屏/锁屏） | 无 |
| `catpaws_live.bat` / `catpaws_live_dialog.py` | **走主程序**的联调：对话框经 `POST /msg` 进角色链路（TTS 会出声） | 主程序 1800 + CatPaws 服务 + 手机 |
| `catpaws_bridge_test.py` | **免手机**的桥接回归：mock 设备跑「触发 → 操作 → 追问 → 反思 → end」，验证记忆/TTS 桥接 | 无（自动起 mock 服务，若 18110 上跑着真机服务会拒绝执行） |
| `catpaws_meituan_test.py` | 真机美团点外卖（不经过主项目），`--shots` 存截图 | 手机 + CatPaws 服务 |
| `catpaws_chain_test.py` | 早期命令行工具（`status` / `device` / `run` / `chat`），**已过时**，新测试请用 `catpaws_device_test` | — |
| `catpaws_chat.bat` | 配套 `catpaws_chain_test.py chat` 的旧入口，**已过时** | — |
| `_catpaws_geom_test.py` | 几何自检：安全区夹取、swipe 归一化、短滑动拒绝、限速、图像尺寸 | 无 |

## 常用命令

```bat
:: 真机联调（推荐）
scripts\catpaws\catpaws_device_test.bat

:: 免手机的桥接回归
runtime\311\python.exe scripts\catpaws\catpaws_bridge_test.py

:: 几何自检
runtime\311\python.exe scripts\catpaws\_catpaws_geom_test.py
```

## 注意

- `catpaws_bridge_test.py` 会检查 18110 上跑的是不是 **mock**；真机服务在跑时它会明确拒绝，避免污染回归结果。
- 所有脚本的输出日志仍在项目 `logs/` 下（`svc_catpaw_<日期>.log`、`catpaws_ops/ops_<日期>.jsonl`）。
- 本目录不写任何项目文件，只读配置/日志、发 HTTP。
