# PLAN · MeowLLM 代码模块清单 + llama.cpp 选型（待评审，未实施）

> **本文档目的**：实施前把「要写哪些文件、每个文件的类/方法/职责」和「llama.cpp 该下哪个版本、怎么在本机和云端采集必要信息」讲清楚，请你逐条提修改意见。
> **配套文档**：`PLAN_MeowLLM_本地模型接入方案.md`（架构、命名规范、端口、缓存、验收）
> **状态**：一行代码都还没写。本文档通过后再开工。

---

## 第一部分 · 代码模块清单

### 1.1 分批策略（建议按 B1 → B2 → B3 分批评审）

| 批次 | 内容 | 何时做 | 能否本机跑 | 估行数 |
|---|---|---|---|---|
| **B1** | 服务骨架 + 契约 + stub 引擎 + 缓存记账 + 自测 | **先做** | ✅ 零下载零权重 | ≈2 900 |
| **B2** | MIRROR 认知层 + 工具语法约束 + 视觉模板 | B1 全绿后 | ✅ 仍用 stub | ≈800 |
| **B3** | 真实引擎（llamacpp / hf / vllm） | 云端 V1 前 | ❌ 需 GPU | ≈1 200 |

**B1 就能验证你最关心的三件事**：项目 ↔ MeowLLM 契约成立、缓存账本正确、命名规范落地。这三件都不需要权重。

### 1.2 总目录树（`*` = B1，`†` = B2，`‡` = B3）

```
.vendor/.MeowLLM/
├─ meowllm.yml *                        # 配置（根键 meowllm:）
├─ README.md *                          # 命名规范 + 禁用名清单 + 启动/自测说明
├─ requirements.txt *                   # B1 为空（复用 runtime/311）
│
├─ meowllm/
│  ├─ __init__.py *                     # MeowLLM_VERSION / MeowLLM_API_VERSION
│  ├─ meowllm_errors.py *               # 异常族
│  ├─ meowllm_config.py *               # 配置加载 + 校验
│  ├─ meowllm_scheduler.py *            # 优先级队列（interactive / background）
│  │
│  ├─ server/
│  │  ├─ meowllm_schema.py *            # 请求模型 + extra_body.meowllm 解析
│  │  ├─ meowllm_stream.py *            # OpenAI 分片封装（content/reasoning/tool_calls）
│  │  ├─ meowllm_app.py *               # FastAPI 入口 + lifespan + main()
│  │  ├─ meowllm_routes_v1.py *         # /meowllm/v1/*
│  │  └─ meowllm_routes_control.py *    # /meowllm/control/*
│  │
│  ├─ engine/
│  │  ├─ meowllm_engine_base.py *       # 抽象接口 + MeowLLMGenParams/MeowLLMGenEvent
│  │  ├─ meowllm_engine_factory.py *    # 三道安全闸门（C4）
│  │  ├─ meowllm_engine_stub.py *       # ★ 本机唯一引擎，零权重
│  │  ├─ meowllm_engine_llamacpp.py ‡
│  │  ├─ meowllm_engine_hf.py ‡
│  │  └─ meowllm_engine_vllm.py ‡
│  │
│  ├─ cache/
│  │  ├─ meowllm_cache_prefix.py *      # 前缀键计算 + 命中记账
│  │  └─ meowllm_cache_session.py *     # per-meowid 会话（LRU + TTL）
│  │
│  ├─ tools/
│  │  ├─ meowllm_tool_parse.py *        # 工具参数容错解析 + 分片镜像
│  │  └─ meowllm_tool_guard.py †        # 工具子集化 + JSON Schema 语法约束
│  │
│  ├─ mirror/
│  │  ├─ meowllm_mirror_state.py †      # ThinkState（有界 + 每轮重构）
│  │  ├─ meowllm_mirror_prompt.py †     # Talker 分区 / Thinker 提示 + JSON schema
│  │  ├─ meowllm_mirror_core.py †       # 状态机 IDLE→TALK→THINK
│  │  └─ meowllm_mirror_loop.py †       # 后台思考循环 + salience 门控
│  │
│  └─ vision/
│     ├─ meowllm_vision_encode.py *     # data URL 解码 + 像素探测 + 限流 + token 估算
│     └─ meowllm_vision_template.py †   # messages 里抽图 / 转引擎格式
│
├─ bin/
│  ├─ meowllm_start.ps1 *               # 端口探测 + 启动 + 健康轮询 + READY
│  ├─ meowllm_selftest.py *             # 12 项契约矩阵
│  ├─ meowllm_project_probe.py *        # ★ 用项目真 port 打本服务
│  └─ meowllm_bench.py †                # TPS / 命中率 / TTFB 基准
│
├─ state/meowllm/                       # 运行态（.gitignore，不写项目 .temp）
├─ models/                              # 权重（.gitignore）
└─ logs/
```

### 1.3 B1 模块逐项规格

---

#### `meowllm/__init__.py` · ≈20 行

```python
MeowLLM_VERSION: str          = "0.1.0"
MeowLLM_API_VERSION: str      = "meowllm/v1"
MeowLLM_CONTROL_PREFIX: str   = "/meowllm/control"
MeowLLM_V1_PREFIX: str        = "/meowllm/v1"
```
职责：放版本与路径常量，让端点前缀只在一处定义。

---

#### `meowllm/meowllm_errors.py` · ≈40 行

```python
class MeowLLMError(Exception)            # 基类，带 code / http_status
class MeowLLMConfigError(MeowLLMError)   # 配置非法
class MeowLLMSafetyError(MeowLLMError)   # 闸门拦截（>1B / 白名单）
class MeowLLMEngineError(MeowLLMError)   # 引擎加载/推理失败
class MeowLLMContractError(MeowLLMError) # 请求不符合契约
```
职责：所有错误统一带 `code`（如 `meowllm.safety.params_exceeded`）与 `http_status`，直接映射到响应里的 `meowllm.error`。

