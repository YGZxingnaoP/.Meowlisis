# labs —— 实验台（双流 vs 单流对照）

> 这里只做一件事：**用真实使用方式**（SSE 流式、逐字出、思考内容照实显示）跑
> 「双流边想边说」和「单流不想直说」两种模式，把首字延迟、思考字数、正文字数摊开看。
>
> MeowLLM 本体（引擎/服务/配置）在 `..\`，训练与云端实验在隔壁的
> `dmem_train\`。这个 README 只讲 `labs\` 本身。

零依赖：只要 Node 18+（本机 v24）。不需要 npm install。

```powershell
cd .vendor\.MeowLLM\labs
run_lab.bat                 :: 起 MeowLLM(必要的话) + 实验台 + 开浏览器
node run_headless.js        :: 无界面跑一轮对照（需要实验台已在跑）
```

---

## 1. 组成

| 文件 | 作用 |
|---|---|
| `launch.py` | **唯一编排入口**。找 python/node、探测 18100 起已有实例、没有就起一个、再起 `server.js`、开浏览器 |
| `server.js` | 实验台后端（零依赖）：静态页 + 把 MeowLLM 的 SSE 转成 NDJSON 事件 |
| `build_prompt.py` | **主项目构建模式**：按主项目真实链路（MeowPromptBuilder + PromptGet + 最近 N 轮短期记忆）拼一条 messages。**只读**：`ShortMemory` 的 `_mark_session/_write/save` 全部打桩，并在前后比对 `public_short_mem.json` 的 sha1 |
| `public\index.html` | 单页前端（内联 CSS/JS，无构建） |
| `run_lab.bat` | 薄壳，全部逻辑在 `launch.py` |
| `run_headless.js` | 无界面跑一次，`POST /api/run` |
| `autoDL\` | 云端凭据（`登录指令.txt` / `密码.txt`，已被 .gitignore 排除） |

### 主项目构建模式（勾选即用）

页面输入框下面勾「主项目构建模式（真实 system + 短期记忆，只读）」+ 填账号（默认
`000001`），实验台就会调 `build_prompt.py` 现拼一条请求：

```
system   = catbrain 人设（api.py 里 register_builder 的那条链路）
history  = .temp/public_short_mem.json 最近 N 轮（直接读 JSON，不走 ShortMemory）
user     = 你输入的那句
```

发出去之后 `built` 事件会回传 system 字数 / 历史条数 / 记忆有没有被改动。
命令行等价用法：

```powershell
..\..\..\runtime\311\python.exe build_prompt.py --uid 000001 --text "在吗" --full
```

`experiments\*.json` 是早期 MIRROR 实验的场景数据，**现在没有任何代码读它**
（`server.js` 全文不引用），属于待删的历史文件。

## 2. 启动方式

```powershell
run_lab.bat                 :: start（默认）：没有实例就起，有就复用
run_lab.bat attach          :: 只起实验台，要求 MeowLLM 已经在跑
run_lab.bat nobrowser       :: 不开浏览器
run_lab.bat stub            :: 用零权重假引擎（只验管道）
run_lab.bat llamacpp        :: 用真 llama.cpp 引擎
run_lab.bat --cloud         :: 本地没有实例时连云端（经 SSH 隧道）
node server.js --meowllm http://127.0.0.1:18100 --port 18700
```

位置参数由 `launch.py` 里的 `words` 逐个解析，写成 `start`/`attach`/`nobrowser`
这些词都可以（argparse 不会再把它们当非法参数直接退出）。

## 3. 两条臂

| 臂 | thinking | 说明 |
|---|---|---|
| `A_async` | `low` | 双流：边想边分段说 |
| `S_seq` | `off` | 单流：不思考、一口气说完 |

页面能直接看到**首字延迟**和**思考/正文各多少字** —— 这两个数才是"真流式"的证据。

## 4. 端口与端点

| 端口 | 谁 |
|---|---|
| **18100**（回退到 18108） | MeowLLM 本体 |
| **18700** | 实验台 |

实验台用到的 MeowLLM 端点：

| 端点 | 用途 |
|---|---|
| `POST /meowllm/v1/chat/completions` | 对话（`stream: true`，带 `meowllm.thinking_level`） |
| `GET /meowllm/control/health` | 探测实例是否活着 |

实验台自己的端点：`GET /`、`GET /api/info`、`POST /api/chat`（NDJSON 流）、
`POST /api/run`（跑一轮并落盘到 `labs\out\`）。

环境变量：`MEOWLLM`（MeowLLM 地址）、`LAB_PORT`、`LAB_OUT`。

## 5. 数据隔离（重要）

实验台起的是**同一个** `meowllm.server.app`、读的是**同一份** `config.yml`。
如果不改目录，实验产生的 δ-mem 状态会直接写进主项目真实的
`character/userinfo/<uid>/mem/` —— 等于拿真人记忆做实验。

所以 `launch.py` 默认注入三个环境变量，把数据和主项目彻底隔开：

| 环境变量 | 实验台的值 | 默认（主项目） |
|---|---|---|
| `MEOWLLM_STATE_DIR` | `labs/.lab/state` | `.test/state/meowllm` |
| `MEOWLLM_LOG_DIR` | `labs/.lab/logs` | `.test/logs` |
| `MEOWLLM__MEMORY__DELTA_MEM__USERINFO_DIR` | `labs/.lab/userinfo` | `../../character/userinfo` |

（都相对模块根 `.vendor/.MeowLLM/`，且 `labs/.lab/` 已在 .gitignore 里）

- 想**故意**用主项目真实数据：`run_lab.bat shared` 或 `launch.py --shared`
  （会打印红字警告）。
- 注意两种例外：
  1. **复用已有实例**时不生效 —— 数据目录是启动那个人决定的。要保证隔离就先停掉
     再跑本脚本。
  2. 实验台占用 18100 时，主项目读 `port.json` 也会连到它。此时主项目写记忆会写进
     实验台的沙箱目录（不会污染，但也存不到真实用户身上）。所以别在跑实验的同时
     用主项目聊天。

## 6. 云端怎么对应

`labs\` 里的路径**全部相对**，所以上云不需要改代码。规则只有一条，写在
`dmem_train\cloud_paths.py` 里：

```
本地   .vendor\.MeowLLM\labs\...
云端   <REMOTE_ROOT>/labs/...            REMOTE_ROOT 默认 /root/autodl-tmp/MeowLLM
```

`launch.py --cloud` 走 `..\.scripts\cloud_serve.py`：它在云端 `cd <REMOTE_ROOT>`
起同一个 `meowllm.server.app`，再把远端端口隧道到本地 —— 本地这一侧看到的仍然是
`http://127.0.0.1:18100`，实验台完全不知情地跑在云端 8B 上。

远端根用环境变量覆盖：`MEOWLLM_REMOTE_ROOT`、`MEOWLLM_REMOTE_PYTHON`。
