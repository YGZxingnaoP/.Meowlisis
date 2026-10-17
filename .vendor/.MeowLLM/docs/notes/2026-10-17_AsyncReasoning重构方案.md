# AsyncReasoning 实施计划与项目结构

> 依据：`docs/Asynchronous Reasoning.pdf`（arXiv 2512.10931，Yakushev 等，45 页）
> 状态：**仅计划，未实施**
> 相关：`docs/notes/` 下另有一份 MIRROR 机制笔记，按 §5 处置

---

## 1. 为什么弃用 MIRROR

MIRROR 在**消息序列**层做编排（两轮 prompt 调用 + 一段文本叙事），
AsyncReasoning 在**注意力位置**层做编排（同一份 KV，两套位置编号）。

后果差别：

| 性质 | MIRROR | AsyncReasoning |
|---|---|---|
| 思考与输出 | 严格串行：先想完再说 | 同一 forward 内并行推进 |
| 两条流寿命 | 同轮同终 | 互相独立 |
| 增量输入 | 做不到 | 可在思考中吸收 |
| 是否需要训练 | 否 | 否 |
| 是否改模型 | 否 | 否（只改位置与 KV 组织） |

我们自己的实测（`labs/RESULT_MIRROR_对比.md`）显示：0.6B 上叙事**机制成立但行为 0/3**。
这个负结果保留，作为改走 AsyncReasoning 的动机证据。

---

## 2. 原理

### 2.1 一句话

> **transformer 唯一用来感知"顺序"的东西是位置编码，所以"顺序"是可以伪造的。**
> 同一份 KV cache，换一套位置编号，模型就看到了另一种历史。

论文原话：改变 prefix 中元素的顺序**不需要真的搬动 token**，只需改变 token 之间的位置关系，
因为 transformer 其余部分与位置无关。

### 2.2 三块 KV，每个 token 只存一次

| 块 | 内容 | 大小 |
|---|---|---|
| **P** (Prompt) | 系统提示 + 用户输入 | 固定 |
| **T** (Thinker) | 思考流（用户看不到） | 增长 |
| **W** (Writer) | 输出流（用户看到） | 增长 |

另有 **linker 块**：只在某一个视图中可见的短连接段。
不可见的块给一个**很大的位置索引**，靠因果掩码自然屏蔽掉。

### 2.3 两个视图 = 两套位置编号

```
Writer 视图要看到的顺序：  P → T → W
    P: [0, P)
    T: [P, P+T)
    W: [P+T, P+T+W)

Thinker 视图要看到的顺序： P → W → T
    P: [0, P)
    W: [P, P+W)
    T: [P+W, P+W+T)
```

含义：
- **Writer 看 T**：像标准 read-think-answer 那样"已经想过了"，所以它说的话有依据
- **Thinker 看 W**：像"上一轮已经说出去的话"，所以它知道自己在用户面前已经承诺了什么，
  从而能判断"要不要暂时别说了"

### 2.4 关键实现：键只旋一次，查询按块旋多次

RoPE 下 attention 分数只依赖**位置差**，所以"旋转键 +α" 等价于 "旋转查询 −α"。

```
A := [ ρ(q, iq − i_k^P)·K_P ,  ρ(q, iq − i_k^T)·K_T ,  ρ(q, iq − i_k^W)·K_W ]
```

- **键**：存进 cache 时就按"块内相对位置"旋好（第 5 个 W token 永远按 5 旋，不管前面有多少思考 token）
- **查询**：算 attention 时，针对每个块用不同的角度旋转

这样既不用每步重转整个 cache，也不用把同一个 token 存两份。

### 2.5 并行怎么发生

两个视图作为**一个 batch** 前向：Thinker 视图产出下一个思考 token，Writer 视图产出下一个回复 token。
两者互不等待。

### 2.6 模式切换：让模型自己决定"要不要先别说"

不是外部定时器。每段结束**或**每 **T=20** 个思考 token，在思考流末尾插入探针：

```
...

Wait, are my current thoughts enough to write the next paragraph or formula?
(yes/no):
```

比较下一个 token 上 `yes` 与 `no` 的概率：
- `yes` 更可能 → 继续并行（边想边说）
- `no` 更可能 → **冻结 Writer**，只推 Thinker，直到再次出现 `yes`

回答完毕后把探针那几个 KV **从视野中隐藏**，避免污染后续思维链。
论文自评：现有 thinking 模型已能大致自控，但**会犯错**。

---

## 3. 一轮对话的完整流程

