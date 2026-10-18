# MeowLLM 使用协议（api.md）

> 本文是 **MeowLLM 对外协议的唯一说明**。任何协议改动都必须同步更新本文
> 以及项目侧 12 个 `port/meowllm.py` 的 `_build_params`（见文末「维护规则」）。

---

## 1. 服务形态

本地 sidecar 进程，**OpenAI 兼容**接口 + 一层控制面。默认只绑回环。

| 项 | 值 |
|---|---|
| 默认端口 | `18100`（被占用会顺延，实际端口写在 `port.json`） |
| 业务地址 | `http://127.0.0.1:<port>/meowllm/v1` |
| 控制面 | `http://127.0.0.1:<port>/meowllm/control` |
| 鉴权 | 无（`api_key` 随便填，OpenAI SDK 必填占位） |
| 模型名 | `meowllm-local`（`/v1/models` 可查） |
| 端点发现 | `<state_dir>/port.json`：`{"host","port","base_url","pid","started_at"}` |

> 项目侧不读 `port.json`：端口由启动器回写环境变量 `MEOWLLM_BASE_URL` 或项目
> `config.yml` 的 `llm.meowllm.base_url`；12 个端口的默认值也是这两处。

---

## 2. 业务接口（OpenAI 兼容）

### 2.1 `POST /v1/chat/completions`

标准字段（与 OpenAI 一致，均可用）：

```json
{
  "model": "meowllm-local",
  "messages": [{"role": "user", "content": "你好"}],
  "stream": true,
  "temperature": 0.8,
  "top_p": 0.9,
  "max_tokens": 256,
  "tools": [...],
  "tool_choice": "auto"
}
```

**本平台扩展字段**（OpenAI SDK 里要走 `extra_body`）：

| 字段 | 位置 | 说明 |
|---|---|---|
| `top_k` | **请求顶层** | 40 左右。⚠ 放进 `meowllm` 子块会被 schema 当未知字段**静默丢弃** |
| `repeat_penalty` | **请求顶层** | 1.05 左右，同上 |
| `meowllm.thinking_level` | 子块 | `off` / `low` / `medium` / `high`，默认取配置 |
| `meowllm.think_budget` | 子块 | 覆盖 `thinking.budgets.<level>`；一般不用传 |
| `meowllm.memory_owner` | 子块 | 用谁的 δ-mem，必须是 `^\d{6}$`（见 §4） |
| `meowllm.memory_write` | 子块 | **请求内顺便写记忆**（`["文本1", ...]`）；常规写入用控制面 |
| `meowllm.session_id` | 子块 | 复用 KV 会话（配置 `cache.session.enabled` 时生效） |
| `meowllm.context_limit` | 子块 | prompt 裁剪上限，**最小 1024**，超出报 400 |
| `meowllm.priority` | 子块 | 队列优先级（`interactive` 优先于 `background`） |

> `enable_thinking`（布尔）也接受：`false → off`，`true → medium`。

### 2.2 响应

非流式：标准 `choices[0].message`（`content` / `tool_calls`），外加
`model_extra.meowllm` 元数据：

```json
{"meowllm": {
  "stage": "prefill", "prompt_tokens": 14, "thinking_level": "off",
  "engine": "dualstream", "mode": "plain",
  "ttfb_ms": 120.5, "total_ms": 9481.4, "completion_tokens": 10,
  "queue": {"queue_depth": 0, "running": 1, "avg_waited_ms": 1888.3},
  "memory": {"attached": true, "owner": "000001"}
}}
```

流式：标准 SSE。**末尾固定补一个只含 `usage` 的 chunk**（`choices: []`），
客户端不要在 `if not chunk.choices: continue` 里把它丢掉，否则拿不到 token 统计。

`finish_reason`：`stop` / `length` / `tool_calls`。

---

## 3. 工具调用（function calling）

- 只支持 `type: "function"`（其它类型 400）。
- 模型在模板里用 Qwen3 原生的 `<tool_call>{json}</tool_call>` 形式输出；
  引擎侧 `parse_tool_calls()` 把它解析成结构化的 `tool_calls`。
- **带工具时强制走单流（plain）路径**，不进双流思考。
- 流式下增量结构：首个 chunk 带 `id`/`name`，后续 chunk 只带 `arguments` 增量，
  按 `index` 合并即可。

### ⚠ 协议级规则：带工具时**忽略** `memory_owner`

```python
# engine._apply_memory()
if params.tools:
    return {"attached": False, "reason": "tools"}
```

原因（实测）：δ-mem 的注入会扰动回复开头的 `<tool_call>` 标记，导致格式不合法、
解析失败、整段被当正文发出 → **工具从未执行**。强度越高越糟（α×4 直接重复崩坏）。

放在服务端而不是客户端，是为了让任何调用方（curl / 脚本 / 未来新平台）都自动守规矩。
**客户端不需要为 δ-mem 写任何特判。**

---

## 4. δ-mem（按用户记忆）

- 参数：36 层、r=64、N=1、chunk=16，约 56.63M（占 backbone 0.69%）。
- 状态：**每用户一个 `r×r` 矩阵 / 层**，delta 规则**覆盖式**更新
  （`S ← (1-β)S + β(v-Sk)kᵀ`）——不是追加式日志，写多了只会记得最近的。
- 落盘：`<state_dir>/<layout>/<owner>/mem/`，默认 `layout=userinfo`。

