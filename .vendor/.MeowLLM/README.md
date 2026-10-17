# MeowLLM

> Meowlisis 的本地模型加载端：独立进程，只对回环暴露 OpenAI 兼容 HTTP。
> 核心是自研双流并发推理（AsyncReasoning）：思考流与输出流在同一份权重上并行推进。

**当前状态**：本机 Qwen3-0.6B 双流已跑通（思考/输出真交错、分段续说可用）；
角色分离效果受 0.6B 能力限制，换 8B 以上才能看到论文级效果。

MIRROR 已完全移除（配置、代码、控制面接口都没有了）。本项目只做 AsyncReasoning。

---

## 两种生成模式

引擎按 `thinking_level` 自动选路：

| 命令 | 走的路径 | 说明 |
|---|---|---|
| `thinking_level=off`（默认） | **plain** | 标准 chat template（`enable_thinking=False` 生成空 `<think></think>`），单流、快，适合闲聊/工具 |
| `thinking_level=low/medium/high` | **dual** | 双流：thinker 与 writer 并行，writer 走分段续说 |

模型含 `linear_attention` 层（Qwen3.5 / 3.8 这类混合架构）时，引擎只跑 plain，
并在日志里说明原因——双流要求两个视图对同一批 token 使用两种顺序，线性注意力的
递推状态对顺序敏感，没有参考实现可依。

---

## 双流的三块 KV

- `PROMPT`：共享，只 prefill 一次
- `THINKER`：思考流（`reasoning_content`）
- `WRITER`：输出流（`content`）

两个视图看同一份物理 KV，只是拼接顺序不同：

```
writer  视图： P → T → W
thinker 视图： P → W → T
```

于是：新思考立刻改变下一句输出；已说出口的话成为后续思考的上下文。两条流寿命互不绑定。

RoPE 可加性让"换个顺序"只改**查询的旋转角度**，不动 KV 存储。

---

## 角色扮演：分段续说

`probe_kind: roleplay` 时，writer 不再"一次说完"：

1. 触发时 **思考与说话同时开始**（writer 第一段不延迟）
2. 一段自然结束（`<|im_end|>` 或段长上限）→ 说话暂停，思考继续
3. 每 `probe_every_tokens` 个思考 token 插一次探针「还有话要说吗？(yes/no)」
4. 判 yes → 在 W 末尾补边界标记 `<|im_end|>\n<|im_start|>assistant\n`（进 KV、不进文本）→ 再说一段
5. 连续 `stop_after_no` 次 no，或段数到 `max_segments`，结束

探针插入思考流末尾、判完截断回原长度（隐藏探针 KV），不影响后续推理。

`probe_kind: math` 保留官方数学语义（想法不够就暂停输出）。

---

## 快速开始

```bat
start.bat                 :: 按 config.yml 启动
start.bat check           :: 只做配置校验 + 安全闸门自检
labs\run_lab.bat          :: 实验台：双流时间轴 + 两臂对比
start.bat stop            :: 停止
```

`run_lab.bat` 会先探测 18100–18108 上有没有健康实例：有就复用，不重启、不重载模型。
没有就起一个，并等它就绪（会跟随服务端实际落到的端口）。

---

## 配置（`config.yml`）

无 api_key：服务只绑回环，是私有进程。

```yaml
meowllm:
  server:   { host: 127.0.0.1, port: 18100, port_fallback: 9 }
  model:    { name: meowllm-local }
  context:  { n_ctx: 8192 }
  gen:
    temperature: 0.8        # 采样
    top_p: 0.9
    top_k: 40
    repeat_penalty: 1.05
    talk_max_tokens: 256    # 每段说话上限（思考长度由 thinking.budgets 控制）
  engine:
    kind: dualstream
    dualstream:
      model_dir: models/Qwen3-0.6B
      device: cuda
      dtype: bfloat16
      language: en              # 探针语言
      probe_every_tokens: 20
      max_segments: 6           # 最多说几段
      stop_after_no: 2          # 连续几次 no 就收尾
      probe_kind: roleplay      # roleplay | math
  safety:
    allow_engine: [dualstream]
    max_local_model_params_b: 1.0   # 本机闸门：超过就拒载
```

请求级可覆盖：`max_tokens`（→ talk）、`temperature`、`top_p`、`top_k`、`stop`、`seed`、
以及 `extra_body.meowllm.{thinking_level, think_budget, session_id, context_limit, priority, language}`。

---

## 接口