---

#### `meowllm/meowllm_config.py` · ≈220 行

```python
@dataclass class MeowLLMSection           # 不可变 key-value 视图，支持 a.b.c
class MeowLLMConfig:
    @classmethod load(cls, path: str | None = None) -> "MeowLLMConfig"
    def get(self, dotted: str, default=None)
    def validate(self) -> None            # 失败抛 MeowLLMConfigError
    # 结构属性
    server : MeowLLMSection   # host/port/port_fallback/request_timeout
    model  : MeowLLMSection   # name/path/quant/vision_encoder_dtype
    context: MeowLLMSection   # n_ctx/n_batch/n_ubatch/n_threads
    gen    : MeowLLMSection   # max_tokens/temperature/top_p/top_k/repeat_penalty/stop
    engine : MeowLLMSection   # kind/n_gpu_layers/load_in_4bit/flash_attn
    safety : MeowLLMSection   # allow_engine/max_local_model_params_b/require_env_override
    thinking: MeowLLMSection  # default_level/budgets/force_off_when_tools
    cache  : MeowLLMSection   # prefix/session/kv_quant/keep_alive
    queue  : MeowLLMSection   # max_concurrency/interactive_priority
    mirror : MeowLLMSection   # enabled/narrative_max_tokens/plan_next_max/salience_threshold
    vision : MeowLLMSection   # max_pixels/min_pixels/session_prefix
    stub   : MeowLLMSection   # reply/chunk_chars/chunk_delay_ms/emit_reasoning/.../sim
```

**职责**：读 `meowllm.yml`（根键 `meowllm:`）；`${ENV_VAR}` 展开；`MEOWLLM_*` 环境变量按 `MEOWLLM_SERVER__PORT` 形式覆盖；缺省值兜底。

**校验规则**（`validate`）：
1. `server.host` 必须是 `127.0.0.1` / `localhost`（**拒绝 `0.0.0.0`**）
2. `server.port` ∈ 1024–65535
3. `safety.allow_engine` 非空
4. `thinking.budgets` 键 ⊆ `{off,low,medium,high}` 且 `off == 0`
5. `context.n_ctx ≥ 1024`，`gen.max_tokens < context.n_ctx`
6. `engine.kind ∈ safety.allow_engine`，否则**启动就失败**（提前到 B1，不等工厂）

> 🔎 **请你确认**：我打算把"只允许回环"做成硬校验而不是仅文档约定。你若需要手机/局域网访问（项目 Flask 是 `0.0.0.0:1800`），这条要改成可配。

---

#### `meowllm/server/meowllm_schema.py` · ≈260 行

```python
class MeowLLMMessage(BaseModel):        role: Literal["system","user","assistant","tool"]
                                        content: str | list[dict] | None
                                        tool_calls / tool_call_id: ...
class MeowLLMTool(BaseModel):           type: Literal["function"] = "function"; function: dict
class MeowLLMToolChoice(BaseModel)      # "auto" | "none" | "required" | {"type":"function","function":{"name":...}}

class MeowLLMExtras(BaseModel):         # ← extra_body.meowllm 的全部字段
    thinking_level: Literal["off","low","medium","high"] | None
    think_budget: int | None
    session_id: str | None
    context_limit: int | None
    max_tokens: int | None
    cache: MeowLLMCacheOpt | None
    priority: Literal["interactive","background"] | None
    language: str | None

class MeowLLMChatRequest(BaseModel):    model/messages/tools/tool_choice/stream/max_tokens/
                                        temperature/top_p/top_k/stop/seed/stream_options
    def resolve(self, cfg: MeowLLMConfig) -> MeowLLMGenParams   # 请求级覆盖服务级

def parse_body(raw: dict) -> tuple[MeowLLMChatRequest, MeowLLMExtras]
def normalize_legacy_body(raw: dict) -> MeowLLMExtras           # ★ 兼容映射
```

**`normalize_legacy_body` 的映射表**（让现有 port 不改一行也能用）：

| 输入 | 映射到 |
|---|---|
| `extra_body.thinking.type == "disabled"` | `thinking_level=off` |
| `extra_body.thinking.type == "enabled"` | `thinking_level=medium` |
| `extra_body.parameters.enable_thinking == false` | `thinking_level=off` |
| 顶层 `reasoning_effort: low/medium/high/none` | 对应档位（`none`→off，`low` 保留为 low） |
| `tool_choice` 非空 | 强制 `thinking_level=off` |
| 未知字段 | 忽略，`logger.debug` 记录，**不报错** |

**参数优先级**：`extra_body.meowllm.*` > 顶层 OpenAI 标准字段 > `meowllm.yml` 默认值。

> 🔎 **请你确认**：`extra_body.meowllm` 与顶层字段冲突时，我按"meowllm 优先"。反过来也行，但那会让"项目侧标准字段"覆盖我们自己的调参，不利于灰度对照。

---

#### `meowllm/server/meowllm_stream.py` · ≈160 行

```python
class MeowLLMChunkWriter:
    def __init__(self, model: str, chunk_id: str | None = None)
    def content(self, text: str) -> dict
    def reasoning(self, text: str) -> dict
    def tool_call(self, index: int, *, call_id=None, name=None,
                  arguments_delta=None) -> dict
    def finish(self, reason: str) -> dict
    def meta(self, meta: dict) -> dict          # 顶层 meowllm 对象

def to_sse(obj: dict) -> bytes                  # b"data: {...}\n\n"
MEOWLLM_DONE: bytes = b"data: [DONE]\n\n"
def event_stream(events: AsyncIterator[MeowLLMGenEvent],
                 writer: MeowLLMChunkWriter) -> AsyncIterator[bytes]
```