### 4.1 谁能用

| uid 形式 | 算不算正式用户 |
|---|---|
| `000001`（6 位数字） | ✅ |
| `temp-000029` / 空 / 其它 | ❌ 不挂记忆 |

规则同 `func/catbrain/UserMemory/identity/dmem_owner.py::is_formal()`。

### 4.2 写入与控制面

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/control/dmem/write` | `{owner, text, mode: replace\|append}` 写入该用户记忆；返回 `{ok, tokens, chunks, seconds, dir}` |
| POST | `/control/dmem/forget` | `{owner}` 清空 |
| POST | `/control/dmem/use` | `{owner}` 预热/切到某个 owner |
| GET | `/control/dmem/status` | `enabled` / `params` / `config` / `registry`（缓存、命中、写入统计）/ `reason`（为什么没挂上） |

> 记忆**写入**与**读取**是两条路：`write` 是独立请求，不受"工具回合忽略记忆"影响。

### 4.3 强度调参（重要）

`config.yml` 里 `memory.delta_mem.alpha` **只是初始化值**；训练后每层有自己的
`log_alpha`（实测 ≈16）。想改注入强度只能用 `alpha_scale`（乘在 `log_alpha` 上）：

| `alpha_scale` | 效果 |
|---|---|
| 1.0 | 生产默认。实测事实召回 0/4，但**不会破坏生成** |
| 4.0 | 干净短 prompt 下事实召回 4/4；**长 prompt + 带工具会重复崩坏** |
| 16.0 | 直接崩（`ffff…` / `respect respect…` 死循环） |

结论：**生产保持 1.0**。要用更高强度必须按真实请求（最长 prompt、最多工具）重新标定，
并配退化检测（4-gram 重复率、0 工具调用、空正文）。

---

## 5. 控制面

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/control/health` | `{ok, engine:{model, loaded, params_b, mode}, uptime_s}` |
| GET | `/control/stats` | `cache` / `perf`（ttfb、错误、tool 计数）/ `queue` / `engine` / `gpu` / `memory` |
| GET | `/control/gpu` | 显存/利用率/进程占用（torch → pynvml → `nvidia-smi` 三级回退） |
| GET | `/control/version` | 版本 |
| POST | `/control/reload` | 重载配置（模型不重载） |
| POST | `/control/session/reset` | `{session_id}` 清 KV 会话 |

### 错误约定

```json
{"error": {"code": "meowllm.engine_error", "message": "构建提示词失败：…"}}
```

| HTTP | code | 场景 |
|---|---|---|
| 400 | `meowllm.contract_error` | 字段类型/取值不合法（如 `context_limit < 1024`） |
| 503 | `meowllm.engine_error` | 引擎未就绪 / 生成失败 |
| 429 | `meowllm.queue_full` | 队列满（`queue.max_depth`） |

---

## 6. 项目侧怎么接（12 个端口）

每个 `func/<模块>/port/meowllm.py` **结构与同目录的 deepseek.py 一致**：
自己读配置 → `OpenAI(api_key="meowllm-local", base_url=...)` → 自己的 `_build_params`
→ `chat` / `chat_stream`。`func/` 下**没有** `meowllm/` 平台目录。

`_build_params` 必须做到这四件事（与本文 §2 对齐）：

```python
params = {model, messages, stream, temperature, top_p, max_tokens}
if tools: params["tools"] = tools
if tool_choice: params["tool_choice"] = tool_choice
params["extra_body"] = {
    "top_k": ..., "repeat_penalty": ...,          # 顶层，不是 meowllm 子块
    "meowllm": {"thinking_level": ..., "memory_owner": ...},
}
```

---

## 7. 维护规则（改协议时照做）

1. **先改服务端**（`meowllm/server/schema.py` + 引擎），并给新字段**默认值**——
   这样老客户端不改也能跑。
2. **同步本文**：字段表、响应示例、错误码。
3. 只有当"客户端必须传新值才生效"时，才去改 12 个 `_build_params`。
4. 改完跑三件事：
   - `python -m meowllm.server.app --check`（配置校验）
   - 12 个端口冒烟：同一输入构造，断言 `extra_body` 逐字段相同
   - 带工具 + 带 `memory_owner` 各一次实测（确认 §3 的规则仍生效）
5. 破坏性变更（改名、改语义）必须**同时**改 12 个端口 + 本文，并在
   `docs/notes/` 留一条变更记录。

---

## 8. 常见坑

| 坑 | 现象 | 正解 |
|---|---|---|
| `top_k` 放进 `meowllm` 子块 | 静默无效 | 放请求顶层 |
| `thinking_level: off` 不加引号 | YAML 解析成布尔 `False` | 写 `"off"` |
| 带工具又挂记忆 | 正文里出现 `qq_send_message{...}`，工具不执行 | 服务端已自动忽略；客户端别加特判 |
| `context_limit` 设 512 | 400 错误 | 最小 1024 |
| 流式末尾 usage chunk 被丢 | 统计不到 token | 别在 `not chunk.choices` 时 `continue` 掉最后一片 |
| `alpha_scale` 调高 | 重复崩坏 / 死循环 | 生产保持 1.0 |
| 用 `port.json` 硬编码端口 | 端口顺延后连不上 | 读 `MEOWLLM_BASE_URL` 或 `llm.meowllm.base_url` |
