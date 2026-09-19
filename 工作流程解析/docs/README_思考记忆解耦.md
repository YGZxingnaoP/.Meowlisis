# Meowlisis 思考—记忆解耦架构（δ-mem × MIRROR）· README

> 目标：解决喵呜系统的两个原始问题——**① 回复不跟话题/求全**；**② 记忆记了用不上、理解差**。
> 方法：**思考与输出彻底解耦**（MIRROR 式）+ **记忆直接参与注意力**（δ-mem 式）+ **每用户低秩矩阵**（CLS 式）。
> 形态：**单骨干（自托管）+ 两套 LoRA（思考步用/输出步用）+ 共享记忆基底**（形态 A）。

---

## 0. 术语与形态澄清

### 0.1 三种形态：先按「骨干份数」区分（务必看这一列）
> 约定：**"模型"= 一份独立的骨干网络**。同一份骨干上挂几套 LoRA，**仍然只算 1 个模型**。

| 形态 | 骨干份数 | 具体构成 | 隐藏状态 | 能否挂 δ-mem | 出处 |
|---|---|---|---|---|---|
| **MIRROR 形态** | 0（调 API） | 外部 API 模型；仅靠 prompt 分"思考/输出" | ❌ 拿不到 | ❌ 不可能 | `D:\Git\MIRROR` |
| **形态 A（本方案）** | **1** | 一份冻结自托管骨干 + **两套 LoRA**（思考步用 1 套、输出步用 1 套，参数不重叠） | ✅ 共享 | ✅ 可直接耦合 | 本 README |
| **形态 B（否）** | **2** | **两个独立模型**：一个负责思考、一个负责输出 | ❌ 不同空间 | ⚠️ 要加"桥" + 对齐损失 | 备选对照 |

**要点**：
- **形态 A 只有 1 个模型**；"两套 LoRA"只是同一骨干上的两组小参数，**不等于"两个模型"**。
- MIRROR 是形态 A 的"**无训练、无记忆耦合退化版**"。A 必须自托管，因为 δ-mem 需要隐藏状态。

### 0.2 为什么选 A（结论）
- 问题1（偏题）≈ 80% 靠**框架**解决 → A/B 无差别。
- 问题2（记忆）只有 δ-mem 能解，而 δ-mem 必须挂在**输出模型**上、且需隐藏状态 → **只有 A 成立**。
- B 会被迫退回"文本记忆"，等于现状。
- 所有被引系统（MIRROR/FLAIR/δ-mem/CLS）都是 A 型。

---

## 1. 理论依据及实验目标

### 1.1 理论依据（论文支撑）
| 来源 | 借用的机制 |
|---|---|
| **MIRROR**（arXiv 2506.00430） | 并行内心独白（Goals/Reasoning/Memory）；Cognitive Controller **合成有界叙事**；**每轮重构**而非累积；快响应 + 慢巩固 |
| **δ-mem**（arXiv 2605.12357） | 紧凑在线联想记忆 `S∈R^{r×r}`；**门控 delta 更新**；读出 → **注意力低秩修正（q/o）**；冻结骨干、SFT |
| **CLS**（bioRxiv 2026） | **门控 LoRA / masked LoRA**：每-episode 低秩适配 + **赢者通吃门控** + 慢巩固（replay） |
| FLAIR / TVS-ReVerT（对照，非本阶段） | latent 推理的 ELBO 训练；口语化增量解耦（列为非目标/可选） |

### 1.2 要解决的两个原始问题
- **问题1**：回复每次都 10~30 字（分段假象），但整轮趋向"覆盖全部素材、求全、偏题"。
- **问题2**：记忆能记能取，但靠词面/文本注入，模型用不起来、理解差。

### 1.3 假设与证伪条件
| 编号 | 假设 | 指标 | 证伪条件 |
|---|---|---|---|
| H1 | 思考/输出解耦 + 焦点锁 → 更贴话题 | 偏题率 | 与不分区提示词无显著差异 |
| H2 | δ-mem > 文本记忆（同内容） | 记忆召回、no-context 正确率 | D ≤ T |
| H3 | 跨轮持续思考 > 每轮现算 | 下轮连贯性/预判命中 | 无差异 |
| H4 | per-user 状态减弱跨用户干扰 | 污染率 | >0 且显著 |
| **H5** | **M+D 超加性（协同）** | 综合分 + 两失败模式联合改善 | M+D ≤ max(M,D)+ε |