**关键约束（来自 §1.4 的真实消费点）**：
- 同一个 `id` 贯穿整个流（`chatcmpl-` + 短 uuid）
- `object` 恒为 `chat.completion.chunk`，`created` 恒定
- `tool_call` 首片必须带 `id` + `type:"function"` + `function.name`；后续片只带 `index` + `arguments` 增量
- `role:"assistant"` 只在第一片的 `delta` 里出现一次
- 末片 `finish_reason` 非 null，之后才发 `[DONE]`

---

#### `meowllm/server/meowllm_app.py` · ≈160 行

```python
def create_app(cfg: MeowLLMConfig) -> FastAPI
    # lifespan: 建 engine → 起 mirror loop（若 enabled）→ 注册 atexit
    # include_router(v1), include_router(control)
    # exception_handler: MeowLLMError → JSON {meowllm:{error:{code,message}}}

def main(argv=None) -> int
    # 1) 解析 --config / MEOWLLM_CONFIG
    # 2) cfg.validate()
    # 3) bind 探测 18100..18108 → 写 state/meowllm/port.json
    # 4) uvicorn.run(app, host, port, log_level)
```
**依赖**：fastapi / uvicorn / pydantic（runtime/311 已有）

---

#### `meowllm/server/meowllm_routes_v1.py` · ≈320 行

```python
router = APIRouter(prefix="/meowllm/v1")

@router.post("/chat/completions")
async def meowllm_chat_completions(request: Request):
    #  1) parse_body → (req, extras)
    #  2) cfg 合并 → MeowLLMGenParams
    #  3) guard: tool_guard.subset(tools, hint)        [B2 前直通]
    #  4) 计数: engine.count_tokens(messages) → prefill_tokens
    #  5) 缓存: prefix_cache.key_of(...) → hit?
    #  6) mirror: 若 enabled → mirror_core.state_of(session) → apply_to_messages
    #  7) engine.generate(...)  [经 scheduler 排队]
    #  8) stream? event_stream() : 聚合为一个完整 ChatCompletion
    #  9) 每次响应注入 meowllm 元信息（cache/prefill_ms/ttfb_ms/decode_tps/...）

@router.get("/models")
async def meowllm_models()      # 返回 {"object":"list","data":[{"id": cfg.model.name, ...}]}
```

**非流式聚合**：内部仍走 `generate()`，把 content/reasoning 拼起来、`tool_calls` 按 index 合并，最后生成与流式同构的 `chat.completion`。→ 保证"流式拼接 == 非流式"这条自测能过。

> 🔎 **请你确认**：B1 是否需要 `/meowllm/v1/completions`（旧 text-completion）？我打算**不实现**——项目 70 处调用点全是 chat 接口。

---

#### `meowllm/server/meowllm_routes_control.py` · ≈200 行

```python
@router.get("/health")           # {"ready","engine","model","params_b","vram_mb","kv","uptime"}
@router.get("/stats")            # {"cache":{...},"perf":{...},"queue":{...},"counters":{...}}
@router.post("/think")           # body {session_id, history?} → ThinkState
@router.post("/session/reset")   # body {session_id} → 清 KV + ThinkState
@router.post("/reload")          # 重载 meowllm.yml（不重载权重）
@router.post("/selftest")        # 内嵌跑 12 项矩阵，返回逐项 PASS/FAIL
```
**`/stats` 必须包含**（§11 埋点）：`ttfb_p50/p95`、`prefill_tps`、`decode_tps`、`cache_hit_rate`、`cache_hit_rate_l2/l3/l4`、`vram_mb`、`kv_used_mb`、`queue_depth`、`timeout_count`、`empty_content_rate`、`tool_call_count`。

---

#### `meowllm/engine/meowllm_engine_base.py` · ≈180 行

```python
@dataclass class MeowLLMGenParams:
    max_tokens: int; temperature: float; top_p: float; top_k: int
    repeat_penalty: float; stop: list[str]; seed: int | None
    thinking_level: str; think_budget: int
    tools: list[dict] | None; tool_choice: Any
    cache_key: str | None; session_id: str | None

@dataclass class MeowLLMGenEvent:
    kind: Literal["content","reasoning","tool_call","finish","meta"]
    text: str = ""; index: int = 0; call_id: str | None = None
    name: str | None = None; arguments_delta: str | None = None
    finish_reason: str | None = None; meta: dict | None = None

class MeowLLMEngineBase(ABC):
    kind: str = "abstract"
    @abstractmethod def load(self) -> None
    @abstractmethod def unload(self) -> None
    @abstractmethod def info(self) -> dict          # {engine,model,params_b,quant,n_ctx,vram_mb}
    @abstractmethod def count_tokens(self, messages: list[dict]) -> int
    @abstractmethod def build_prompt(self, messages, tools, params) -> str
    @abstractmethod async def generate(self, prompt: str,
                                       params: MeowLLMGenParams
                                       ) -> AsyncIterator[MeowLLMGenEvent]
    def kv_slot_stats(self) -> dict                 # 默认 {}
    def cache_take(self, key: str) -> str | None    # 默认 None（无 KV 复用能力）
    def cache_give(self, key: str, handle: str) -> None
```

**设计要点**：
- 上层（routes）只认这个接口 → 换引擎不动上层
- `cache_take/give` 是**L3 MIRROR 共享前缀**的挂钩点；stub 返回 None，真引擎才实现
- `generate` 是 async generator → 天然适配 SSE，不需要线程