```
t0   用户说完，P 块确定（系统提示 + 这句话）

t1   一次 batch 前向：{Writer 视图（W 为空）} + {Thinker 视图（T 为空）}
     Thinker 出："先看用户问的是 5 的平方……"
     Writer  出："我算一下——"

t2   两个视图各 append 一个 token，重新 batch 前向
     Thinker 出："5 的平方是 25"
     Writer  出："先从 5 开始，"

...  持续并行。用户此时已经在听/看 Writer 的前半句

tN   思考累计到 20 个 token → 插探针 → no
     → Writer 冻结（下面几轮只推 Thinker，Writer 视图不参与 batch）
     → 用户听到的最后一句话停在那里，这是有意的"停顿"

tM   探针 → yes → Writer 解冻，继续并行

tK   Thinker 自然结束（输出 </think>）
     → Writer 单独继续推进直到说完（思考停了，输出不一定停）

tZ   Writer 结束
     → 若还有增量输入，Thinker 可以继续（论文 §4.4 场景）
```

**三条性质由此得到**：
1. 输出开始时思考没停
2. 思考停了输出还能继续
3. 两条流的终止时刻互不绑定

---

## 4. 项目结构

### 4.1 目录

```
.vendor/.MeowLLM/
├── .scripts/                       临时与一次性脚本（用户原则：都放这里）
│   ├── download_qwen3_0.6b_hf.py   ✅ 已写：下载 HF 权重（带进度条）
│   └── ar_smoke.py                 ⬜ 待写：P1 地基验证（position_ids 是否可控）
├── meowllm/
│   ├── engine/
│   │   ├── base.py                 [改] 去掉 mirror_enabled；事件增加 stream 字段
│   │   ├── factory.py              [改] 白名单加 dualstream
│   │   ├── stub.py                 [改] 去 mirror
│   │   ├── llamacpp.py             [留] 不参与新功能，作为 P4 顺序基线
│   │   └── dualstream/               ★ 新增，本方案主体
│   │       ├── __init__.py
│   │       ├── engine.py           实现 MeowLLMEngineBase
│   │       ├── blocks.py           KV 三块 + linker 的分配/增长/生命周期
│   │       ├── rope.py             按块旋转查询（唯一的数学核心）
│   │       ├── attention.py        自定义 attention + 物理重排参考实现（对拍用）
│   │       ├── prompts.py          thinker/writer 视图提示 + 哨兵 + 探针（中英）
│   │       ├── mode.py             探针插入、yes/no 判定、探针 KV 隐藏
│   │       └── loop.py             双流调度：推进、冻结、解冻、产出事件
│   ├── server/
│   │   ├── state.py                [改] 去掉 mirror 编排，改为 async 运行时状态
│   │   ├── routes_control.py       [改] 删 /mirror/*、/think；加 /async/{state,pause,resume}
│   │   ├── schema.py               [改] 去 mirror_enabled（保留 thinking_level）
│   │   ├── routes_v1.py            [改] meta 去 mirror
│   │   ├── stream.py               [留] 已有的 content + reasoning 双通道正好够用
│   │   └── app.py                  [留]
│   ├── cache/
│   │   ├── prefix.py               [删] → _deprecated/
│   │   └── session.py              [改] 会话 ↔ KVBlocks 生命周期绑定
│   ├── mirror/                     [删] → _deprecated/mirror/
│   ├── config.py                   [改] 删 mirror 段默认值与读取
│   ├── errors.py / scheduler.py    [留]
│   ├── tools/                      [留]
│   └── vision/                     [留] 与本方案无关，不阻塞
├── .test/bin/                      运维与自检（按 §5 改）
├── labs/                           实验台（按 §5 改）
├── docs/notes/                     本文件 + MIRROR 笔记（标注弃用）
├── _deprecated/                    ⬜ 新增：mirror/ + prefix.py + 旧实验报告
├── config.yml, start.bat, stop.bat, README.md
├── llama.cpp/                      [留] P4 基线
└── models/                         GGUF（基线）+ Qwen3-0.6B（HF，新引擎用）
```

### 4.2 模块职责与依赖规则

| 文件 | 职责 | 允许依赖 | 不得依赖 |
|---|---|---|---|
| `blocks.py` | 纯数据：块偏移、长度、可见性、位置基址 | 标准库 + torch | transformers、server |
| `rope.py` | 纯数学：给定 `(块, 块内位置, 视图)` 算出查询旋转角 | torch | transformers、blocks |
| `attention.py` | 把 blocks + rope 接进 attention 计算 | blocks、rope、transformers | server |
| `prompts.py` | 只要字符串常量与拼装函数 | 标准库 | 其它全部 |
| `mode.py` | 探针插入时机、yes/no 判定、隐藏探针 KV | blocks | server |
| `loop.py` | 调度两条流、产出事件 | 以上全部 | server |
| `engine.py` | 兑现 `MeowLLMEngineBase` 契约 | loop、config | server |
| `server/**` | 只认 `engine/base.py` 的抽象 | base、config | `dualstream` 内部 |

