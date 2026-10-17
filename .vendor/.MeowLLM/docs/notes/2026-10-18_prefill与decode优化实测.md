# 双流 prefill / decode 优化实测报告

> 环境：AutoDL RTX 5090（32.6 GB）· Qwen3-8B bf16 · torch 2.8.0+cu128 · transformers 5.3.0
> 模型经 SSH 隧道挂在本地 `http://127.0.0.1:18100`
> 测试时间：2026-10-18

---

## 1. 改了什么

| # | 改动 | 文件 | 语义影响 |
|---|---|---|---|
| 1 | **PROMPT 块容量动态化**：从"等于 `n_ctx`"改为"按实际 prompt 长度向上取 64 的整" | `engine/dualstream/loop.py` | 无 |
| 2 | **单块 prefill 走原生 SDPA**：可见块只有自己（P 首填）时，`delta` 全为 0，直接 `F.scaled_dot_product_attention(is_causal=True)` | `engine/dualstream/attention.py` | 无（数学等价，仅浮点差异） |
| 3 | **decode 快路**：按有效长度切片，跳过 padding 掩码、`logical` 索引、容量对齐 | `engine/dualstream/attention.py` | 无（padding 权重本来就是 0） |
| 4 | 开关 `engine.dualstream.fast_prefill`（默认 `true`），置 `false` 可回退旧实现做 A/B | `config.py` / `config.yml` | — |

改动 1 与 2 解决 **prefill 的显存天花板**，改动 3 解决 **decode 的每步开销**。

---

## 2. 为什么之前那么慢

先用数据把耗时拆开（同一 prompt，8B）：

| 阶段 | 改之前 | 改之后 |
|---|---|---|
| decode 每步 | **65 ms** | **34 ms** |
| plain（原生 SDPA 单流）每 token | 21–30 ms | 21–30 ms |
| prefill 3.4k token | 1.57 s | 0.89 s |
| 双流可用上限 | ~900 token（再长 OOM） | **≥16k token** |

两个独立原因：

1. **prefill 按"容量"算分数**：旧代码 `capacity[PROMPT] = n_ctx`，于是每次 prefill 都要算 `qlen × (P容量 + T容量 + W容量)` 的分数矩阵。`n_ctx` 提到 32768 后，900 token 的 prompt 就要 3.9 GB —— 这才是 OOM 的来源，而不是历史真的太长。
2. **decode 走手写 attention**：每层每步都重建 padding 掩码、`arange`、`cat`，共 36 层 × ~20 个小算子。把"按容量切片 + 掩码"换成"按有效长度切片"，每步从 65 ms 降到 34 ms。

**总耗时 ≈ (思考 token + 输出 token) × 34 ms + prefill(1–3 s)**。

所以"这么久"的主因是**思考 token 多**：`thinking.budgets.medium = 768`，8B 在难题上基本会把 768 用满 → 768 × 34 ms ≈ **26 s**。跟 prompt 长度关系不大（见下表：16k prompt 只比 452 token 慢几秒）。

---

## 3. 实测结果

### 3.1 长度阶梯（thinking=medium，max_tokens=64）

| pairs | prompt token | 模式 | 思考 token | 耗时 |
|---:|---:|---|---:|---:|
| 10 | 452 | dual | 278 | 9.8 s |
| 20 | 882 | dual | 214 | 7.5 s |
| 40 | 1 742 | dual | 468 | 15.9 s |
| 80 | 3 462 | dual | 320 | 11.3 s |
| 160 | 7 022 | dual | 612 | 30.2 s |
| 260 | 11 522 | dual | 399 | 24.4 s |
| 400 | 16 122 | dual | 588 | 37.8 s |
| 560 | 14 982 | dual | 422 | 27.9 s |

耗时与"思考 token"强相关，与 prompt 长度弱相关 —— 说明瓶颈已从 prefill 转到 decode。

### 3.2 prefill 专项（`max_tokens=8`、`think_budget=8`，基本只测首填）

| prompt | fast_prefill=false | fast_prefill=true |
|---:|---|---|
| 882 | 0.81 s · dual | 1.25 s · dual（含首次 CUDA 预热） |
| 3 462 | 1.57 s · dual | **0.89 s** · dual |
| 7 031 | ❌ OOM → 回退 plain（1.10 s） | **1.30 s · dual** |
| 11 531 | ❌ OOM → 回退 plain（1.53 s） | **1.81 s · dual** |
| 16 122 | — | **2.45 s · dual** |

结论：SDPA 快路的**主要收益是显存**（≥7k 不再掉单流），速度基本持平或略好；它不是"变快"的银弹，但把双流上限从 ~900 token 拉到 16k 以上。

### 3.3 语义一致性

同一 prompt、`temperature=0`（贪心）、`thinking_level=low`：

| 设置 | 输出 | 思考前缀 |
|---|---|---|
| fast_prefill=true | `喵，鸡23只，兔12只。` | `好的，我现在要解决这个鸡兔同笼的问题…` |
| fast_prefill=false | `喵，鸡23只，兔12只。` | 同上 |

- 同设置连跑两次：输出完全一致
- 快慢两路的输出与思考开头一致，差异只在浮点（预期 ~1e-7，与仓库 `reference.py` 对拍记录同量级）

### 3.4 主项目真实请求（203 条短期记忆）

```
原始 prompt : 9138 token
裁剪后      : 3749 token（受 context.max_prompt_tokens 限制）
模式        : dual        ← 改动前是 plain（思考为 0）
耗时        : 14.5 s
输出        : 在呢，你干嘛，又想骗我？
```

---

## 4. 配置项

```yaml
engine:
  dualstream:
    fast_prefill: true       # 单块 prefill 走 SDPA + decode 走长度切片；false=旧实现
context:
  n_ctx: 32768               # 硬上限
  max_prompt_tokens: 4096    # 裁剪后的 prompt 上限（云端用环境变量覆盖为 16384）
  dual_max_prompt_tokens: 2048   # 超过则单流（云端 16384）
thinking:
  budgets: { "off": 0, low: 256, medium: 768, high: 2048 }
```

**想更快**：调小 `thinking.budgets.medium`（768→256 约省 17 s）。
**想更长上下文**：调大 `max_prompt_tokens` / `dual_max_prompt_tokens`；16k 时 prefill 约 2.5 s、显存仍有余量。

---

## 5. 复现方式

```powershell
# 云端同步 + 重启（会自动等端口释放、校验是否落到 18100）
python .vendor\MeowLLM\.test\bin\cloud_sync_start.py

# 长度阶梯
python .vendor\MeowLLM\.test\bin\probe_fast_prefill.py

# 主项目真实 prompt 链路
python .vendor\MeowLLM\.test\bin\probe_project_chat.py
```

A/B 对照：在 `cloud_sync_start.py` 的启动命令里加
`MEOWLLM__ENGINE__DUALSTREAM__FAST_PREFILL=0` 后重启即可。

---

## 6. 仍未做的

- **decode 没能用 SDPA**：每块要用不同旋转的 query 再拼分数，单次 SDPA 只有一个 query 张量，逐块 SDPA 再相加会把 softmax 归一化拆散（数学上不等价）。要再快只能上 CUDA Graph / `torch.compile`，或按论文说的用 PagedAttention 自定义 kernel。
- **batch=2 合并前向**只在双流同时推进时生效；writer 停下后是单行前向，没有额外收益。