---

#### `meowllm/engine/meowllm_engine_factory.py` · ≈160 行

```python
def create(cfg: MeowLLMConfig) -> MeowLLMEngineBase      # 详见 §7.2 三道闸
def probe_params_b(path: str) -> float                   # 读不到返回 inf
def _probe_hf(path) -> float                             # config.json: num_parameters / 按层粗算
def _probe_gguf(path) -> float                           # GGUF metadata: general.parameter_count
```

**三道闸门（把 C4 变成代码）**：
1. `engine.kind ∈ safety.allow_engine`（本机只有 `stub`）
2. 非 stub 且 `require_env_override` → 必须 `MEOWLLM_ALLOW_LOCAL_MODEL=1`
3. 非 stub → `probe_params_b() > max_local_model_params_b`（默认 1.0）→ 拒绝启动；读不到按 `inf` 拒绝

> 🔎 **请你确认**：`probe_params_b` 读不到参数时，你要"拒绝"还是"警告后放行"？我按**拒绝**设计（fail-closed），因为你的约束是"绝对禁止"。

---

#### `meowllm/engine/meowllm_engine_stub.py` · ≈200 行

```python
class MeowLLMEngineStub(MeowLLMEngineBase):
    kind = "stub"
    def load(self)        # no-op；日志醒目打印 "STUB：未加载任何权重"
    def info(self)        # {"engine":"stub","params_b":0.0,"quant":"none","n_ctx":cfg.context.n_ctx}
    def count_tokens(self, messages) -> int      # 中文近似：1 token ≈ 1.6 字符
    def build_prompt(self, messages, tools, params) -> str   # "role: content" 拼接 + <<TOOLS:n>>
    async def generate(self, prompt, params) -> AsyncIterator[MeowLLMGenEvent]
```

**`generate` 的行为（完全由 `meowllm.stub.*` 控制）**：
1. 若 `emit_reasoning`：先吐 `ceil(reasoning_chars/chunk_chars)` 个 `reasoning` 事件（受 `think_budget` 截断 → 验证预算强制）
2. 若 `tool_call` 配置了：吐 `parallel_tools` 组 `tool_call` 事件，`arguments` 按 `split_arguments` 字符切片（→ 验证 `ToolCallAccumulator` 增量合并）
3. 再吐 `content` 事件，按 `chunk_chars` 切
4. 每个事件之间 `await asyncio.sleep(chunk_delay_ms/1000)`
5. 末事件 `finish(finish_reason)`；`meta` 里带仿真 `prefill_ms = prefill_tokens/sim.prefill_tps*1000`、`decode_tps = sim.decode_tps`

**为什么这样设计**：stub 不是"假回复"，而是**可控的时序与形状发生器**。本机唯一能验证的东西（契约 + 缓存账本 + 预算强制）都靠它。

> 🔎 **请你确认**：`count_tokens` 用"1 token ≈ 1.6 中文字符"的近似，而不是引入真 tokenizer。引入 Qwen tokenizer 需要 `transformers`（已装但会拖入更多依赖且需要下载 tokenizer 文件）。**近似是否够用**？缓存命中判断靠的是"同样的 messages 得到同样的 key"，近似不会影响正确性，只影响统计数字。

---

#### `meowllm/cache/meowllm_cache_prefix.py` · ≈180 行

```python
@dataclass class MeowLLMSlot:  key: str; slot_id: str; tokens: int; created: float; hits: int
class MeowLLMPrefixCache:
    def __init__(self, slots: int, min_prefix_tokens: int)
    def stable_prefix(self, messages) -> list[dict]   # ★ 稳定段切分
    def key_of(self, messages) -> tuple[str, int]     # (sha1, tokens)；tokens < min → ("",0)
    def lookup(self, key) -> MeowLLMSlot | None
    def give(self, key, slot_id, tokens) -> None
    def stats(self) -> dict                            # hits/misses/hit_rate/cached_tokens
```

**★ `stable_prefix` 是这一层的核心算法**：

```
messages = [system, ...history, user]
稳定段 = 从 system 起，一直取到"最后一条 user 之前"的所有消息
        且要求 system 首部连续稳定（遇到第一个易变标记即停）
易变标记（有序）: "# 现在是" / "我心里装着的" / "# 当前情绪"
```
→ 目的是把 3–6k token 的系统提示里"确实稳定的那段"抽出来做 key，而不是拿整段（整段每轮都变，永远 miss）。

> 🔎 **这是最需要你拍板的一处**：这等于让 MeowLLM **知道项目提示词的内部结构**（知道 `# 现在是` 这类标题）。这算不算"耦合原项目"？
> 我的看法：可以接受，因为①它只是字符串匹配，不改项目；②做成 `meowllm.yml` 里的可配列表，默认给一组，项目改了提示词只改配置。
> 另一个方案是**完全不管语义**：让项目侧传 `meowllm.cache.pin_prefix: "system 前 N 个 token"`。但那要改项目。你选哪个？

---

#### `meowllm/cache/meowllm_cache_session.py` · ≈130 行

```python
@dataclass class MeowLLMSession: sid: str; tokens: int; last: float; slot_id: str | None
class MeowLLMSessionCache:
    def __init__(self, max_sessions: int, ttl_seconds: int)
    def get(self, sid) -> MeowLLMSession | None
    def touch(self, sid, tokens_delta: int) -> MeowLLMSession
    def reset(self, sid) -> None
    def evict_expired(self) -> int
    def stats(self) -> dict
```
职责：per-meowid 会话记账 + TTL/LRU 淘汰。B1 只记账（stub 无真 KV），B3 才把 `slot_id` 交给真引擎。