| 端点 | 用途 |
|---|---|
| `POST /meowllm/v1/chat/completions` | 流式 / 非流式，`content` 与 `reasoning_content` 分开 |
| `GET /meowllm/v1/models` | 探活 + 模型名 |
| `GET /meowllm/control/health` | 就绪、引擎信息（含 `dual_stream` / `linear_layers` / `architecture`） |
| `GET /meowllm/control/stats` | 速率、队列、缓存记账 |
| `POST /meowllm/control/reload` | 只重载配置（引擎参数需重启） |
| `POST /meowllm/control/session/reset` | 清会话记账 |

非流式响应的 `meowllm` 字段带 `mode / segments / pauses / resumes / probes / probe_no / writer_tokens / thinker_tokens`。

---

## 端口

| 用途 | 端口 |
|---|---|
| MeowLLM | 18100 - 18108 |
| 实验台 | 18700 |

---

## 目录

```
meowllm/
  engine/
    dualstream/
      engine.py        加载 + plain/dual 两条生成路径 + 架构探测
      loop.py          三块 KV 调度、分段续说、探针
      blocks.py        块布局与位置差值表
      attention.py     按块旋查询的注意力
      mode.py          探针（roleplay / math 两套语义）
      prompts.py       官方逐字提示词 + 工具调用解析
      reference.py     物理重排参考实现（对拍基准）
    base.py  factory.py  stub.py
  server/              OpenAI 兼容层 + 控制面
config.yml
start.bat  stop.bat
.test/bin/             运维脚本（自检、就绪等待、停服）
labs/                  实验台 + 启动器
docs/notes/            设计与论文对照
.scripts/              一次性脚本（下载、对拍、云端）
models/                本地权重
```

---

## 适配过的模型

| 模型 | 架构 | 能跑 | 双流 |
|---|---|---|---|
| Qwen3-0.6B | 全注意力（dense） | ✅ | ✅ |
| Qwen3.5-27B-FP8 | 混合注意力（48/64 线性）+ VLM，fp8 | 需 ≥32 GB 显存 | ❌ 自动降级 plain |
| Qwen3.8-27B-FP8 | 同上，MoE + 融合投影 | 需 ≥32 GB 显存 | ❌ 自动降级 plain |

加载器按 `config.json` 的 `architectures[0]` 反射取类（`Qwen3_5ForConditionalGeneration`
等原生支持，不需要 `trust_remote_code`），并统一使用模型自带 cache：
混合模型必须用 `Qwen3_5DynamicCache`，传 `DynamicCache` 会在 `linear_attn` 处报错。

---

## 研究历程

按时间顺序记录这一轮从"跑不起来"到"能跑但不爱说"的完整过程，方便回看每一步的动机与结论。

### ① 0.6B 双流只会"自言自语"

现象：`content` 里全是"好的，用户让我……"，没有真正的回答。
定位：`thinking_level=off` 时仍套用双流的 writer 前缀（`" ... [SYSTEM: thoughts will continue here]\n</think>\n"`），thinker 块为空，模型只能续写思考。
处理：关思考走标准 chat template（`enable_thinking=False` 生成空 `<think></think>`）；writer 改懒启动。顺带修掉 `usage` 恒 0、流式 meta 分片 `choices: []`、tool_call 事件参数名错误、prompt 容量硬编码 1024、attention 实现残留等。

### ② 配置清理与主项目接线

去掉 `mirror.*`、`api_key`、`vision/stub/llamacpp` 等冗余项；`max_tokens` 拆成 `gen.talk_max_tokens`（说话）与 `thinking.budgets`（思考）。主项目侧统一成 `MeowLLMLLM` 一个端口，39 个调用点全部接上；前端不再重复参数，选 MeowLLM 时跳转到独立的 `/meowllm.html` 配置页。

### ③ 27B / 3.8 的适配边界

`Qwen3.5-27B-FP8` 是混合注意力（48/64 层 `linear_attention`）+ VLM + fp8。引擎按 `architectures[0]` 反射取模型类、改用模型自带的 `Qwen3_5DynamicCache`、并做架构探测：混合模型自动降级单流。结论：双流要求"两个视图对同一批 token 用两种顺序"，线性注意力的递推状态对顺序敏感，没有参考实现可依，因此不做。

### ④ 云端 8B 内容级实测

用主项目真实 system prompt + 真实 201 条短期记忆，跑 6 级阶梯（打招呼→情绪→观点→推理→创作→追问）。结论：