### 1.4 实验目标（成功判据）
1. 机制正确：改造后前向/损失可训练、收敛、两套 LoRA 无泄漏（改 LoRA_think 不影响 LoRA_talk）。
2. 记忆进注意力：**no-context 测试**出现增益（复现 δ-mem 签名结论）。
3. 偏题率 ↓ ≥ 20pt；记忆使用率 ↑ 显著。
4. 多用户污染 ≈ 0，随用户数可扩展。
5. 端到端：真实日志盲评偏好 ↑，延迟/成本在阈值内。

---

## 2. 方向验证方案（先证伪方向，再投入训练）

### 2.1 三层验证
| 层 | 问题 | 失败即停 |
|---|---|---|
| L1 机制 | 能跑、收敛、无泄漏 | 不收敛 / S 爆炸 / 两套 LoRA 互相泄漏 |
| L2 有效性 | 两个问题是否缓解 | 任一指标不升 |
| L3 归因 | 增益来自哪个组件？是否协同 | 拆开后增益消失 |

### 2.2 三条"生死判定门"（Go/No-Go）
| 门 | 检验 | 通过标准 | 失败后果 |
|---|---|---|---|
| **G1** | **写策略有效性（N1）**：思考选择写入 vs 确定性写入 | 思考写入 ≥ 确定性 | 不能主张 N1 → 论文降级 |
| **G2** | **no-context 复现**：移除历史明文只留 S | 显著高于无 S 基线 | 记忆没进注意力 → N2/N7 塌 |
| **G3** | **协同超加性（H5）** | M+D > max(M,D) | 无协同 → 只能做工程/系统论文 |

### 2.3 受控合成任务（便宜，先跑）
1. **联想召回**：注入 key→value，移除明文，用 key 查询。
2. **写策略对照**：确定性写入 vs 思考选择写入（G1 的核心）。
3. **记忆总线闭环**：思考步写 intent → 输出步读并说 → 输出步写 utterance → 下轮思考步读（N3）。
4. **写粒度**：TSW / SSW / MSW。

### 2.4 预注册证据（先定图，再跑实验）
- Figure 1：两失败模式（偏题率 × 记忆漏用率）二维散点 → M、D 落在**正交方向**，组合在左下角。
- Figure 2：G1 柱状图（写策略对照）。
- Figure 3：G2 的 no-context 增益。
- Table：消融矩阵（层/分支/r/写粒度/训练方式/per-user）。

---

## 3. 实际实施计划（工程 + 训练）

### 3.1 架构定稿（形态 A）
```
冻结共享骨干 φ
 ├─ 两套 LoRA：LoRA_think（思考步用）, LoRA_talk（输出步用）   ← 参数不相交
 ├─ δ-mem 旁路：按步条件投影 Wdq^step, Wdo^step, Wq^m, Wk^m, Wv^m, Wb
 └─ 记忆银行 S = { S^{(层, 用户, 主题槽, 步骤标签)} }, 标签∈{intent, utterance}
```
**读写（每层）**
```
qm,km = l2norm(tanh(Wq^m x + e_step)), l2norm(tanh(Wk^m x + e_step)); vm = Wv^m x
beta  = sigmoid(Wb (x ⊕ e_step) + b); lam = 1 - beta
r     = S^{(..,tag_read)} @ qm
dq,do = Wdq^step @ r, Wdo^step @ r
q~    = q + (alpha_step/r_dim) dq
y~    = Attn(q~,K,V) + (alpha_step/r_dim) do
S     = Diag(lam) S + Diag(beta) outer(vm - S@km, km)
```
**时序契约（N3 闭环）**
```
本轮: 思考 读S → 写S(intent) → 输出 读S(intent) → 说 → 写S(utterance)
轮间: 输出结束 → 思考继续 读S(utterance) → 更新 plan_next → 写S(intent')
```