---

#### `meowllm/tools/meowllm_tool_parse.py` · ≈120 行

```python
def parse_tool_args(raw: str) -> dict
    # 容错：截断补 }、去尾逗号、中文引号 → 英文、单引号 → 双引号
    # 失败返回 {}，绝不抛
class MeowLLMToolCallBuilder:            # 服务端镜像 ToolCallAccumulator，供自测断言
    def add(self, event: MeowLLMGenEvent) -> None
    def has_calls(self) -> bool
    def payload(self) -> list[dict]
```
**为什么要这个镜像**：自测要断言"我们发的分片，能被项目那套累积器正确还原"。把项目的累积逻辑抄一份到 MeowLLM 侧做交叉验证（**不改项目**）。若两边结果不一致 → 说明分片形状有问题。

---

#### `meowllm/meowllm_scheduler.py` · ≈110 行

```python
class MeowLLMScheduler:
    def __init__(self, max_concurrency: int, interactive_first: bool)
    async def submit(self, priority: str, coro) -> Any
    def stats(self) -> dict          # queue_depth / running / waited_ms
```
职责：单卡默认并发 1；`interactive` 先出，`background`（记忆摘要/价值观）等。用 `asyncio.PriorityQueue` + 信号量。

---

#### `meowllm/vision/meowllm_vision_encode.py` · ≈150 行

```python
def decode_data_url(url: str) -> tuple[bytes, str]        # (data, mime)
def probe_size(data: bytes) -> tuple[int, int]            # 解析 PNG/JPEG 头，不解码全图
def cap_pixels(data, max_pixels, min_pixels) -> bytes     # 超限则缩放（B1 用 PIL）
def count_vision_tokens(w: int, h: int) -> int            # ceil(w/28)*ceil(h/28) 量级
def collect_images(messages) -> list[dict]                # 从 content 数组里挑 type==image_url
```
**B1 范围**：解析 + 探测 + 计数 + 回显。缩放用 PIL（已装），不依赖 torch。

---

#### `bin/meowllm_start.ps1` · ≈120 行

```powershell
param([string]$Config = "meowllm.yml", [switch]$NoModel, [switch]$Background)
# 1) 读 meowllm.yml，$NoModel 时强制 engine.kind=stub
# 2) 试绑 18100..18108，选第一个空闲
# 3) Start-Process runtime\311\python.exe -ArgumentList "-m","meowllm.server.meowllm_app"
# 4) 轮询 http://127.0.0.1:$port/meowllm/control/health 直到 ready（超时 60s）
# 5) 打印 "MEOWLLM READY on 127.0.0.1:$port  engine=stub"
# 6) 写 state/meowllm/port.json
```

---

#### `bin/meowllm_selftest.py` · ≈350 行

跑 §7.4 的 12 项矩阵，逐项 `PASS/FAIL` 表格 + 汇总 + 退出码（CI 友好）。每项打印实际值，便于看数字而不是只看红绿。

---

#### `bin/meowllm_project_probe.py` · ≈220 行

```python
# 用项目真正的 port 类打我们的 stub，而不是 openai SDK 裸测
os.environ["MEOWLLM_BASE_URL"] = f"http://127.0.0.1:{port}/meowllm/v1"
from func.llm.config import LLMConfig
cfg = LLMConfig(); cfg.deepseek_base_url = ...; cfg.deepseek_api_key = "meowllm"
from func.llm.port.deepseek import DeepSeekLLM          # 族 1 chat_stream
from func.toolbox.port.deepseek import TBoxDeepSeekLLM  # 族 3 chat + chat_stream(thinking_level)
from func.toolbox.meowvision.port.aliyun import TBVisionAliyunLLM   # 族 4 多模态 data URL
# 逐族断言：不抛异常 / content 正确 / tool_calls 可合并 / reasoning_content 可读 / llm.client 可判真
```
**必须在项目根目录运行**（`sys.path` 要能找到 `func`）。它**不修改** `config.yml`，只在内存里覆盖 `base_url`。

> 🔎 **请你确认**：这个脚本会 import 项目的 `func.llm.*`，会触发 `ConfigReader` 读 `config.yml`。如果你的 `config.yml` 里有会联网/起线程的初始化，可能在 probe 时被连带执行。**要不要我加一个"只导入 port 模块、不 import llm_core/active_core"的白名单**？我倾向于加。

---

### 1.4 B2 模块（MIRROR 认知层）

| 文件 | 类/函数 | 职责 | 行数 |
|---|---|---|---|
| `meowllm/mirror/meowllm_mirror_state.py` | `MeowLLMThinkState` / `MeowLLMThinkStore` | ThinkState 落盘 `state/meowllm/mirror/<sid>.json`；**写前强制截断**（thinking ≤1.5k token、plan_next ≤3） | 170 |
| `meowllm/mirror/meowllm_mirror_prompt.py` | `talker_block()` / `thinker_messages()` / `MEOWLLM_THINKER_SCHEMA` | Talker 分区文本（拼在项目 system **之后**）；Thinker 的 JSON 约束 schema | 150 |
| `meowllm/mirror/meowllm_mirror_core.py` | `MeowLLMMirrorCore` | 状态机 IDLE→TALK→THINK；`think()` / `apply_to_messages()` | 200 |
| `meowllm/mirror/meowllm_mirror_loop.py` | `MeowLLMThinkLoop` | 后台 asyncio task；salience 门控（琐碎轮跳过）；TALK 结束后续跑 | 140 |
| `meowllm/tools/meowllm_tool_guard.py` | `MeowLLMToolGuard` | 工具子集化（默认 ≤8）+ JSON Schema→语法约束（接 `outlines`/`xgrammar`）+ 强制单函数预填 | 200 |
| `meowllm/vision/meowllm_vision_template.py` | `extract_images()` / `to_engine_image()` | messages 抽图、转各引擎格式 | 110 |

