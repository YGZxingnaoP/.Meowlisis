# PLAN · MeowLLM 实施规格（V2 · 按评审意见修订）

> **相对 V1 的变更**：① 文件名去掉 `meowllm` 前缀（类名保留 `MeowLLM*`）② 新增 Vulkan vs CUDA 决策依据 ③ 批次重排为 **MIRROR + llama.cpp 优先** ④ 新增极小模型加载可行性测试 T0–T3 ⑤ 本机 Vulkan 实测结论。
> **配套**：`PLAN_MeowLLM_本地模型接入方案.md`（架构/命名/端口/缓存/验收）

---

## 0. 本轮四条意见的落地

| 你的意见 | 落地 |
|---|---|
| 1. 文件名不要 `meowllm` 前缀，类名要 | 文件改 `config.py` / `schema.py` / `engine/llamacpp.py` …；类名全部保留 `MeowLLM*`。包根目录仍叫 `meowllm/`（那是命名空间，不是前缀）→ §3 |
| 2. Vulkan 与 CUDA 区别 | → §2 完整对比 + 本机实测结论 |
| 3. `bags` 已有压缩包、AutoDL 有登录信息 | 已实测校验三份包完整可用 → §1 |
| 4. 改方案：准备实施 MIRROR + llama.cpp，给极小模型测试 | 批次重排 → §4；llama.cpp 引擎规格 → §6；MIRROR → §7；极小模型测试 → §8 |

---

## 1. 已到位资源（我逐项实测校验过）

### 1.1 `bags/`

| 文件 | 体积 | 校验结果 |
|---|---|---|
| `llama-b11669-bin-win-vulkan-x64.zip` | 30.69 MB | ✅ 52 个条目。`llama-server.exe` / `llama-server-impl.dll`(8.83MB) / `llama-cli.exe` / `llama-bench.exe` / `llama-mtmd-cli.exe` / `mtmd.dll` / `ggml-vulkan.dll`(39.61MB) / `ggml-cpu-x64.dll` 全在。**纯 Vulkan + CPU，无 `ggml-cuda.dll`** |
| `llama-b11669-bin-ubuntu-cuda-12.8-x64.tar.gz` | 164.53 MB | ✅ 51 个文件。`libggml-cuda.so`(169.39MB) / `libllama-server-impl.so` / `libmtmd.so` / `llama-cli` |
| `cudart-llama-b11669-bin-ubuntu-cuda-12.8-x64.tar.gz` | 566.84 MB | ✅ 3 个库：`libcublasLt.so.12`(716.95MB) / `libcublas.so.12`(111MB) / `libcudart.so.12` |

**版本确认**：`llama-cli --version` → `0.7.0-dev (build 11669, commit 620d2225c)`，与 `libllama-common.so.0.7.0` 一致。**b11669 = v0.7.0 对应夜版**，正是我上一轮预测的那一版。三份都选对了。

### 1.2 本机 Vulkan 实测（这是本轮最重要的发现）

我把 Vulkan 包解到临时目录跑 `llama-cli --list-devices`：

```
Available devices:
  Vulkan0: Intel(R) RaptorLake-S Mobile Graphics Controller (16239 MiB, 15471 MiB free)
  Vulkan1: NVIDIA GeForce RTX 5060 Laptop GPU (7810 MiB, 7042 MiB free)
```

**结论一：Vulkan 在这台机器上可用**，独显被正确识别（7810 MiB 可用）。
（`nvidia-smi` 显示 8151 MiB，Vulkan 报 7810 MiB，差值约 340 MB 是驱动/桌面预留。）

**结论二（坑）：`Vulkan0` 是 Intel 核显，llama.cpp 默认用 device 0。**
不显式指定的话，模型会跑在 Intel 核显上 —— 慢 30–50 倍，而且会吃掉系统内存。**必须 `-dev Vulkan1`**。