- 思考是实打实的（240–421 token），不是空转
- 回复长度跟着任务走（42 / 122 / 257 / 101 / 292 字）
- **"不多说"来自人设里"简短直接"的约束**，不是模型吝啬
- 格式被历史污染：回复里出现 `【来自QQ的消息】`、`【绘画】`，因为短期记忆混着多模块条目

### ⑤ 性能：从 O(qlen×容量) 到 O(qlen)

三个发现依次落地：

1. **瓶颈不是 n²，是容量**：attention 按 `capacity` 切片，而 `capacity[PROMPT] = n_ctx`。`n_ctx` 提到 32768 后，900 token 的 prompt 就要 3.9 GB → OOM。
   → 改成按实际 prompt 长度向上取 64。
2. **单块 prefill 可以用原生 SDPA**：只有 P 首填时可见块只有自己、`delta=0`，数学上就是普通因果注意力（论文 §3 也靠因果掩码定义正确性）。
   → 双流可用上限 900 → 16k token。
3. **decode 每步重建掩码**：按容量切片 + padding 掩码 + `arange`，36 层每步约 20 个小算子。
   → 改成按有效长度切片，每步 65 ms → 34 ms。

耗时模型：`(思考 token + 输出 token) × 34 ms + prefill(1–3 s)`，所以"慢"主要来自思考长度，不是上下文长度。

### ⑥ 段数恒为 1 的机制分析

探针（yes/no）的实现是：把问句插到思考流末尾 → 读下一个 token 的 yes/no 概率质量 → 截断回滚。

实测 p(yes) 只有 0.04–0.12，两次 no 就 `probing_stopped`，而思考流之后还会继续跑两百多个 token，却再没人问它。

结论：不是模型不愿说，是**没有任何激励**——探针措辞中性、人设要求简短、两次 no 就永久停问、思考流当时正在收尾。

### ⑦ A+B 实施（效果未达预期，如实记录）

- **A**：writer 暂停期间，把 `</think>`/EOS 从 thinker 的采样里屏蔽，避免它提前收尾
- **B**：探针改问"还有没讲到的具体细节吗？有就补一句"

实测（同一份输入、同一模型）：

| 输入 | p(yes) 前 | p(yes) 后 | 段数 |
|---|---:|---:|---:|
| 在吗 | 0.119 | 0.003 | 1 |
| 编个流浪猫故事 | 0.037 | 0.026 | 1 |
| 再详细讲讲结局 | 0.065 | 0.043 | 1 |

**没有变好，反而更低。** 说明瓶颈不在"给不给机会"，而在模型判断 + 人设约束。下一步候选：阈值偏置、停问后降频重问、创作类强制最少段数、人设里给多段示范。

### ⑧ 「从零再想一轮」可行性实验（关键结论）

假设：截断思考流破坏了 KV，导致模型倾向结束；改为**保留完整思考、在回复结束后从零开始新一轮思考**。

做法：每个输入先跑正常一轮拿到 `T1/R1`，再新建一轮请求，上下文显式带上 `T1`（拼成 `<think>…</think>` + 回复）与追问：

```
回顾你上面这轮的内容。如果还有没讲到的具体细节，就直接补一到两句；
如果确实没有了，就只回复「没有了」两个字。
```

结果（3 类输入 × 2 变体，共 6 次）：

| 输入 | 带 T1 | 只带 R1 | 回答 |
|---|---|---|---|
| 观点 | 思考 200 tok | 176 tok | **没有了** |
| 创作 | 239 tok | 193 tok | **没有了** |
| 解释 | 266 tok | 242 tok | **没有了** |

**即使没有任何截断、思考完整保留、并且明确邀请它补充，模型仍然全部答"没有了"**，而且每次先想 176–266 token 才拒绝。带不带 `T1` 没有差别。

对照实验（把询问改成**指令**）——同一上下文，只把追问换成
`请在刚才那段之后，再补两句更具体的细节（不要重复已说过的内容）`：

| 输入 | 补充长度 | 内容样例 |
|---|---:|---|
| 观点 | 103 字 | "就像现在，明明知道该修TTS，但一想到要碰那些代码，就又想先画个画……" |
| 创作 | 76 字 | "上班族在离开前，悄悄在猫窝里放了一本画满猫咪的绘本……" |
| 解释 | 207 字 | "短期记忆容易被新信息冲走……长期记忆需要反复巩固……" |