**B2 的关键设计选择**：
- MIRROR 分区**拼在项目 system 之后**，保证项目 system 仍是稳定前缀 → 不破坏 L2 缓存
- `mirror.enabled: false` 时整层是透明的（消息原样透传）→ 便于 A/B 对照
- Thinker 的调用走同一个 `engine.generate()`，但 `priority=background` + `thinking_level=high`

> 🔎 **请你确认**：B2 的 `thinker_messages` 是否要**完全不给原始对话史**（MIRROR 论文的"认知控制器无原始史"约束）？我按"只给最近 3 轮 + 上次 narrative"实现，比论文宽松一点（论文是完全不给）。你要严格按论文的话，Thinker 只看 3 条 thread 输出。

### 1.5 B3 模块（真实引擎）

| 文件 | 类 | 接入方式 | 关键点 | 行数 |
|---|---|---|---|---|
| `engine/meowllm_engine_llamacpp.py` | `MeowLLMEngineLlamaCpp` | **子进程**：起 `llama-server`，我们代理 | `--jinja`（工具调用必需）、`--reasoning-format deepseek`（吐 `reasoning_content`）、`--cache-prompt`、`--slot-save-path`、`--mmproj`（视觉）、**必须显式 `--port`**（v0.7.0 起默认改 9931） | 420 |
| `engine/meowllm_engine_hf.py` | `MeowLLMEngineHf` | **进程内**：`transformers` + AWQ/GPTQ/NF4 | 自管 `DynamicCache` 前缀复用；视觉塔 fp16；`bad_words`/`stop` 手写循环 | 460 |
| `engine/meowllm_engine_vllm.py` | `MeowLLMEngineVllm` | **子进程**：`vllm serve` + 代理 | `--enable-prefix-caching`、`--limit-mm-per-prompt`、`--max-model-len` | 320 |

**引擎接入方式（请你拍板）**

| 模式 | 优点 | 缺点 | 适用 |
|---|---|---|---|
| **子进程 + 代理**（推荐 llamacpp/vllm） | 不动命名空间；引擎自带 prefix cache 与视觉；崩溃隔离；不用编译 | 多一跳 HTTP（本机 <1ms，可忽略）；KV 由引擎管，我们只能观测 | 云端 V1/V2 主流 |
| **进程内**（hf） | 完全自研；KV 由我们掌控（L3 MIRROR 共享前缀最好实现） | 重、要编译、崩了带死服务 | 将来需要精确 KV 控制时 |

> 🔎 **请你确认**：B3 最小可用集合，我建议**只先做 `llamacpp` 一个**（子进程模式），云端 V1 用它跑 Qwen3-VL-8B GGUF 就能拿到真实 TPS 与缓存命中。`hf` 与 `vllm` 等 V1 有数据后再决定。**同意吗？**

### 1.6 明确**不**做的（避免范围蔓延）

- ❌ `/meowllm/v1/completions`（旧 text-completion）
- ❌ `/meowllm/v1/embeddings`（项目的 embedding 走 `database/store/port`，另议）
- ❌ 鉴权 / API key 校验（只绑回环）
- ❌ 多卡 / 张量并行 / 连续批处理调度（B3 交给 vLLM）
- ❌ δ-mem / attention hook / LoRA / 训练（C1）
- ❌ GGUF 量化转换（用现成 GGUF 或云端工具链）
- ❌ 模型下载器（C2：你自己下）

---

## 第二部分 · llama.cpp 选型与信息采集

### 2.1 先看一个硬事实：本机驱动卡在 CUDA 12.8

我刚在你机器上实测：

```
NVIDIA-SMI 573.22      Driver Version: 573.22      CUDA Version: 12.8
GPU : NVIDIA GeForce RTX 5060 Laptop GPU     VRAM: 8151 MiB (7.96 GiB)
compute capability : sm_120  (Blackwell)
torch : 2.11.0+cu128,  CUDA available = True
```

这两条组合起来就排除了官方 Windows 的两个 CUDA 预编译包：

| 官方 Windows 构建 | 能否用 | 原因 |
|---|---|---|
| `win-cuda-12.4-x64` | ❌ | CUDA 12.4 早于 Blackwell，**不含 sm_120 内核**（sm_120 自 CUDA 12.8 才有）→ CUDA 后端加载失败，退回 CPU |
| `win-cuda-13.4-x64` | ❌ | CUDA 13.x 运行时要求驱动 **≥ R580**，你是 **573.22**（上限 CUDA 12.8） |
| `win-vulkan-x64` | ✅ | Vulkan 只走显卡驱动，不绑定 CUDA 版本，Blackwell 可用 |
| `win-cpu-x64` | ⚠️ | 能跑但极慢，只够验证"能不能加载" |

**结论**：
1. 按 C4（本机不跑模型、禁 >1B），**本机其实不需要下载 llama.cpp**。
2. 若你以后想在本机做一次 ≤1B 冒烟，两条路：**① 用 `win-vulkan-x64`**；**② 把 NVIDIA 驱动升到 ≥580 再用 `win-cuda-13.4`**（升驱动影响面更大，不推荐仅为测试升级）。
3. 官方**没有** Windows 的 `cuda-12.8` 构建，所以"12.8 驱动 + CUDA 构建"这条路在本机不通。

### 2.2 云端（Ubuntu 22.04 / CUDA 12.8 / PyTorch 2.8.0 / Python 3.12）