**硬规则**：`server/**` 不许 import `engine/dualstream/*` 的具体实现，只能过 `factory` 拿到抽象。

### 4.3 接口扩展（最小改动）

`MeowLLMGenEvent` 增加一个字段，标明 token 来源：

```python
stream: Literal["thinker", "writer", "mode"] = "writer"
```

- `writer` → SSE 的 `content`（用户可见）
- `thinker` → SSE 的 `reasoning_content`（对项目侧就是"思考内容"，语义完全一致）
- `mode` → 不发给用户，只进 `/control/stats`（记录 pause/resume 事件）

**OpenAI 契约零改动**，项目侧 70 处调用不动。

---

## 5. MIRROR 清理清单

### 5.1 可以直接删（MIRROR 专属，无其它用途）

| 路径 | 内容 | 体积 |
|---|---|---|
| `meowllm/mirror/` | prompt/core/state/loop/`__init__`，10 个文件 | 79 KB |
| `meowllm/cache/prefix.py` | 前缀 KV 记账（新引擎自己管 KV，已无意义） | 5.6 KB |

### 5.2 建议移到 `_deprecated/` 而不是删

| 路径 | 理由 |
|---|---|
| `labs/RESULT_MIRROR_对比.md` | 负结果有价值：证明"应用层叙事在弱模型上不产生行为收益" |
| `docs/notes/MIRROR_三线程是怎么工作的.md` | 记录过机制理解，便于日后对比 |
| `docs/[参考价值-高]MIRRORConvergingCognitivePrinciples.pdf` | 1.67 MB，可留可删 |

### 5.3 需要改代码去引用（不是删文件）

| 文件 | mirror 命中数 | 怎么改 |
|---|---|---|
| `labs/server.js` | 42 | ARMS 从 A/B/C/D 叙事臂 → `S_seq` vs `A_async` |
| `meowllm/server/state.py` | 40 | 删 `schedule_mirror` / 叙事注入 / mirror 统计 |
| `labs/public/index.html` | 28 | 叙事面板 → **交错双流面板**（思考/输出分列，带"思考领先多少 token"） |
| `.test/bin/selftest.py` | 25 | 删 13–20、21–24 的 MIRROR 用例；保留契约用例；新增双流契约用例 |
| `meowllm/server/routes_control.py` | 20 | 删 `/mirror/{sid}`、`/mirror/reset`、`/think`；加 `/async/*` |
| `meowllm/config.py` | 16 | 删 `mirror:` 默认值与读取 |
| `meowllm/server/schema.py` | 5 | 删 `mirror_enabled` |
| `meowllm/server/routes_v1.py` | 5 | `_common_meta` 去 mirror |
| `config.yml` | 2 | 删整段 `mirror:`（约 30 行） |
| `meowllm/engine/base.py` · `stub.py` | 2 · 1 | 删 `mirror_enabled` 参数 |
| `labs/run_lab.bat` · `run_headless.js` | 4 · 2 | 去 mirror 参数 |
| `.test/bin/wait_ready.py` | 2 | 只是提示文案，改字样 |

> 注：`.scripts/download_qwen3_0.6b_hf.py` 里的 6 处 "mirror" 是 `--mirror`（hf-mirror.com 镜像站），
> 与 MIRROR 框架无关，**不要删**。

### 5.4 llama.cpp 现在不能删

**结论：留着，等 P4 跑完再删。**

三个理由：
1. **P4 需要顺序基线**。要证明 AsyncReasoning 有用，必须与"先想完再说"对比；
   那个基线就是 llama.cpp 引擎。删了就没有对照组。
2. **项目侧还没切过来**。`func/llm/port/**` 目前仍可以用它跑，等新引擎过 P5 的
   `project_probe.py` 再切。
3. 只有 87 MB，不占地方。

**将来可回收的空间**（合计约 1.4 GB）：

| 路径 | 体积 | 何时可删 |
|---|---|---|
| `llama.cpp/` | 87 MB | P4 完成后 |
| `models/Qwen3-0.6B-Q8_0.gguf` | 610 MB | 同上 |
| `bags/llama-*.zip` / `*.tar.gz` | 762 MB | 永远可删（只是安装包） |

---

## 6. 需要准备什么

### 6.1 模型（用户手动下载）

