# napcat_diagnose —— 登录态观测（只读）

> [English](README.en.md) | 中文

目的：弄清 **QQ 的登录态到底落在哪些文件/键/连接上**，以及 **官方 QQ 与 NapCat 便携版在同一次登录里到底差在哪**。

**边界**：只读元数据与哈希；不改任何配置、不启动任何程序、不复制 QQ 数据文件本体、不导出票据内容。

---

## 一、实验设计（两个账号）

| 会话 | 客户端 | 账号 | 用途 |
|---|---|---|---|
| `A-official` | 官方 QQ `D:\QQ`（9.9.29） | A 号 | 对照组 |
| `B-napcat` | `.vendor\.NapCat` 便携（9.9.26） | B 号 | 目标组 |

两个账号各用自己的客户端，**避免互相顶号**。
> 想更严谨可以补一组交叉（官方×B、NapCat×A），但每多一组就多一次登录风险，按需。

每组的采点（同一套）：

```
1. 客户端完全退出        → snap  00-cold      （冷态基线）
2. 启动到登录界面（不扫码）→ snap  01-login     （未登录态）
3. 扫码成功那一刻        → snap  02-scanned   （登录瞬间，越接近越好）
4. 登录后 60 秒          → snap  03-online1
5. 然后 watch 30~60 分钟  （捕获掉线/重连/写入）
6. watch 结束时自动写 final → snap 99-final
```

> 掉线如果发生，先在事件流里记时间，再补一个 `snap 90-kicked`。

---

## 二、命令

```powershell
$py = "D:\.Meowlisis\runtime\311\python.exe"
$c  = "D:\.Meowlisis\scripts\napcat_diagnose\collect.py"
$d  = "D:\.Meowlisis\scripts\napcat_diagnose\diff.py"

# 冷态
& $py $c snap --session A-official --label 00-cold
# 启动 QQ 到登录界面后
& $py $c snap --session A-official --label 01-login
# 扫码成功后立刻
& $py $c snap --session A-official --label 02-scanned
# 60 秒后
& $py $c snap --session A-official --label 03-online1
# 持续采集 30 分钟（Ctrl+C 可提前结束，会自动补 final 快照）
& $py $c watch --session A-official --duration 1800

# 差量
& $py $d --a "out\A-official\snap_00-cold.json"  --b "out\A-official\snap_02-scanned.json"
& $py $d --a "out\A-official\snap_01-login.json" --b "out\A-official\snap_99-final.json"
```

**建议以管理员运行**：进程模块列表、部分注册表、事件日志才拿得全。

---

## 三、采了什么

| 层 | 内容 | 频率 |
|---|---|---|
| 文件 | `D:\QQ\files\TencentFiles\Tencent Files`、`%APPDATA%\Tencent`、`%LOCALAPPDATA%\Tencent`、`Documents\Tencent Files`、NapCat `resources/app/napcat`。记录 size/mtime/ctime/属性/哈希（≤2MB 全量，大文件头尾 64KB+长度）；**含 `.db-wal` / `.db-shm`** | snap 全量；watch 1s |
| 注册表 | `HKCU\Software\Tencent`、`HKLM\SOFTWARE\Tencent`、`HKLM\SOFTWARE\WOW6432Node\Tencent` 递归；值只存长度+哈希（短明文才留原值） | snap；watch 30s |
| 进程 | QQ/NapCat 进程树、命令行、`--type=`（判断有无 renderer/GPU 子进程）、线程/句柄、内存、**已加载模块**（看注入痕迹） | snap；watch 5s |
| 管道 | `\\.\pipe\` 里含 napcat/mojo/qq 的项 | snapshot；watch 5s |
| 网络 | QQ 相关 PID 的 inet 连接（对端 IP:port、状态）；DNS 缓存（仅 snap） | snapshot；watch 5s |
| NapCat | `qrcode.png` 出现/消失、`config/*.json` 哈希、`logs/*.log`、3000/3001/6099 监听、Tencent Files 下的账号目录 | snapshot；watch 5s |
| 系统 | Application 事件日志里含 qq/tencent/napcat 的条目（崩溃、UtilityProcess 退出） | 仅 snap |

大媒体目录（Emoji/Pic/Video/File/avatar/Ptt/ams）默认跳过——占 99% 文件量、与登录态无关。

---

## 四、怎么读结果

`diff.py` 会按"文件 / 注册表 / 进程 / 管道 / 网络 / NapCat 产物"分节列出 **新增 / 消失 / 变化**。

重点看三件事：

1. **`00-cold → 02-scanned` 新增了哪些文件** —— 这就是登录态的落点候选（尤其 `nt_db\*.db-wal`、`nt_temp`、`misc.db`、`profile_info.db`、`settings.db`）。
2. **`A-official` 与 `B-napcat` 的同阶段差量** —— 两个客户端写的东西是否同一套；NapCat 多写了什么、少写了什么。
3. **进程模块 / `--type=`** —— 官方 QQ 有 renderer/gpu 子进程，NapCat 便携版是否有，是"有无 UI"的硬证据。

> 注：QQ 自己的 `nt_data\log\qq-log_*.qqxlog` 是加密的，本项目不解析它（只记录文件变化）。

---

## 五、红线

- 只读；不修改、不移动、不复制任何 QQ 数据文件。
- 不把 `out/` 里任何内容上传或分享（里面含本机路径、进程、注册表键名）。
- 不要在**同一账号**上并发跑两个客户端（会互相顶号，也会污染结论）。
- 做完删除 `out/` 整个目录即可（`rmdir /s /q out`）。

---

## 六、可选增强：Procmon

想要调用栈级别的细节（谁写了这个文件、用了哪个 API），用 Sysinternals **Procmon**：

- 过滤器：`Process Name is QQ.exe` 或 `Path contains Tencent Files`
- 抓完 `File → Save` 成 PML，再 `File → Export` 成 CSV 给我解析
- 需要管理员；输出可能几百 MB，建议只抓登录前后 2 分钟

本脚本负责"结构化 + 可 diff"，Procmon 负责"极致细"，两者互补。