好消息：官方**正好有 `ubuntu-cuda-12.8-x64` 资产**，与你的 CUDA 12.8 完全对齐，不需要装 CUDA Toolkit、不需要编译。

| 要下 | 资产名（模式） | 体积（b11669 实测） |
|---|---|---|
| CUDA 运行时库 | `cudart-llama-b<NNNNN>-bin-ubuntu-cuda-12.8-x64.tar.gz` | **567 MB** |
| 主程序 | `llama-b<NNNNN>-bin-ubuntu-cuda-12.8-x64.tar.gz` | **165 MB** |

两个都要（cudart 包提供 `libcudart` / `libcublas` 等，免装 Toolkit）。
解压后必须 `export LD_LIBRARY_PATH=<解压目录>:$LD_LIBRARY_PATH`。

### 2.3 云端到底用 llama.cpp 还是 vLLM

| 维度 | llama.cpp（GGUF） | vLLM |
|---|---|---|
| 前缀缓存 | `--cache-prompt` + slot 文件（要自己管 slot） | **`--enable-prefix-caching` 自动，按 block 哈希** |
| 连续批处理 | `-np` 多 slot，非真批处理 | ✅ 原生 |
| 量化 | GGUF 全档（Q4_K_M…Q8_0） | AWQ/GPTQ/FP8（需预量化权重） |
| 视觉 | `--mmproj`，成熟 | `--limit-mm-per-prompt`，新版 Qwen3-VL 支持 |
| 安装难度 | **解压即用**（推荐先上） | pip 依赖链重，可能动 torch |
| 与你的 CUDA 12.8 | ✅ 有对应预编译 | 需匹配 wheel 的 cu 版本 |
| 对你"缓存命中/TPS"目标 | 中（够用） | **最好** |

**建议路线**：
- **V1（第一次真跑）用 llama.cpp** —— 解压即用，最快拿到真实 TPS / 缓存命中 / 工具调用 / 视觉四条数据。
- **V2（27B 上生产）再评估 vLLM** —— 那时才需要连续批处理与自动前缀缓存。

⚠️ **vLLM 千万不要装进你现在这个 PyTorch 2.8.0 环境**。vLLM 会 pin 自己的 torch 版本，装进去会把你现有环境搅乱。要装就单独 venv：
```bash
uv venv --python 3.12 ~/vllm-env && source ~/vllm-env/bin/activate
uv pip install vllm --torch-backend auto     # 让它自己选匹配的 torch
```

### 2.4 怎么拿到"该下哪个版本"（不写死 b 号）

llama.cpp 的二进制挂在**夜版 tag `bNNNNN`** 上，而 `releases/latest` 是语义版本（如 `v0.7.0`），它的 release note 里写着 `**Nightly build:** [b11669](...)`。所以正确做法是**每次现查**，我把探测脚本给你，你复制粘贴即可。

#### Windows（本机，PowerShell）

```powershell
# ---- 1) 采集本机事实 ----
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
& 'D:\.Meowlisis\runtime\311\python.exe' -c "import torch;print('sm_%d%d'%torch.cuda.get_device_capability(0),'| cuda',torch.version.cuda,'| torch',torch.__version__)"

# ---- 2) 查最新夜版号 ----
$h = @{ 'User-Agent' = 'meowllm' }
$rel = Invoke-RestMethod -Uri 'https://api.github.com/repos/ggml-org/llama.cpp/releases/latest' -Headers $h
$tag = if ($rel.body -match 'Nightly build:\*\*.*?(b\d+)') { $Matches[1] } else { $null }
"语义版本: $($rel.tag_name)   夜版: $tag"

# ---- 3) 列出该夜版的 Windows 资产（名字 / 大小 / 直链）----
$n = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$tag" -Headers $h
$n.assets | Where-Object { $_.name -match 'win' } |
    Select-Object name, @{n='MB';e={[math]::Round($_.size/1MB)}}, browser_download_url |
    Sort-Object name | Format-Table -AutoSize -Wrap
```

**怎么读输出**：按 §2.1 的结论，在你这台机器上只应关注 `win-vulkan-x64`（和 `win-cpu-x64` 作兜底）。若你后来把驱动升到 ≥580，再考虑 `win-cuda-13.4-x64` 及其配套 `cudart-llama-bin-win-cuda-13.4-x64.zip`。

#### Linux（云端，bash）

```bash
# ---- 1) 采集云端事实 ----
nvidia-smi
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
python3 -c "import torch;print('torch',torch.__version__,'| cuda',torch.version.cuda,'| sm_%d%d'%torch.cuda.get_device_capability(0))"
lsb_release -a; uname -r; python3 -V; nproc; free -g; df -h /root
# 注意 nvidia-smi 右上角的 "CUDA Version:" = 这台机器驱动能支持的最高 CUDA

# ---- 2) 查最新夜版号 ----
curl -s -H 'User-Agent: meowllm' \
  https://api.github.com/repos/ggml-org/llama.cpp/releases/latest \
| python3 -c "import sys,json,re;d=json.load(sys.stdin);m=re.search(r'Nightly build:.*?(b\d+)',d['body']);print('语义',d['tag_name'],'| 夜版',m.group(1) if m else '未找到')"

# ---- 3) 列出 CUDA 12.8 相关资产 ----
TAG=b11669        # ← 换成上一步查到的号
curl -s -H 'User-Agent: meowllm' \
  "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$TAG" \
| python3 -c "
import sys,json
d=json.load(sys.stdin)
for a in d['assets']:
    if 'ubuntu' in a['name'] and 'cuda-12.8' in a['name']:
        print(f\"{a['size']/1048576:8.1f} MB  {a['name']}\n          {a['browser_download_url']}\")
"
```