```bat
cd /d D:\.Meowlisis\.vendor\.MeowLLM

:: 先看要下什么（不下载）
..\..\runtime\311\python.exe .scripts\download_qwen3_0.6b_hf.py --list-only

:: 正式下载（约 1.4 GB，带总进度条，支持断点续传）
..\..\runtime\311\python.exe .scripts\download_qwen3_0.6b_hf.py

:: 国内网络若慢，改用镜像站
..\..\runtime\311\python.exe .scripts\download_qwen3_0.6b_hf.py --mirror
```

产物落在 `.vendor/.MeowLLM/models/Qwen3-0.6B/`（7 个文件，1449 MB）。
**注意**：现有的 `Qwen3-0.6B-Q8_0.gguf` 是 GGUF，transformers 读不了，必须另下这份。

### 6.2 环境（已实测可用）

```
torch 2.11.0+cu128   cuda=True   RTX 5060  sm_120   7.28/8.55 GB free   ✅
transformers 5.3.0                                                     ⚠️ 见 §7 风险 2
accelerate / safetensors / requests / tqdm                             ✅
bitsandbytes                                                           0.6B 不需要
```

### 6.3 提示词（我写）

论文 prompt 是英文（Figure 2）。中文场景需要：
- Thinker 视图系统提示：「我在思考模式，用户看不到我的话……」
- Writer 视图系统提示：「我在输出模式，基于已有的部分思维链开口，**不要跑到思考前面**」
- 两个哨兵串（`[系统会在这里继续写回复]` / `[更多想法会出现在这里]`）
- 探针句中文化，并实测 `是/否` 与 `yes/no` 哪个判定更稳

---

## 7. 三个硬风险

### 风险 1：0.6B 可能跟不上双视图提示

论文最小模型是 **Qwen3-8B**（还有 GPT-OSS-20B/120B）。0.6B 很可能：
- 理解不了"思考模式 / 输出模式"的角色切换
- yes/no 自控几乎全错

**对策**：0.6B 只用来**证明机制正确**（对拍通过 + 并行出 token），不期待行为质量。
行为验证需 4B 以上（8 GB 跑 4B-4bit 约 3–4 GB，可行）。

### 风险 2：transformers 5.x 的 attention 重构

5.x 换了统一 attention 接口，`position_ids` 语义与 4.x 有差异，monkeypatch 点会漂。

**对策**：为这个引擎单独建 venv 并锁 4.5x；或自己维护一份 `Qwen3Attention.forward` 副本（约 50 行）。

### 风险 3：错得静默

块 KV + 查询旋转只要错一点，模型**仍会输出看起来通顺的话**，但语义已偏。

**对策（强制）**：P2 必须实现"物理重排"参考版（把 token 真的按视图顺序拼成一条序列正常前向），
断言 `max|Δlogits| < 1e-4`。**对拍不过不许进 P3。**

---

## 8. 分阶段与验收

| 阶段 | 内容 | 验收标准 | 估时 |
|---|---|---|---|
| **P0** | 下权重、建 venv、跑顺序基线 | TTFT / tokens·s⁻¹ 落表 | 半天 |
| **P1** | 单视图 + 自定义 `position_ids` | 给定 pos 时输出与自然顺序**逐 token 一致** | 1 天 |
| **P2** | blocks + rope + attention + **对拍** | `max\|Δlogits\| < 1e-4` | 3–4 天 |
| **P3** | 双流 + 模式切换 + SSE | curl 看到思考/输出**交错**到达；stats 报"思考领先 token 数" | 2–3 天 |
| **P4** | 指标 + A/B（llamacpp 基线） | 一张对照表 + 明确结论 | 1–2 天 |
| **P5** | 项目侧接入 | `project_probe.py` 仍 8 PASS / 3 WARN / 0 FAIL | — |

---

## 9. 立即第一步

P1 的地基只有一件事：**`position_ids` 是否真的可控且生效**。

```python
# .scripts/ar_smoke.py（待写）
model = AutoModelForCausalLM.from_pretrained("models/Qwen3-0.6B", dtype=torch.bfloat16, device_map="cuda")
ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to("cuda")

pos = torch.arange(ids.shape[1], device="cuda").unsqueeze(0)
out_a = model(input_ids=ids, position_ids=pos).logits[0, -1]

pos2 = pos.clone(); pos2[0, -1] = 999          # 故意改一个位置
out_b = model(input_ids=ids, position_ids=pos2).logits[0, -1]

print("position_ids 生效：", not torch.allclose(out_a, out_b))
```

若 `position_ids` 被忽视（两者 logits 相同），整个方案要换实现路径（改 attention 内部），
必须在这一步就发现。