`vulkan-1.dll` 系统已有（`C:\Windows\System32\vulkan-1.dll`, 1557 KB），NVIDIA 的 ICD（`nvoglv64.dll`）在 `DriverStore\FileRepository\nvtf.inf_amd64_b7e28e107e520f55\`，所以**不需要装 Vulkan SDK**。

### 1.3 AutoDL

`autoDL/登录指令.txt`：`ssh -p 43080 root@connect.weste.seetacloud.com`（46 字节）
`autoDL/密码.txt`：12 字节，**我没有回显密码内容**。

> 建议：这两个文件请你自己确认是否已加入 `.gitignore`。`.vendor` 下目前只有 `*.gguf`/`*.safetensors` 被忽略，**`autoDL/密码.txt` 不在忽略名单里**，存在被提交进仓库的风险。建议加：
> ```gitignore
> .vendor/.MeowLLM/autoDL/
> ```

---

## 2. Vulkan vs CUDA（回答你的问题）

### 2.1 本质区别：不是"两个显卡驱动"，而是两套完全不同的编译与执行模型

| | **CUDA** | **Vulkan** |
|---|---|---|
| 归属 | NVIDIA 私有 | Khronos 开放标准（跨厂商） |
| llama.cpp 后端 | `ggml-cuda` | `ggml-vulkan` |
| 内核用什么写 | CUDA C++（`.cu`） | GLSL/HLSL → **SPIR-V** |
| 什么时候编译成机器码 | **构建时**：nvcc 编译成 SASS，指定 `-arch=sm_XX` | **运行时**：驱动里的着色器编译器 JIT 编译 SPIR-V |
| 产物 | 每个 GPU 架构一份 SASS（+可能带 PTX 兜底） | 一份 `.dll/.so` 通吃，靠驱动现场编译 |
| 驱动要求 | 驱动支持的 CUDA 上限 **必须 ≥** 构建所用 CUDA | 只要有该厂商的 Vulkan 驱动 |
| 跨厂商 | ❌ 只 NVIDIA | ✅ NVIDIA / AMD / Intel / 高通 / Apple(MoltenVK) |

**这一条差异直接决定了本机的处境**：
- CUDA 走"构建时绑定架构"，所以 `sm_120`（Blackwell）必须用 CUDA **≥12.8** 编译的二进制；而官方 Windows 只有 12.4 和 13.4 两档，你的驱动又卡在 CUDA 12.8 → 两头都够不着。
- Vulkan 走"运行时 JIT"，一份二进制在任何 NVIDIA 驱动上都能跑 → **本机唯一可行**。

### 2.2 性能差异（这是你最该关心的）

| 维度 | CUDA | Vulkan | 实测经验 |
|---|---|---|---|
| **量化内核覆盖度** | 最全。Q2_K…Q8_0、IQ1_S…IQ4_XS、MXFP4 全有专用 MMQ 内核 | 覆盖主流（Q4_K/Q5_K/Q6_K/Q8_0/Q4_0/IQ2…），冷门量化可能走通用路径或不可用 | CUDA 更稳 |
| **张量核心利用** | MMA / MMQ 手工调优，历史最久 | coopmat / coopmat2 路径可用上张量核心，近年进步很大 | **Vulkan 约为 CUDA 的 85–100%**（Q4_K_M/Q8_0 常见档位），个别配置持平甚至略高 |
| **Flash Attention** | 内核最全（head size / 量化组合覆盖广） | 支持，但组合少一些 | 长上下文时 CUDA 优势更明显 |
| **MoE（`mul_mat_id`）** | 专用内核多 | 有，特化少 | 对稠密 27B 影响不大 |
| **首次调用延迟** | 加载预编译 SASS，**快**（除非只有 PTX 要 JIT） | **首次要编译着色器流水线 → 明显尖峰**，之后靠 pipeline cache | 影响 TTFB，需 warmup |
| **显存占用** | 精细控制（pinned、统一内存） | 走驱动分配，通常接近 | 差别不大 |
| **多卡** | `-sm layer/row/tensor` + P2P 成熟 | 多 GPU 可用，P2P 依赖驱动 | 大模型多卡选 CUDA |
| **bf16 / fp8** | 完整 | bf16 依赖驱动扩展，fp8 基本没有 | 我们用 fp16 计算，够 |

**⚠️ 一个实践中的大坑（本机正好撞上）**：Vulkan 会把**所有** GPU 都列出来，包括核显。`-list-devices` 里 `Vulkan0` 是 Intel UHD、`Vulkan1` 才是 5060。默认 `-mg 0` / 不指定 `-dev` 就会跑核显上。**必须显式指定。**

### 2.3 稳定性 / 运维差异

| | CUDA | Vulkan |
|---|---|---|
| 崩溃风险 | 后端成熟，问题少 | 某些驱动的着色器编译器有 bug，遇到冷门量化/超长上下文可能崩或算错 |
| 出错可诊断性 | `nvidia-smi` + nvtop 直接看 | 需 `vulkaninfo`，一层抽象 |
| 与容器/云环境 | 标准（`--gpus all`、nvidia-container-toolkit） | 需要透传 `/dev/dri` + Vulkan loader，AutoDL/Docker 里麻烦 |
| Windows 支持 | 好 | 好 |
| 占用显存可见性 | 精确 | 大致准确 |

### 2.4 对你这个项目的结论

| 场景 | 选择 | 理由 |
|---|---|---|
| **本机（573.22 / sm_120 / 8GB / 只验证可行性）** | **Vulkan** | CUDA 两条路都堵死；Vulkan 已实测可用。只跑 ≤1B 验证"加载+出 token+OpenAI 契约"，性能不重要 |
| **云端 V1（Ubuntu 22.04 / CUDA 12.8 / 24G）** | **CUDA** | 官方有 `ubuntu-cuda-12.8` 现成包；内核更全、无着色器冷启动、多卡路径成熟。**别在云上用 Vulkan**（容器透传麻烦，也没有性能优势） |
| 云端 V2（27B 生产） | CUDA 或 vLLM | 看最终 TPS 数据决定 |

一句话：**本机 Vulkan 是"能跑"的选择，云端 CUDA 是"跑好"的选择。** 而 MeowLLM 的引擎层把这两者抽象掉了，所以这个差别只影响启动参数，不影响接口。

---

## 3. 文件命名修订

### 3.1 新规则

| 对象 | 规则 | 示例 |
|---|---|---|
| **文件名** | **不带 `meowllm` 前缀**（靠目录与包名区分） | `config.py`、`engine/llamacpp.py`、`bin/start.ps1` |
| **包根目录** | 保留 `meowllm/`（命名空间根，不是前缀） | `.vendor/.MeowLLM/meowllm/` |
| **类名** | **必须 `MeowLLM` 前缀** | `MeowLLMConfig`、`MeowLLMEngineLlamaCpp`、`MeowLLMThinkState` |
| 端点 | 保留 `meowllm` | `/meowllm/v1/chat/completions` |
| 请求扩展键 | 保留 | `extra_body.meowllm.*` |
| 配置根键 | 保留 | `meowllm:` |
| 环境变量 | 保留 | `MEOWLLM_CONFIG`、`MEOWLLM_ALLOW_LOCAL_MODEL` |

> 配置文件我建议叫 **`config.yml`**（按你的规则去前缀）。因为文件在 `.vendor/.MeowLLM/` 里，和项目根 `config.yml` 靠目录区分；且**根键是 `meowllm:`**，合并进项目配置时也不会串味。若你更想叫 `meowllm.yml`，只需改一个常量。

### 3.2 最终目录树（`*`=B1 `†`=B2 `‡`=B3）

```
.vendor/.MeowLLM/
├─ config.yml *                       # 根键 meowllm:
├─ README.md *                        # 命名规则 + 禁用名 + 启动/自测
├─ requirements.txt *                 # B1 为空（复用 runtime/311）
├─ bags/                              # ✅ 已到位
├─ autoDL/                            # ✅ 已到位（建议 gitignore）
├─ docs/                              # MIRROR 论文
│
├─ meowllm/                           # 包名保留
│  ├─ __init__.py *                   # MeowLLM_VERSION / MeowLLM_API_VERSION / 前缀常量
│  ├─ errors.py *                     # MeowLLMError 族
│  ├─ config.py *                     # MeowLLMConfig
│  ├─ scheduler.py *                  # MeowLLMScheduler
│  ├─ server/
│  │  ├─ __init__.py *
│  │  ├─ schema.py *                  # MeowLLMChatRequest / MeowLLMExtras / 旧字段映射
│  │  ├─ stream.py *                  # MeowLLMChunkWriter / SSE 封装
│  │  ├─ app.py *                     # create_app / main
│  │  ├─ routes_v1.py *               # /meowllm/v1/*
│  │  └─ routes_control.py *          # /meowllm/control/*
│  ├─ engine/
│  │  ├─ __init__.py *
│  │  ├─ base.py *                    # MeowLLMEngineBase + GenParams/GenEvent
│  │  ├─ factory.py *                 # 三道安全闸门
│  │  ├─ stub.py *                    # MeowLLMEngineStub
│  │  ├─ llamacpp.py ‡                # MeowLLMEngineLlamaCpp（B2/B3）
│  │  ├─ hf.py ‡                      # 暂不实现
│  │  └─ vllm.py ‡                    # 暂不实现
│  ├─ cache/
│  │  ├─ __init__.py *
│  │  ├─ prefix.py *                  # MeowLLMPrefixCache
│  │  └─ session.py *                 # MeowLLMSessionCache
│  ├─ tools/
│  │  ├─ __init__.py *
│  │  ├─ parse.py *                   # 工具参数容错 + MeowLLMToolCallBuilder
│  │  └─ guard.py †                   # 工具子集化 + 语法约束
│  ├─ mirror/
│  │  ├─ __init__.py †
│  │  ├─ state.py †                   # MeowLLMThinkState / MeowLLMThinkStore
│  │  ├─ prompt.py †                  # Talker 分区 / Thinker 提示 + JSON schema
│  │  ├─ core.py †                    # MeowLLMMirrorCore 状态机
│  │  └─ loop.py †                    # MeowLLMThinkLoop
│  └─ vision/
│     ├─ __init__.py *
│     ├─ encode.py *                  # MeowLLMVisionEncoder
│     └─ template.py †                # 图像抽取/转换
│
├─ bin/
│  ├─ start.ps1 *                     # 端口探测 + 启动 + 健康轮询
│  ├─ selftest.py *                   # 12 项契约矩阵
│  ├─ project_probe.py *              # 用项目真 port 打本服务
│  ├─ tiny_probe.py ‡                 # ★ 极小模型加载可行性（T0–T3）
│  └─ bench.py †                      # TPS / 命中率基准
│
├─ engine_bin/                        # 解压后的 llama.cpp（gitignore）
│  ├─ win-vulkan/                     # ← bags 的 win-vulkan 包解到这
│  └─ linux-cuda-12.8/                # （云端用）
├─ state/meowllm/                     # 运行态（不写项目 .temp）
├─ models/                            # GGUF（gitignore）
└─ logs/
```

### 3.3 需要补的 `.gitignore`

```gitignore
.vendor/.MeowLLM/engine_bin/
.vendor/.MeowLLM/state/
.vendor/.MeowLLM/logs/
.vendor/.MeowLLM/autoDL/
```
（`*.gguf` / `*.safetensors` / `.venv/` 已被现有规则覆盖）

---

## 4. 实施批次（按你的优先级重排）

| 批次 | 内容 | 本机可跑 | 估行数 | 产出 |
|---|---|---|---|---|
| **B1 骨架** | 配置/契约/路由/引擎抽象/stub/缓存记账 | ✅ 零下载 | ≈1 800 | 服务能起、`selftest` 12 项全绿 |
| **B2 llama.cpp 引擎** | `engine/llamacpp.py`（子进程）+ `bin/tiny_probe.py` | ✅ Vulkan + ≤1B | ≈600 | **极小模型真实出 token、契约打通** |
| **B3 MIRROR 框架** | `mirror/*` 4 个 + 集成进 `routes_v1` | ✅ 用 ≤1B 模型验证状态机 | ≈700 | 焦点锁 / 每轮重构 / Thinker 后台 |
| **B4 云端** | CUDA 后端验证 + 视觉 mmproj + 真实模型 | ❌ 需云端 | ≈500 | 真实 TPS / 缓存命中率 / 工具准确率 |

**MIRROR 与 llama.cpp 都在本机就能做完**（≤1B 模型），这是这版方案最大的变化 —— 你的两块诉求不需要等云端。

---

## 5. B1 骨架模块规格

与 V1 相同的设计，仅文件名去前缀。下列为**签名速查**（详细职责见 V1 文档，未变）：

```python
# meowllm/config.py
class MeowLLMConfig:
    @classmethod def load(cls, path=None) -> "MeowLLMConfig"
    def get(self, dotted, default=None); def validate(self) -> None
    # 段：server/model/context/gen/engine/safety/thinking/cache/queue/mirror/vision/stub

# meowllm/server/schema.py
class MeowLLMMessage / MeowLLMTool / MeowLLMToolChoice / MeowLLMExtras / MeowLLMChatRequest
def parse_body(raw) -> tuple[MeowLLMChatRequest, MeowLLMExtras]
def normalize_legacy_body(raw) -> MeowLLMExtras        # ★ 旧字段映射（下表）

# meowllm/server/stream.py
class MeowLLMChunkWriter: content/reasoning/tool_call/finish/meta
def event_stream(events, writer) -> AsyncIterator[bytes]

# meowllm/server/app.py
def create_app(cfg) -> FastAPI;  def main(argv=None) -> int

# meowllm/engine/base.py
@dataclass MeowLLMGenParams / MeowLLMGenEvent
class MeowLLMEngineBase(ABC):
    load/unload/info/count_tokens/build_prompt/generate/kv_slot_stats/cache_take/cache_give

# meowllm/engine/factory.py
def create(cfg) -> MeowLLMEngineBase;  def probe_params_b(path) -> float

# meowllm/cache/prefix.py
class MeowLLMPrefixCache: stable_prefix/key_of/lookup/give/stats
# meowllm/cache/session.py
class MeowLLMSessionCache: get/touch/reset/evict_expired/stats
# meowllm/tools/parse.py
def parse_tool_args(raw) -> dict;  class MeowLLMToolCallBuilder
# meowllm/scheduler.py
class MeowLLMScheduler: submit(priority, coro)/stats
```

**旧字段映射表**（`normalize_legacy_body`，让现有 port 零改动可用）：

| 现有 port 传的 | 映射为 |
|---|---|
| `extra_body.thinking.type == "disabled"` | `thinking_level=off` |
| `extra_body.thinking.type == "enabled"` | `thinking_level=medium` |
| `extra_body.parameters.enable_thinking == false` | `thinking_level=off` |
| `reasoning_effort: low/medium/high/none` | 对应档位 |
| `tool_choice` 非空 | 强制 `thinking_level=off` |
| 未知字段 | 忽略 + debug 日志，**不报错** |

---

## 6. B2 llama.cpp 引擎规格

### 6.1 类设计

```python
# meowllm/engine/llamacpp.py
class MeowLLMEngineLlamaCpp(MeowLLMEngineBase):
    kind = "llamacpp"
    def __init__(self, cfg)                     # cfg.engine.llamacpp
    def load(self) -> None                      # mode=launch → 起子进程；attach → 只连通性检查
    def unload(self) -> None                    # 终止子进程 + 落盘 slot
    def info(self) -> dict                      # 解析 /props 与 /metrics
    def count_tokens(self, messages) -> int      # 调 /tokenize
    def build_prompt(self, messages, tools, params) -> str   # 交给 server 的 chat 模板（不做本地模板）
    async def generate(self, prompt, params) -> AsyncIterator[MeowLLMGenEvent]
    def kv_slot_stats(self) -> dict
    def cache_take(self, key) -> str | None      # 返回 slot_id
    def cache_give(self, key, slot_id) -> None
```
**实现要点**：
- `mode: launch` 用 `asyncio.create_subprocess_exec` 起 `llama-server`，日志重定向到 `logs/llamacpp-*.log`，就绪靠轮询 `GET /health`
- `mode: attach` 不启动，只连现成的（方便你手动调试）
- `generate()` 内部对 `llama-server` 的 `/v1/chat/completions` 发 `stream:true`，把它的 SSE 反向解包成 `MeowLLMGenEvent`，再由 MeowLLM 重新封装成**我们的**命名空间响应
- **不做本地 chat 模板**：模板交给 llama.cpp（`--jinja` 默认已开），我们只透传 `messages`/`tools`
- 会话 KV：`session_id → slot_id` 映射，请求带 `id_slot`

### 6.2 启动参数（本机实测确认，已核对 `--help`）

```yaml
engine:
  kind: llamacpp
  llamacpp:
    mode: launch
    bin_dir:  engine_bin/win-vulkan          # bags 解压到这里
    server_exe: llama-server.exe
    host: 127.0.0.1
    port: 18110                              # 内部端口，不对外
    device: Vulkan1                          # ★ 必须！否则跑 Intel 核显
    model: models/Qwen3-0.6B-Q8_0.gguf
    mmproj: null
    n_ctx: 8192
    n_batch: 512
    n_ubatch: 512
    n_gpu_layers: 99
    threads: 0
    parallel: 2
    extra_args:
      - "--jinja"                            # 默认已开，显式写死防未来变更
      - "--reasoning-format"                 # ★ 思考内容进 reasoning_content
      - "deepseek"
      - "--cache-prompt"                     # 默认已开，显式写死
      - "--slot-save-path"
      - "state/meowllm/slots"
      - "--no-mmproj"                        # 文本模型时显式关掉，避免自动下载
    env:
      GGML_VK_VISIBLE_DEVICES: "1"           # 双保险：只暴露独显
    startup_timeout: 180
```

**已在本机实测确认的事实**（`llama-server --help`）：
- `-dev/--device <dev1,dev2>`、`--list-devices`、`-ngl`、`-sm`、`-mg` 都存在
- `--cache-prompt` **默认已开启**
- `--jinja` **默认已开启**
- `--reasoning-format deepseek` → 「puts thoughts in `message.reasoning_content`」，正是项目 `napcat_llm.py` 需要的字段名
- `-mm/--mmproj`、`--no-mmproj`、`--no-mmproj-auto`
- `-np/--parallel`、`--slot-save-path`、`--warmup/--no-warmup`、`--metrics`、`--api-key`
- `--port` **默认 9931**（v0.7.0 起的变更），所以我们**必须显式传 18110**
- ⚠️ `--tools` 是 llama.cpp **内置 agent 工具**（read_file/grep_search…），**与模型的 function calling 无关**。模型工具调用靠 `--jinja` + 模型自带的 chat template。别开 `--tools`（有安全风险，`--help` 里自己写了 "do not enable in untrusted environments"）

---

## 7. B3 MIRROR 框架规格

### 7.1 四个模块

```python
# meowllm/mirror/state.py
@dataclass MeowLLMThinkState:
    session_id: str; focus: str; thinking: str
    plan_next: list[str]; open_threads: list[dict]
    salience: float; updated_at: str
class MeowLLMThinkStore:
    def load(self, sid) -> MeowLLMThinkState
    def save(self, st) -> None            # ★ 写前强制截断
    def reset(self, sid) -> None
    # 路径 state/meowllm/mirror/<sid>.json；截断上限 thinking ≤1.5k token、plan_next ≤3、focus ≤1 句

# meowllm/mirror/prompt.py
MEOWLLM_THINKER_SCHEMA: dict              # focus/plan_next/open_threads/thinking 的 JSON Schema
def talker_block(st: MeowLLMThinkState) -> str     # 内心/焦点/行为约束
def thinker_messages(history, prev_narrative) -> list[dict]

# meowllm/mirror/core.py
class MeowLLMMirrorCore:
    def state_of(self, sid) -> MeowLLMThinkState
    async def think(self, sid, history) -> MeowLLMThinkState    # 走 engine.generate，priority=background
    def apply_to_messages(self, messages, st) -> list[dict]     # ★ 拼在项目 system 之后
    # 状态机 IDLE → TALK → THINK → IDLE

# meowllm/mirror/loop.py
class MeowLLMThinkLoop:
    def start(self); async def stop(self)
    async def on_user_message(self, sid, text); async def on_talk_done(self, sid)
    # salience 门控：琐碎轮跳过；TALK 结束后接着跑一轮产出 plan_next
```

### 7.2 三条设计铁律

1. **`talker_block` 拼在项目 system 之后**，不是之前。项目 system（角色卡/价值观/记忆）是稳定前缀，不能被 MIRROR 的动态内容污染，否则缓存全废。
2. **每轮重构，禁止追加**。`thinking` 每轮重写；超限直接截断而非截一半保留。
3. **`mirror.enabled: false` 时完全透明**（`apply_to_messages` 原样返回），保证能和云端 API 做 A/B。

### 7.3 MIRROR × 缓存的红利（L3）

Thinker 与 Talker 的 `[system + history]` 完全相同，只差最后一段指令 → 把 Thinker 用的 `slot_id` 直接交给 Talker，**第二次前向几乎免费**。这是本地 MIRROR 相对云端的额外收益，云端 API 做不到。

---

## 8. 极小模型加载可行性测试（T0–T3）

> 目的：**在花任何云端钱之前**，证明"llama.cpp 能在这台机器加载模型 → 出 token → 提供 OpenAI 契约 → 被我方项目代码消费"。用 ≤1B 模型，符合你的上限。

### 8.1 测试用模型（≤1B，GGUF）

| 首选 | 文件 | 体积 | 说明 |
|---|---|---|---|
| `Qwen/Qwen3-0.6B-GGUF` | `Qwen3-0.6B-Q8_0.gguf` | ≈0.65 GB | 同系列，带 Qwen3 chat template（含 tools 段），能验 `--reasoning-format deepseek` |
| 备选 | `Qwen3-0.6B-Q4_K_M.gguf` | ≈0.40 GB | 显存/带宽紧张时用 |
| 兜底 | `Qwen2.5-0.5B-Instruct-GGUF` | ≈0.4–0.5 GB | 若 Qwen3 GGUF 仓库有问题 |

放到 `.vendor/.MeowLLM/models/`。（以 HF 仓库实际文件名下载，我不代下。）

**⚠️ 本机测不了视觉**：Qwen3-VL 最小是 2B > 1B 上限。视觉链路只能等云端。

### 8.2 T0 —— 二进制与设备（不加载模型，现在就能跑）

```powershell
$bin = "D:\.Meowlisis\.vendor\.MeowLLM\engine_bin\win-vulkan"
& "$bin\llama-cli.exe" --version
& "$bin\llama-cli.exe" --list-devices
```

**判据**
| 检查 | 期望 |
|---|---|
| `--version` | `0.7.0 (build 11669)` |
| `--list-devices` | 出现 `Vulkan1: NVIDIA GeForce RTX 5060 Laptop GPU` |
| 若只有 `Vulkan0: Intel ...` | 说明 Vulkan 只看到核显 → 需更新 NVIDIA 驱动 |

### 8.3 T1 —— 模型能加载 + 能出 token

```powershell
$bin = "D:\.Meowlisis\.vendor\.MeowLLM\engine_bin\win-vulkan"
$m   = "D:\.Meowlisis\.vendor\.MeowLLM\models\Qwen3-0.6B-Q8_0.gguf"
& "$bin\llama-cli.exe" -m $m -dev Vulkan1 -ngl 99 -c 4096 -n 64 -p "你好，用一句话介绍你自己。" 2>&1
```

**判据**
| 指标 | 通过线 |
|---|---|
| 能打印出完整回复 | 是（内容质量不重要） |
| 加载耗时 | ≤ 15 s |
| 显存占用 | ≤ 2 GB |
| decode 速度 | ≥ 20 tok/s（Vulkan 独显） |
| 若显示 `ggml_vulkan: ... RTX 5060` | 证明真的用了独显 |

### 8.4 T2 —— OpenAI 契约 + 缓存命中（核心）

```powershell
$bin = "D:\.Meowlisis\.vendor\.MeowLLM\engine_bin\win-vulkan"
$m   = "D:\.Meowlisis\.vendor\.MeowLLM\models\Qwen3-0.6B-Q8_0.gguf"
& "$bin\llama-server.exe" -m $m -dev Vulkan1 -ngl 99 -c 4096 `
    --host 127.0.0.1 --port 18110 `
    --jinja --reasoning-format deepseek --cache-prompt `
    --slot-save-path "D:\.Meowlisis\.vendor\.MeowLLM\state\meowllm\slots" `
    --metrics --no-warmup
```

另开一个窗口：
```powershell
# 1) 健康
Invoke-RestMethod http://127.0.0.1:18110/health

# 2) 非流式
$body = @{ model="local"; messages=@(@{role="user";content="1+1=?"}); max_tokens=64 } | ConvertTo-Json -Depth 6
$r1 = Invoke-RestMethod -Uri http://127.0.0.1:18110/v1/chat/completions -Method Post -Body $body -ContentType 'application/json'
$r1 | ConvertTo-Json -Depth 8

# 3) 同 prefix 再来一次（验缓存）
$r2 = Invoke-RestMethod -Uri http://127.0.0.1:18110/v1/chat/completions -Method Post -Body $body -ContentType 'application/json'

# 4) 流式
curl.exe -N -X POST http://127.0.0.1:18110/v1/chat/completions -H "Content-Type: application/json" -d $body
```

**判据（这是"缓存命中"的硬证据）**
| 检查 | 期望 |
|---|---|
| `/health` | `{"status":"ok"}` |
| 响应含 `choices[0].message.content` | 是 |
| 响应含 `timings` | 是（`prompt_n` / `prompt_per_second` / `predicted_n`） |
| **第二次请求的 `timings.prompt_n` 明显小于第一次** | ★ 证明 `--cache-prompt` 生效（实际字段名以返回为准） |
| 流式首包到达时间 | ≤ 300 ms |
| 带 `tools` 的请求不 500 | 是（0.6B 选对工具不重要，只验协议） |
| `--reasoning-format deepseek` 下思考内容进 `reasoning_content` | 是（0.6B 可能很少思考，但字段应存在或为空） |

### 8.5 T3 —— 我方链路（MeowLLM 代理）

```powershell
# 1) 起 MeowLLM（engine.kind=llamacpp, mode=attach 指向 18110）
& 'D:\.Meowlisis\runtime\311\python.exe' -m meowllm.server.app --config config.yml

# 2) 契约自测
& 'D:\.Meowlisis\runtime\311\python.exe' bin\selftest.py

# 3) 用项目真 port 打 MeowLLM
& 'D:\.Meowlisis\runtime\311\python.exe' bin\project_probe.py
```

**判据**：`selftest` 12 项全绿 + `project_probe` 全绿 → **项目 70 处调用点全部可被本地模型接管**。

### 8.6 安全闸门在本阶段的配置

```yaml
safety:
  allow_engine: [stub, llamacpp]     # 本机放开 llamacpp
  max_local_model_params_b: 1.0      # 仍卡死 1B
  require_env_override: false        # 白名单已限死，不必再加环境变量
```
→ 0.6B 能跑，8B/27B 在启动时被参数闸拦住。**C4 约束依然成立**。

---

## 9. AutoDL 云端注意（等本机 T3 绿了再上）

| 事项 | 说明 |
|---|---|
| 上传什么 | `bags/` 里两个 ubuntu-cuda-12.8 包（共 731 MB）；`meowllm/` 代码；`config.yml` |
| 解压 | `tar xzf` 两个包到 `engine_bin/linux-cuda-12.8/`，需把 **cudart 包的 3 个 .so 和主包放同一目录** |
| 环境变量 | `export LD_LIBRARY_PATH=$PWD:$LD_LIBRARY_PATH`（cudart 是免装 Toolkit 的关键） |
| 自检 | `./llama-cli --version` → `./llama-cli --list-devices` → 应看到 `CUDA0` |
| 视觉 | 需额外下 Qwen3-VL 的 GGUF 主体 + `mmproj-*.gguf`，启动加 `-mm` |
| ⚠️ 安全 | 密码在 `autoDL/密码.txt` 明文。**先把 `.vendor/.MeowLLM/autoDL/` 加进 `.gitignore`**；另外这个 IP/端口是公网可达的，建议用完就改密码或关实例 |
| vLLM | 别装进现有 PyTorch 2.8.0 环境（会改 torch 版本）；要装另建 venv |

还有一个必须确认的：**云端的 `nvidia-smi` 头部**（右上角 `CUDA Version:`）和 `compute_cap`。你现在给我的「CUDA 12.8」我需要确认它是**驱动上限**还是**已装 Toolkit** —— 这决定 CUDA 包能否直接用（判据：驱动上限 ≥ 包所用 CUDA 12.8）。

---

## 10. 待你确认

| # | 问题 | 我的默认 |
|---|---|---|
| 1 | 配置文件叫 `config.yml`（去前缀）还是保留 `meowllm.yml`？ | `config.yml`（根键 `meowllm:`） |
| 2 | 包根目录 `meowllm/` 保留吗？（我认为这是命名空间不是前缀） | 保留 |
| 3 | `engine_bin/` 用来放解压后的 llama.cpp，名字可以吗？ | 可以 |
| 4 | T1/T2 的极小模型用哪个？`Qwen3-0.6B-Q8_0`（0.65GB）？ | 是 |
| 5 | 本阶段 `allow_engine: [stub, llamacpp]` + `max 1.0B`，认可？ | 是 |
| 6 | 要不要我先做 **B1 骨架**（≈1800 行，零下载、零模型，今天可跑 `selftest`）？还是直接从 B1+B2 一起做完再给你验？ | 先 B1，绿了再 B2 |