### 3.2 训练方案（跨步信用分配 = N7）
| 阶段 | 内容 | 损失 |
|---|---|---|
| T-a 写用性预训 | 只训 δ-mem 写投影，专家给"理想写入" | `L_reco` |
| T-b 交替优化 | 冻结 LoRA_talk 训 LoRA_think → 冻结 LoRA_think 训 LoRA_talk（用输出步损失下降当奖励） | `L_talker_CE` |
| T-c 联合微调 | 两套 LoRA（思考步/输出步）+ 写用性对比 | `L = L_talker_CE + λ1 L_write_useful + λ2 L_align(sg) + λ3 L_time` |

`L_write_useful = -log softmax(sim(read(S,Q+), m+))`（正确下轮记忆 vs 干扰项）。
**超参**：`lr=2e-4`，cosine + warmup 0.1，有效 batch 32，bf16；`r=8, α=16` 起步，q/o 分支，全部层。

### 3.3 数据管线
```
输入源： character/memory/*.txt（原始轮次）
        character/abstract_memory/meow-*.json（事件/tags/topics/evidence）
        character/info/users_info/*_latest.json（用户档案）
输出样本： {user_id, time, history[], query, response, memories[], profile{}, focus, plan_next}
切窗：以每条 AI 回复为锚，前 N 轮为 history，同用户记忆为 C；按时间后 10% 做验证。
```

### 3.4 里程碑（M0–M4）
| 里程碑 | 内容 | 训练 | 算力 | 工期 | 验收 |
|---|---|---|---|---|---|
| **M0** | 数据统一 + eval 基建 + 基线分 | 否 | CPU | 2~3 周 | 一键跑出基线 |
| **M1** | 合成任务 + 三条门（G1/G2/G3） | 否/轻 | 1×24G | 1~2 周 | 门全绿才继续 |
| **M2** | δ-mem 复现 + 消融 + 解耦变体 | 是 | 1~2×24G | 3~6 周 | no-context 增益 |
| **M3** | 每用户矩阵（污染/规模/路由） | 是 | 1×24G | 2~4 周 | 污染≈0，可扩展 |
| **M4** | 端到端接入 + 在线 A/B | 是 | 1×24G + 线上 | 1~2 周 | 两问题改善、偏好↑ |

### 3.5 风险与回退
| 风险 | 对策 |
|---|---|
| 写策略无效（G1 失败） | 退化为"记忆增强的框架版"，论文降级 |
| no-context 不复现（G2 失败） | 检查写入/读取实现与门控 |
| 干扰/覆写 | MSW 多状态 + 按步门控；禁裸大矩阵 |
| 过拟合（单用户样本少） | 低秩 + 门控 + 全局先验 + 时间切验证 |
| 非平稳 | 复用 evidence 半衰期做时变正则 |
| 算力 | 单卡 4B 起步；混合部署（日常 API + 记忆场景本地） |

---

## 4. 项目接入实践计划（落到 Meowlisis）

### 4.1 接入原则
**编排层（`func/**`）不改**；新增旁路 + 新增本地服务。理由：`func/llm/port/*.py` 走 OpenAI 兼容 base_url。

### 4.2 服务层
- 新增一个**本地 port**（`func/llm/port/local.py`），指向本地 OpenAI 兼容服务。
- **自定义推理服务**：在 HF `generate`（或 vLLM 自定义层）里挂 **δ-mem hook**（读/写 S、q/o 修正）。这是**唯一必改**处，位于模型侧。

### 4.3 框架层（新增 `func/thinker/`）
| 文件 | 职责 |
|---|---|
| `think_state.py` | 读写 `.temp/think_state_<user>.json`（focus/thinking/plan_next/open_threads） |
| `think_loop.py` | 后台思考循环（用户消息后 / TALK 结束后 / 空闲 tick；salience 门控） |
| `think_prompt.py` | 思考提示词 + Talker 分区 system（内心/焦点/约束/少量记忆） |
**挂接点**
- `llm/llm_core.py :: _ai_response`：开头读 ThinkState 注入；末尾起后台思考线程。
- **升级 `llm_active/inherit/inherit_core.py`**（已是跨轮延续雏形）→ "延续思考"。
- `llm/output.py`：`split_limit=6` 切句适配短句流，无需改。

### 4.4 数据/记忆层（全部复用，不改语义）
- `meow-*.json` → δ-mem 的写单元（按 time 排序，SSW 按条写）。
- `tags.json` → 主题槽划分与门控键。
- `*_latest.json` → S_0 初始化 + 门控键。
- 保留现有 tag 打分 / evidence 衰减 / 摘要条目。