**结论**：能力在、机制可行，但**"询问"永远得到 no，"指令"才产出内容**。所以问题不在 KV 是否被破坏，而在门的性质——探针是"审问"，需要改成"许可/指令"，或者干脆让模型用「生成」而不是「判断」来决定要不要续说。

### ⑨ 许可式探针（第三次尝试，仍为负结果）

把探针改成"这里还能再补一句具体的细节，要补吗？(yes/no)"，并顺带把每段文本暴露成 `meowllm.segment_texts` 方便观察。

| 输入 | 段数 | 探针 | p(yes) | p(no) |
|---|---:|---:|---:|---:|
| 在吗 | 1 | 2（全 no） | 0.012 | 0.963 |
| 编个流浪猫故事 | 1 | 2（全 no） | 0.040 | 0.777 |
| 短期/长期记忆 | 1 | 2（全 no） | 0.123 | 0.787 |

依然全是一段。**根因确认**：探针是塞进 think 块的裸文本，没有角色边界；而对照实验里那句话是真正的 `<|im_start|>user` 轮次，模型才当指令执行。

**决定**：不再用提示词/探针硬撬。模型本身被训练成"一次给完整答案"，缺的是"停顿后自发补充"的行为倾向——这属于模型层，计划日后用 LoRA / 底层改造解决。完整设想见 [设计设想_拟人化的分段说话](docs/notes/2026-10-18_设计设想_拟人化的分段说话.md)。

引擎侧的分段机制（段边界标记、状态机、`segment_texts`、探针语义切换）全部保留，训练好的模型可以直接接上，不需要重写引擎。

---

## 文档

| 文档 | 内容 |
|---|---|
| [2026-10-18_设计设想_拟人化的分段说话](docs/notes/2026-10-18_设计设想_拟人化的分段说话.md) | **要做成什么样**：说—停—想—补的完整设想与训练路线 |
| [2026-10-17_官方实现对照_权威版](docs/notes/2026-10-17_官方实现对照_权威版.md) | 以官方代码为准的三块布局、提示词、批处理机制 |
| [2026-10-17_AsyncReasoning重构方案](docs/notes/2026-10-17_AsyncReasoning重构方案.md) | 实施计划与取舍 |
| [2026-10-17_角色扮演分段改造TODO](docs/notes/2026-10-17_角色扮演分段改造TODO.md) | 分段续说的需求与风险 |
| [2026-10-18_prefill与decode优化实测](docs/notes/2026-10-18_prefill与decode优化实测.md) | 容量动态化 / SDPA 快路 / decode 切片的实测数据 |
| [2026-10-18_角色扮演内容实测_8B](docs/notes/2026-10-18_角色扮演内容实测_8B.md) | 主项目真实输入下的 6 轮完整思考与回复原文 |
| [2026-10-17_主项目LLM调用点盘点与缺口](docs/notes/2026-10-17_主项目LLM调用点盘点与缺口.md) | 主项目里 13 个功能域的接入面 |

---

## 已验证 / 未完成

**已验证**

- 数学等价：块 KV + 查询旋转 ≡ 物理重排
- 双流真交错：同一轮各出一个 token
- HTTP 双通道分开流式；非流式 `usage` 有真实 token 数
- 分段机制：`segments / resumes / probe_no / segment_texts` 计数与取文正确，边界标记不进用户文本
- 架构探测：混合模型自动判 `dual_stream=false` 并降级 plain
- 性能：容量动态化 + 单块 prefill SDPA + decode 长度切片；双流上限 900 → 16k token，每步 65 → 34 ms
- 收尾自检（`.test/bin/selftest_final.py`）：health / models / plain / dual / tools / 流式 / 长 prompt 回退 / 坏请求 400 —— 8 项全过

**未完成 / 已知限制**

- **"说完再补一句"的行为没有做出来**：探针、许可式探针、从零再想一轮三种方案实测均失败（模型一律答"没有了"）。
  能力是有的（改成指令就能补 76–207 字），缺的是行为倾向 → 留待 LoRA / 模型层改造，见 [设计设想](docs/notes/2026-10-18_设计设想_拟人化的分段说话.md)
- 双流要在混合注意力模型上成立，需要给 48 个线性层做 per-view 递推状态——目前**没有任何参考实现**，不做
- 官方 batch 前向（一次出两 token）仍是每步两次前向
- `control/reload` 只对请求期读取的键生效（引擎与缓存按启动时配置构造）
- 非流式响应里的 `segment_texts` 会与 `content` 重复一份文本，长回复时响应体偏大
