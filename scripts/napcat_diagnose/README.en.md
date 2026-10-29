# napcat_diagnose — Login-State Observation (Read-Only)

> [中文](README.md) | English

Goal: figure out **which files/keys/connections QQ's login state actually lands in**, and **exactly how official QQ differs from the NapCat portable build during the same login**.

**Boundaries**: metadata and hashes only, read-only; no config is changed, nothing is started, no QQ data files are copied, no ticket contents are exported.

---

## 1. Experiment Design (Two Accounts)

| Session | Client | Account | Purpose |
|---|---|---|---|
| `A-official` | Official QQ `D:\QQ` (9.9.29) | account A | control group |
| `B-napcat` | `.vendor\.NapCat` portable (9.9.26) | account B | target group |

Each account uses its own client, **so they don't kick each other off**.
> For more rigor you can add a crossed pair (official × B, NapCat × A), but every extra pair is another login risk — optional.

Collection points per group (identical set):

```
1. Client fully exited          → snap  00-cold      (cold baseline)
2. Start to the login screen (no scan) → snap  01-login     (logged-out state)
3. The moment the scan succeeds → snap  02-scanned   (login instant; the closer the better)
4. 60 seconds after login       → snap  03-online1
5. Then watch for 30~60 minutes (captures disconnects/reconnects/writes)
6. watch writes final on exit   → snap 99-final
```

> If a disconnect happens, note the time in the event stream first, then take an extra `snap 90-kicked`.

---

## 2. Commands

```powershell
$py = "D:\.Meowlisis\runtime\311\python.exe"
$c  = "D:\.Meowlisis\scripts\napcat_diagnose\collect.py"
$d  = "D:\.Meowlisis\scripts\napcat_diagnose\diff.py"

# cold state
& $py $c snap --session A-official --label 00-cold
# after starting QQ to the login screen
& $py $c snap --session A-official --label 01-login
# right after the QR scan succeeds
& $py $c snap --session A-official --label 02-scanned
# 60 seconds later
& $py $c snap --session A-official --label 03-online1
# collect continuously for 30 minutes (Ctrl+C ends early and still writes the final snapshot)
& $py $c watch --session A-official --duration 1800

# diffs
& $py $d --a "out\A-official\snap_00-cold.json"  --b "out\A-official\snap_02-scanned.json"
& $py $d --a "out\A-official\snap_01-login.json" --b "out\A-official\snap_99-final.json"
```

**Run as administrator**: only then can you get the full process module list, some registry hives, and the event log.

---

## 3. What Gets Collected

| Layer | Content | Frequency |
|---|---|---|
| Files | `D:\QQ\files\TencentFiles\Tencent Files`, `%APPDATA%\Tencent`, `%LOCALAPPDATA%\Tencent`, `Documents\Tencent Files`, NapCat `resources/app/napcat`. Records size/mtime/ctime/attributes/hash (full contents for ≤2MB; for large files the first and last 64KB plus the length); **includes `.db-wal` / `.db-shm`** | full on snap; every 1s on watch |
| Registry | `HKCU\Software\Tencent`, `HKLM\SOFTWARE\Tencent`, `HKLM\SOFTWARE\WOW6432Node\Tencent`, recursive; values store only length + hash (short plaintext keeps its raw value) | on snap; every 30s on watch |
| Processes | QQ/NapCat process tree, command lines, `--type=` (to tell whether renderer/GPU child processes exist), threads/handles, memory, **loaded modules** (looking for injection traces) | on snap; every 5s on watch |
| Pipes | Entries under `\\.\pipe\` containing napcat/mojo/qq | on snapshot; every 5s on watch |
| Network | inet connections of QQ-related PIDs (peer IP:port, state); DNS cache (snap only) | on snapshot; every 5s on watch |
| NapCat | `qrcode.png` appearing/disappearing, `config/*.json` hashes, `logs/*.log`, listeners on 3000/3001/6099, account directories under Tencent Files | on snapshot; every 5s on watch |
| System | Application event log entries mentioning qq/tencent/napcat (crashes, UtilityProcess exits) | snap only |

Large media directories (Emoji/Pic/Video/File/avatar/Ptt/ams) are skipped by default — they are 99% of the file count and irrelevant to login state.

---

## 4. How to Read the Results

`diff.py` lists **added / removed / changed** entries section by section: files / registry / processes / pipes / network / NapCat artifacts.

Three things to focus on:

1. **Which files appear between `00-cold → 02-scanned`** — those are the candidates for where login state lands (especially `nt_db\*.db-wal`, `nt_temp`, `misc.db`, `profile_info.db`, `settings.db`).
2. **The same-stage diff between `A-official` and `B-napcat`** — do the two clients write the same set of things; what does NapCat write extra, what does it omit.
3. **Process modules / `--type=`** — official QQ has renderer/gpu child processes; whether the NapCat portable build does is hard evidence for "has UI or not".

> Note: QQ's own `nt_data\log\qq-log_*.qqxlog` is encrypted; this project doesn't parse it (it only records that the files change).

---

## 5. Hard Rules

- Read-only; do not modify, move, or copy any QQ data file.
- Do not upload or share anything under `out/` (it contains local paths, processes, and registry key names).
- Do not run two clients on **the same account** concurrently (they kick each other off and also poison the conclusions).
- When you're done, just delete the whole `out/` directory (`rmdir /s /q out`).

---

## 6. Optional Extra: Procmon

For call-stack-level detail (who wrote this file, through which API), use Sysinternals **Procmon**:

- Filter: `Process Name is QQ.exe` or `Path contains Tencent Files`
- After capturing, `File → Save` as PML, then `File → Export` to CSV for me to parse
- Needs administrator; output may be hundreds of MB, so capture only the 2 minutes around login

These scripts handle "structured + diffable"; Procmon handles "maximum detail" — the two complement each other.