#### 决策规则（采集完照这张表走）

| `compute_cap` | 驱动支持的 CUDA | 云端该下 | 本机该下 |
|---|---|---|---|
| sm_90 (H100/A100-H) | 12.4 | `ubuntu-cuda-12.8-x64`（向下兼容） | — |
| **sm_120 (RTX 50 / Blackwell)** | **12.8** | **`ubuntu-cuda-12.8-x64`** ✅ | `win-vulkan-x64` |
| sm_120 | ≥13.0（驱动 ≥580） | `ubuntu-cuda-13.4-x64` | `win-cuda-13.4-x64` |
| sm_86/sm_89 (3090/4090) | 12.8 | `ubuntu-cuda-12.8-x64` | 驱动≥550 可用 `win-cuda-12.4` |

> **一个坑**：`nvidia-smi` 显示的 CUDA Version 是**驱动上限**，不是已安装的 Toolkit。只要驱动上限 ≥ 构建所用 CUDA，就能跑（向前兼容靠 PTX，但**跨大版本不保证**）。所以"驱动的 CUDA 上限"必须 **≥** 资产的 CUDA 版本。

### 2.5 视觉模型要额外两个文件

llama.cpp 跑 Qwen3-VL 需要 **GGUF 主体 + 视觉投射器 `mmproj-*.gguf`**，两个都要下：

```bash
# 预期命名（以 HF 仓库实际文件为准）
Qwen3-VL-8B-Instruct-Q4_K_M.gguf        ≈ 5–6 GB
mmproj-Qwen3-VL-8B-Instruct-f16.gguf    ≈ 0.8–1.4 GB
```
启动时用 `--mmproj` 指定第二个。**少这个文件 = 视觉完全不可用**，这一点最容易漏。

### 2.6 启动参数建议（B3 落地时用）

```bash
# 云端 llama.cpp + Qwen3-VL-8B（示例，参数名以 llama-server --help 为准）
./llama-server \
  -m   Qwen3-VL-8B-Instruct-Q4_K_M.gguf \
  --mmproj mmproj-Qwen3-VL-8B-Instruct-f16.gguf \
  --host 127.0.0.1 --port 18110 \        # ★ 必须显式指定（v0.7.0 起默认改成 9931）
  -c 16384 -b 512 -ub 512 \
  -ngl 99 \                              # 全量卸载到显存
  -np 4 \                                # 4 个 slot，配合会话 KV
  --jinja \                              # ★ 工具调用必需（jinja chat template）
  --reasoning-format deepseek \          # ★ 让思考内容走 reasoning_content
  --cache-prompt \                       # ★ 前缀缓存
  --slot-save-path ./slots               # ★ 会话 KV 落盘（L3/L4 用）
```

三个星号是**必须**，缺任意一个都会直接打掉我们的一个核心能力：
- 缺 `--jinja` → 工具调用不可用（项目 62 处 `llm.chat(tools=…)` 全废）
- 缺 `--reasoning-format deepseek` → `delta.reasoning_content` 为空（`napcat_llm.py` 那条链路看不到思考）
- 缺 `--cache-prompt` / `--slot-save-path` → 缓存命中率 ≈ 0，语音链路首字延迟不可接受

### 2.7 与 MeowLLM 端口的关系（不冲突）

llama.cpp v0.7.0 起 `llama-server` 默认端口改为 **9931**（原来是 8080）。MeowLLM 自己的对外端口仍是 **18100**，llama-server 作为**内部子进程**监听 `127.0.0.1:18110`（不回环外的任何东西、不对外暴露）。

```
项目 ──HTTP──► MeowLLM :18100 /meowllm/v1/*      ← 唯一对外
                    │
                    └─内部──► llama-server :18110  ← 只绑回环，仅本机子进程访问
```

---

## 第三部分 · 需要你拍板的 8 个点

| # | 问题 | 我的默认选择 | 你的意见 |
|---|---|---|---|
| 1 | B1/B2/B3 分批节奏认可吗？ | 先只做 B1（≈2900 行，零下载可跑） | |
| 2 | `server.host` 强制 `127.0.0.1` 作为**硬校验**（拒绝 0.0.0.0）？ | 是 | |
| 3 | `extra_body.meowllm` 与顶层标准字段冲突时谁优先？ | meowllm 优先 | |
| 4 | 不实现 `/meowllm/v1/completions`？ | 不实现（70 处全是 chat） | |
| 5 | `probe_params_b` 读不到参数量时**拒绝启动**？ | 拒绝（fail-closed） | |
| 6 | `stable_prefix` 是否允许 MeowLLM 识别项目提示词的标题（如 `# 现在是`）来做稳定段切分？ | 允许，且做成 `meowllm.yml` 可配列表 | |
| 7 | Thinker 是否严格按论文"完全不给原始对话史"？ | 放宽到"最近 3 轮 + 上次 narrative" | |
| 8 | B3 先只做 `llamacpp`（子进程模式），`hf`/`vllm` 延后？ | 是 | |

## 附：还差你提供的一条信息

云端那台机器的 **`nvidia-smi` 右上角 "CUDA Version:"** 和 **`compute_cap`**。你只给了"CUDA 12.8"，但 12.8 可能是驱动上限、也可能是已装 Toolkit。跑一下 §2.4 的 Linux 第 1 段，把输出贴给我，我就能确定：

- 该下 `ubuntu-cuda-12.8-x64` 还是需要别的
- 24G 卡能不能 `bf16` 直跑 Qwen3-VL-8B（不用量化），还是必须 AWQ
- `n_ctx` 能开多大