### 4.5 灰度与回滚
```
shadow（只记录不生效）→ 小流量 A/B（按用户分流）→ 全量
每阶段留开关： think_enable / delta_mem_enable / per_user_enable
异常回退：切回原 API port
```

### 4.6 观测与评测埋点
- 复用 `llm/narration` 打分（长度/水词/平滑分）。
- 新增埋点：偏题率、记忆使用率、no-context 抽样、延迟 p50/p95、显存。
- 每题记录 traceid，便于失效剖析。

### 4.7 接入验收
- 接入后**原功能不回退**（唱歌/工具/主动回复等）。
- 延迟增量在预设阈值内（δ-mem 论文显示显存开销极小，但解码略慢，需实测）。
- 可一键回滚。

---

## 5. 论文贡献方向

### 5.1 主张清单
| # | 贡献 | 为何新 | 依赖 |
|---|---|---|---|
| **N1** | 思考作为记忆的**写策略**（Write Policy） | δ-mem 是确定性写入；由思考决定写什么 | G1 |
| **N3** | **跨轮持久思考 + 双向记忆闭环** | MIRROR 只有单向、上一轮 insights | G1/G3 |
| **N5** | 两失败模式**正交 + 超加性** | 组合 > 单组件之和 | G3 |
| **N7** | **解耦认知下的跨步信用分配 + 按步记忆总线** | 参数不相交的两套 LoRA 如何共享/训练记忆基底 | 全 |
| N2 | 隐/参数化内心独白 | MIRROR 全文本 | G2 |
| N4 | 焦点作为共享控制变量（约束生成 + 记忆路由） | 两原文都无 | 消融 |
| N6 | per-user 状态 × MSW × 门控 | 组合方式新 | M3 |
| N8 | 三种每用户矩阵实现的**横向评测与决策表** | 实用贡献 | M3 |

### 5.2 最强组合与标题
**N1 + N3 + N5 + N7**。
标题候选：
1. *Think-to-Write: Between-Turn Inner Monologue as a Write Policy for Attention-Coupled Online Memory*
2. *Decoupled Cognition: Coupling Persistent Inner Monologue with Attention-Level Associative Memory*
3. *Two Failure Modes, One Architecture: Complementarity of Deliberative Thinking and Online Memory*

### 5.3 论文结构（对齐里程碑）
| 节 | 来源 |
|---|---|
| Intro：两个正交失败模式 | 问题1、2 |
| Related：δ-mem/MIRROR/FLAIR/CLS，指出"无人做解耦耦合" | — |
| Method：按步记忆总线 + 三种训练方式 + 注意力改动 | §3.1–3.2 |
| Exp-1 机制：合成任务、稳定性、写策略对照 | M1 |
| Exp-2 记忆：no-context 复现 + 解耦消融 | M2 |
| Exp-3 可扩展：多用户污染/路由/决策表 | M3 |
| Exp-4 应用：端到端 A/B + 盲评 | M4 |
| Analysis / Limitations / Ethics | 各阶段 |

### 5.4 投稿路径
```
M1 通过 → Workshop / 系统 demo
M2 no-context 复现 + 消融完整 → Findings
M3–M4 + 标准基准打平 → 冲顶会
先 arXiv 占位（放 N7 机制 + 初步结果），再补实验
```

### 5.5 硬条件
1. G1 写策略对照成立；2. G2 no-context 复现；3. 完整消融 + 3 seeds + 开源；4. 中性化人设（避免 NSFW 伦理风险）。

### 5.6 伦理与定位
论文中以"情感陪伴助手"中性描述；**为论文单独构造无 NSFW 人设**做实验；明确安全边界与用户数据使用声明。

---

## 附：一页速查
- **形态**：A（单骨干自托管 + 两套 LoRA（思考步/输出步） + 共享记忆银行）。
- **两个杠杆**：框架（贴话题）+ δ-mem（记得住）。
- **三条门**：G1 写策略 / G2 no-context / G3 协同。
- **四个里程碑**：M0 数据评测 → M1 方向验证 → M2 δ-mem → M3 多用户 → M4 接入。
- **一个新技术点**：N7（解耦认知下的跨步信用分配）。
