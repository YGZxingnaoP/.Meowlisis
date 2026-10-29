# 记忆模块深度分析：Meowlisis「摘要记忆」× BaiShou-Next「记忆图谱」

> **性质**：纯分析文档，**未修改任何代码**、未改动任何运行时数据文件。
> **基线**：Meowlisis = 本工作区当前工作树（`D:\.Meowlisis`）；BaiShou-Next = `main` @ `645f43a`（2026-10-26，GitHub）。
> **约定**：每一条代码结论都带 `文件:行号`。Meowlisis 用工作区相对路径；BaiShou-Next 用仓库内完整路径（保留 `packages/` 等前缀）。凡属推导而非直读的，标注 **〔推断〕**；未能核验的集中列在 §8.3，不混入结论。

---

## 0. 结论先行

| # | 结论 | 依据 |
|---|---|---|
| **C1** | 两者的差别不是「图谱 vs 摘要」，而是**「在线零决策、写死注入」 vs 「离线构建、在线由模型自己决定查什么」**。白守的召回 100% 是 LLM 主动调用的工具；Meowlisis 的召回 100% 是提示词构建时自动拼接。 | `func/catbrain/prompt_builder.py:89,97`；BaiShou `ai/src/tools/{vector-search,recall-relations}.tool.ts` |
| **C2** | Meowlisis 当前**违反了它自己的「速度优先」原则**：提示词构建路径上有 **1～2 次同步 LLM 往返**（`decide_recall` 无缓存，`_decide_topic` 缓存 60s）。这是可直读的代码事实，不是推断。 | `load_abmem.py:209-242,149-207`；`port/__init__.py:5-20` |
| **C3** | 「记录多了就不准」在两边是**同一个数学病**：召回候选集随语料线性增长，而精排的判别力不随语料增长。区别只是失效方式——Meowlisis 是**闸门失效**（一个词命中即满分，实测每条消息中位 17 条、均值 22.3 条通过闸门，且全部 `text_similarity == 1.0`）；白守是**入口短路**（名字有命中就永不走向量，锚点错则整条链错）。 | §5；`load_abmem.py:26,322-333`；`core/src/graph/graph-rag.service.ts:302` |
| **C4** | 两边都有一条「结构上近乎失效的第二通道」，这是精度损失的主因之一：Meowlisis 的 tags/joint/topic 三路信号（权重合计 0.5）在实测中几乎不提供区分度（91% 记录 accuracy 已封顶、47% 记录 strength 恒为 0、89% 参与人条目因字段名漂移永不命中）；白守的「关键词」通道对中文退化为整句子串匹配，且 RRF 量纲被向量压到 0.005 上限。 | §2.4/§2.5/§2.8-F7；§3.6；`database/src/repositories/hybrid-search.repository.vector-search.ts:18-25,104-115`、`ai/src/rag/hybrid-search.ts:42,75` |
| **C5** | 在「不做在线 AI 决策」的前提下，**白守的图结构仍然值得借，但只能借它的「离线索引与关系」，不能借它的「在线 agent 决策」**。可行的替代是：把召回换成「离线倒排索引 + 在线纯 CPU 查表 + 硬闸门 + 分级预算」，延迟目标从 +1 RTT 降到 +5ms 量级。 | §7 |
| **C6** | 两边**对『衰减』的立场完全相反**：Meowlisis 有完整的证据衰减（强化半衰期 30 天、质疑 180 天、净分归档）；白守全仓**没有任何时间衰减/遗忘曲线**，遗忘只靠软删除、边失效、人工复核。这不是谁对谁错，是「陪伴对话对象」与「个人史档案」两种产品目标的必然结果。 | `process/evidence.py:40-62`；BaiShou 全仓 `decay\|forget\|衰减` 仅命中画布动画参数 |

---

## 1. 阅读范围与方法

### 1.1 Meowlisis
- **代码**：`func/catbrain/**`（含 `AbstractMem` 全部子模块、`UserMemory`、`LongTermMem`）、`func/pipeline/{prompt_builder→catbrain/prompt_builder, msg_abmem, short_memory, toolbox_ltmem, system_prompt, toolbox_llm}`、`func/toolbox/napcat/llm/{napcat_llm, napcat_group_llm}`、`func/toolbox/{qq_response, napcat/groupchat/group_coordinator}`、`config.yml`。
- **数据实测**：以 `character/abstract_memory/meow-*.json`（432 条真实记录，2026-08-20 → 2026-10-23）为语料，用 `runtime/311/python.exe` + `jieba` **逐行复刻** `_text_similarity / _tags_similarity / _relevance / _score / _select / build_prompt` 的公式与阈值，对 `.temp/public_short_mem.json` 中 30 条真实用户消息做了召回模拟。所有数字可在 §8.1 复现口径下重算。
- **未做**：未启动主程序、未触发真实 LLM 调用（沙箱禁止写 `logs/`，且无必要——公式是纯函数）。

### 1.2 BaiShou-Next
- **代码**：GitHub 原始文件直读 + 子 agent 以 `git clone --depth 1 --filter=blob:none` 取得的工作树（5230 文件）交叉核对。二者一致后我才写入本文。
- **关键路径**：`core/src/graph/*`（≈4000 行）、`ai/src/rag/*`（≈1780）、`database/src/repositories/graph.*`+`hybrid-search.*`（≈5880）、`ai/src/tools/*`（≈6890，其中 5 个记忆工具）、`ai/src/agent/*`（≈8850）。
- **额外交叉验证**：我独立复核了子 agent 两条最尖锐的结论——「`vector_search` 的 FTS 分支实为 LIKE」与「`GRAPH_MAX_NEIGHBORS_PER_HOP = 40`」——均**与源码逐字一致**，故采纳。

---

## 2. Meowlisis 记忆栈解剖

### 2.1 分层与数据流

```
用户消息
  └─ qq_response / group_coordinator  ──► merged_text / plain_text
        └─ SystemPromptBridge.get_*_prompt()
              └─ MeowPromptBuilder.build()/build_group()        prompt_builder.py:75,103
                    ├─ _decide_recall(msg, uid)                 ← ★同步 LLM #1
                    └─ abmem.build_prompt(msg, uid, ...)        load_abmem.py:409
                          ├─ load()  读全部 meow-*.json（无缓存）
                          ├─ _rank()
                          │    ├─ _current_topic()               ← ★同步 LLM #2（60s 缓存）
                          │    ├─ jieba 分词 query
                          │    └─ 逐条 _score()  → 排序
                          └─ _select()  → markdown 注入
```

写路径是**完全异步**的旁路，不阻塞回复：`get_memory.cache_message()` 累计 `record.txt` 行数，达到 `summary_rounds` 后 `Thread(target=_summarize_worker)` 起后台线程（`record/get_memory.py:40-56`）。

### 2.2 数据模型（`character/abstract_memory/meow-YYMM.json`）

| 字段 | 类型 | 说明 | 实测（432 条） |
|---|---|---|---|
| `event` | str | 事件概括，约 50 字 | 均值 37.7 字，max 66 |
| `tags` | list[str] | ≤`tags_limit`(3) 个短语 | 1 个:36 / 2 个:191 / 3 个:155 / >3:50 |
| `topics` | list[str] | 仅限 5 值枚举 | — |
| `joint` | list[dict] | 参与人 | 425 条用 `id` 键、53 条用 `meowid` 键 |
| `importance` | float 0-10 | 重要度 | 均值 5.4，中位 6 |
| `accuracy` | int ∈{1,3,5} | 概括置信度 | **5 占 393/432 = 91.0%** |
| `evidence` | dict | `reinforcement / disputation / *_last_signal_at / sub_zero_*` | `reinforcement==0` 占 **203/432 = 47.0%** |
| `time` | `"YYYY-MM-DD-HH-MM"` | 事件时间 | 无缺失 |
| `id` | `mem_[0-9a-f]{12}` | 归一化文本+首个参与人的 sha256 前缀 | 无重复 |

分文件策略：按条目 `time` 的月份落 `meow-YYMM.json`，`save()` 时按 id 去重后整月重写（`load_abmem.py:120-147`）。当前 3 个文件共 ~308 KB。

**结构体检结论（重要）**：
- 近似重复（事件分词 Jaccard > 0.7）**0 对**，精确文本重复 0 组 → **写路径的去重是有效的**，问题不在写入污染。
- 但 tags 体系的质量很差：**275 个不同 tag，72.4% 只出现 1 次**；维护中的 `tags/tags.json` 词表只有 **69** 个，仅覆盖 `880/1116 = 78.9%` 的 tag 出现。
- tags 与本已存在的 `topics` 枚举**重复**：最高频 tag 依次是 闲聊 95、游戏 79、日常 78、情感 59——前四名里三个就是 topic 名。这使得「标签」这一路信号与「话题」信号冗余，且互相污染。
- 存在把**昵称当 tag** 的情况（实测记录中出现 `标签:…YGZ醒脑片、反复催促`）。

### 2.3 写路径（异步、重、多轮工具循环）

`MeowUpdateAbstractMemory.summarize()`（`record/update_abmem.py:396`）：
1. `_build_messages()`：摘要指令 + 角色卡 + **全部已有 tags 附件** + 最近 12 条已记忆要点 + 待概括原文（`:102-120`）。
2. `_run_flow()`：最多 `tool_rounds`=80 轮工具循环（`:268`）。模型先调 `save_memory_summary` 提交事件，系统回传**该事件话题+标签交集范围内的**已有记忆（最多 `scope_reply_limit`=80 条，`:240-252`），模型再用 `grep_memories`（≤10 次）在范围内检索，最后用 `judge_memory_relation` 指认 `strengthen / weaken / new`。
3. **去重主键**：`mem_` + sha256(归一化 event + 首个参与人)（`process/dedup.py:23-27`）。命中即 `_apply_same`（强化 +0.5、accuracy+1、合并 tags/topics/joint）。
4. **审查**：`_ensure_review().review()` 用另一个 LLM 逐条判 pass/kind/accuracy，不合格丢弃（`review/review_core.py:83-111`）。
5. **落盘**：`_init_evidence()` 后 append + `save()`；然后 `_archive.scan()` 扫负分条目。

`_scope()` 是写路径的**候选召回器**，也是它最脆弱的一环（`:210-227`）：

```python
if not (topics & set(item.get("topics") or [])): continue      # 必须话题相交
if tags and item_tags and not (tags & item_tags): continue      # 标签必须相交
```

在 275 个 tag、72% 单例的现实下，「标签必须精确相交」意味着**新事件的标签一旦是新词，范围就是空集**，于是模型被告知「该范围内没有已有记忆，action 填 new 即可」——只能新建，无法合并近义记忆。实测 `tags 全部为孤儿（不与任何其他记录重合）的记录占 10.0%`，这部分永远无法进入合并流程。

> 注意：`config.yml` 里 `max_events: 10` 是**死配置**——真正生效的是类常量 `MAX_EVENTS = 6`（`record/summary_tool.py:14`，被 `update_abmem.py:299,333` 引用）。`config.py:47` 读了但没有任何地方使用。

### 2.4 衰减与证据（Meowlisis 的核心设计资产）

`process/evidence.py`：

```
effective_reinforcement = r · 0.5^(Δt_days / 30)      # rein_half_life_days = 30
effective_disputation    = d · 0.5^(Δt_days / 180)     # disp_half_life_days = 180
score                    = eff_rein − eff_disp
status: score ≥ +1.0 → confirmed ; score ≤ −2.0 → archive_candidate
归档: 负分持续 sub_zero_days ≥ 14 天 → 移入 wrong_mem.json
```

初始强化值按 importance 映射：`≥10→0.8, ≥9→0.6, ≥8→0.4, ≥7→0.2, 其余→0`（`:15-24`）。

**这套设计本身是合理且少见的**（有质疑项、非对称半衰期、需持续负分才归档）。但**它当前的召回贡献接近零**，两个原因都可实测：

1. **一半条目 strength 恒为 0**：47.0% 的记录 `reinforcement == 0`，因为 importance < 7 一律给 0；而 importance 中位数正好是 6。在 `_score()` 里 `strength = min(score,5)/5`，所以这 47% 的 `strength` 分量恒等于 0。
2. **accuracy 完全丧失区分度**：91.0% 的记录 accuracy = 5（满分），`accuracy/5 = 1.0` → 该分量对 91% 的条目是同一个常数。

于是 `RANK_WEIGHTS` 里 `strength(0.20) + accuracy(0.10) = 0.30` 的预算，实际上只有不到 53% 的条目在其中一个分量上非零、且在 91% 的条目上 accuracy 是常数。**排序的实际自由度只剩 relevance(0.45) + recency(0.15) + importance(0.10)。**

归档侧：`wrong_mem.json` 现有 **25** 条，相对 432 条语料 = 5.8%；`disputation > 0` 的条目在 meow-2609 中仅 **3/254**。**衰减机制在实际数据上几乎没被激活**——原因不在衰减公式，而在**触发源**：`_apply_opposite()` 只能由写入时 LLM 的 `weaken` 判定触发（`record/update_abmem.py:375-378`），而实测 254 条里只有 3 条真的被削弱过。机制本身没问题，是入口太窄：要 14 天持续负分才归档，但「判为矛盾」这件事本身极少发生。

### 2.5 Tags 体系（用户点名的「tags 调用」）

| 用途 | 位置 | 机制 | 实测效果 |
|---|---|---|---|
| 写时生成 | `summary_tool.py:91-96` | 让模型「优先从已有 tags 附件选择」 | 词表仅 69 个，21% 的出现是新词；72% 单例 |
| 写时召回 | `update_abmem.py:210-227` | `tags & item_tags` **精确集合相交** | 标签新词 → 范围空 → 只能新建 |
| 读时打分 | `load_abmem.py:258-272` | 只看 `tags[:3]`，逐个分词求 `overlap/len(tag_words)` 取最大 | 单字 tag（如「听」）分词后为空 → 直接 0 |
| 清理 | `cleanup_mem.py:214-226` | 剔除泛化 tag + 回收孤儿 tag | 需人工跑；`generic` 集合含 topic 名 |

三个结构性问题：
1. **tag 与 topic 冗余**：前四高频 tag 中三个是 topic 枚举值（闲聊/日常/情感），权重 0.2 的 tags 通道与权重 0.2 的 topic 通道在统计上高度共线，等于把 0.4 的预算押在同一个弱信号上。
2. **精确相交过于刚性**：「异环」（29 条）与「Minecraft」（17 条）都是游戏，但集合相交判为不相交；「直播互动」与「直播提醒」也不相交。系统没有词形归一、没有同义表、没有上下位。
3. **读时只看前 3 个 tag 且是「tag 内命中率」而非「query 覆盖率」**：`overlap / len(tag_words)` 的分母是 tag 的分词数，不是 query 的词数 → 一个单字 query 命中一个单词 tag 就得 1.0，而一个 15 词的具体 query 命中一个双词 tag 得 0.5。**信号随 query 变长而衰减**，与直觉相反。

### 2.6 召回路径（重点）

`build_prompt()`（`load_abmem.py:409-434`）逐步：

```python
data   = self.load()                                   # 每次全量 json.load，无缓存
limit  = max(summary_top_limit, relevance_guarantee)   # = max(30, 8) = 30（8 实际被 30 吞掉）
ranked = self._rank(data, current_message, uid, topic_override)
if need_recall: ranked = _prioritize_months(...)       # 时间窗条目整体前置
lines  = ["# 喵呜的记忆"]
for item in self._select(ranked, limit): 按格式拼一行
```

`_score()`（`:344-370`）：

```
strength   = min(max(evidence_score,0), 5) / 5
accuracy   = accuracy / 5
relevance  = 0.5·text + 0.2·tags + 0.2·topic + 0.1·joint
recency    = 0.5^(age_days / 14)
importance = importance / 10
total      = 0.20·strength + 0.10·accuracy + 0.45·relevance + 0.15·recency + 0.10·importance
# evidence_score < 0 的条目直接不参与（返回 None）
```

`_text_similarity()`（`:322-333`）——**这是全部问题的数学核心**：

```python
words = msg_words - STOPWORDS          # jieba 切词，len>1，去停用词
hits  = sum(1 for w in words if w in event)   # 单向子串包含
return min(1.0, hits / OVERLAP_SATURATION)    # OVERLAP_SATURATION = 1.0
```

即：**只要消息里任意一个 ≥2 字、不在停用词表的词，作为子串出现在事件文本里，text 分量就是满分 1.0**。消息再长、命中再多也不会更高；反过来一个 20 字的具体问题，与一个 40 字的概括，其「相关性」只有一个布尔值。

`_select()`（`:394-407`）：沿 `total` 降序取，**只保留 `relevance ≥ 0.15` 的**，按 event 文本去重，取满 `limit` 为止。

#### 实测（复刻公式 + 真实语料 + 真实消息）

对 30 条真实用户消息（已剥掉 `【来自QQ，…】` 前缀，以免夸大），topic 固定为线上真实值「日常」（`.temp/current_topic.json` 内容）：

| 指标 | 结果 |
|---|---|
| 通过 `relevance ≥ 0.15` 闸门的条数 | **均值 22.3 / 中位 17 / min 0 / max 54**（语料 432 条，通过率 5.2%） |
| 其中 `text_similarity == 1.0` 的条数 | 与上完全相等（均值 22.3）→ **闸门实际就是「共享 ≥1 个词」的布尔判据** |
| 典型反例 | 「随便」「喵呜别唱了，好好说话」这类短句也让 24～27 条记忆通过 |
| 注入体积（limit=30，按确切行格式计算） | **30 条 = 3214 字符 ≈ 2400 token**，单行平均 **103.7 字符** |
| 其中元数据前缀占比 | `[话题:…｜标签:…｜参与:…｜时间:…]` 约占单行 **48%** |

一次真实查询的 top-8（query 是「…今天先睡觉了，明天再跟你讲故事吧」）：

```
1 话题:闲聊、日常 | 标签:QQ好友、MBTI测试、社交 | 时间:2026-08-27  YGZ醒脑片让喵呜去QQ群看消息、公布MBTI结果ENFP-T…
2 话题:日常、情感、爱好 | 标签:作息、说话方式、游戏、异环 | 时间:2026-09-27  主人不喜欢被催睡觉…
3 话题:日常、爱好 | 标签:英语六级、图书馆、学习 | 时间:2026-09-21  主人正在备考英语六级考试…
5 话题:日常 | 标签:学唱《星降る海》… | 时间:2026-08-25  主人反复催我学唱《星降る海》…
```

第 3、5 条与「睡觉/讲故事」无关，却因为「今天/明天/之前」这类被停用词表漏掉的时间词，或昵称碎片，拿到了满分 text 分量。**这正是「调用不精准」的现场快照。**

**为什么一个词就满分，会随记录增多而恶化**——这一点值得单独强调，因为它解释了现象的「增长性」：

`_select` 取的是「**任一** token 命中」的**并集**。单 token 命中率实测：`画` 11.6%、`游戏` 10.2%、`听` 5.8%、`异环` 6.7%、`说话` 4.6%、`直播` 4.9%。一条 10 词的消息，其并集很容易到 20 条以上。随着语料增大，常用词的命中率**单调上升并趋近 1**（`主人` 已达 86.3%，只是恰好被停用词表挡住），于是 pass 集会从「22/432」向「N」漂移。当 pass 集 > 30 个槽位时，**决定注入内容的不再是相关性，而是 strength/recency/importance 这些与查询无关的先验**——精度必然随语料增长而下降。这不是「数据脏」，是打分函数的量纲设计问题。

### 2.7 速度剖面（逐调用点）

一次群聊 @ 回复的提示词构建，同步链路里的网络调用：

| 序 | 调用 | 位置 | 是否有缓存 | 次数 |
|---|---|---|---|---|
| 1 | `decide_recall` → `force_tool_call` → `llm.chat` | `load_abmem.py:209-242` | **无** | 1（阈值触发路径 2 次：`decide` + `reply` 各建一次 prompt） |
| 2 | `_decide_topic` → `force_tool_call` → `llm.chat` | `load_abmem.py:180-207` | 有，`topic_update_interval`=60s | ≤1/分钟 |
| 3 | `load()` 全量读 3 个 json（~308 KB） | `load_abmem.py:80-109` | **无** | 每次 |
| 4 | `ShortMemory.load()` 全量读 `.temp/public_short_mem.json`（63 KB） | `short_memory.py:226-232` | 无 | 由 #2 触发 |

`force_tool_call()` 最多重试 **3 次**（每次都是一次完整 API 往返），且失败会追加两条消息再试（`port/__init__.py:5-20`）。使用 `deepseek-flash`（`config.yml:45,61`）。

**结论**：Meowlisis 的提示词构建**不是「快速及时」的**，它目前在最热的路径上插入了一次（群聊阈值触发路径两次）同步 LLM 往返，且没有任何超时/熔断/降级开关——`decide_recall` 抛异常才由 `prompt_builder.py:62-64` 兜底，正常慢请求会一直等。这与用户设定的「速度优先」原则直接冲突，是全篇最容易改善的一处。

### 2.8 已定位的具体缺陷（按影响排序）

| 编号 | 缺陷 | 位置 | 影响 |
|---|---|---|---|
| **F1** | `OVERLAP_SATURATION=1.0` + `hits/1.0` → 单词命中即满分，相关性是布尔值不是梯度 | `load_abmem.py:26,322-333` | 闸门失效；排序退化到先验 |
| **F2** | 单向子串包含 `w in event`，无 IDF、无长度归一、无同义 | 同上 | 高频词与稀有词同权；长事件天然占优 |
| **F3** | 数字/昵称碎片参与匹配：jieba 把 `2026`、`00`、`醒脑`（昵称「YGZ醒脑片」碎片）切成词 | `jieba_segment.py:31-40` | 实测 `醒脑` 命中 25/432、`QQ` 19/432、`2026` 4/432 → 纯噪声入场 |
| **F4** | `RELEVANCE_THRESHOLD=0.15` 低于单项权重上限（topic 单独命中=0.2，joint=0.1+text） | `:40,335-342` | 「话题相同」就能单独通过闸门 |
| **F5** | relevance 上限只有 0.45，先验合计 0.55 → 无关但新、且被标记高 important 的记忆可以挤掉相关但旧的记忆 | `:30-31` | 排序与查询脱钩 |
| **F6** | `summary_relevance_guarantee=8` 实际是 `max(limit,8)`，limit=30 时完全失效；`_select` 又会过滤掉不达标项，所以「保底」不可能实现 | `:416,394-407` | 配置语义与实现不符 |
| **F7** | `joint` 字段键漂移：425/478 条参与人条目的是 `id` 键，而 `joint_util.resolve()` 只读 `meowid` | `joint_util.py:34-52`；数据实测 | 对 89% 老记录，`joint` 信号（0.1）恒为 0；`_joint_similarity` 传 `(uid, uid)` 也永不匹配 |
| **F8** | tags 与 topic 冗余、只看 `tags[:3]`、分母是 tag 词数 | `:258-272` | 信号弱且随 query 变长而衰减 |
| **F9** | strength/accuracy 无区分度（47% strength=0，91% accuracy=5） | `:352-357` | 30% 的权重预算被浪费 |
| **F10** | 提示词注入 48% 是元数据；30 条 3214 字符 ≈ 2400 token | §2.6 实测 | 每轮固定开销；信噪比低 |
| **F11** | `max_events` 配置（10）是死配置，生效值硬编码 6 | `summary_tool.py:14` vs `config.py:47` | 调参无效 |
| **F12** | `decide_recall` 无缓存/无超时/无熔断，在热路径同步阻塞 | `load_abmem.py:209-242` | 违反速度优先 |

---

## 3. BaiShou-Next 记忆图谱解剖

### 3.1 两套互不合并的库（理解全部代码的前提）

| 库 | 载体 | 写入者 | 用途 |
|---|---|---|---|
| **全局 AI 记忆** | `memory_embeddings`（向量分块）+ `graph_nodes`/`graph_edges`/`graph_node_aliases`（关系图） | 伙伴主动 `memory_store`；日记抽图 | 伙伴「记得你」 |
| **笔记本记忆** | `knowledge_chunks`(+`_fts`) + `notebook_graph_*` | 只由资料抽取写入 | 查资料 |

文档明确写了「不合并两套图」「不拿资料分块向量当节点向量」（`core/src/graph/docs/unified-organize-plan.md` §5）。这不是疏忽，是刻意的产品边界：**资料里的人不进「人生关系图」**。

### 3.2 数据模型

**节点**（`database/src/schema/graph.ts:47-86`）：`id`（**内容派生的确定性 ID**）、`vault_id`、`node_type`、`name`、`name_normalized`、`discriminator`、`aliases`(JSON)、`summary`、`props_json`、`embedding`/`dimension`/`model_id`、`mention_count`、`first_seen_at`/`last_seen_at`、`origin`(ai/user)、`shard_month`、`review_status`(approved/pending/rejected，默认 approved)、`deleted_at`。

- **节点类型 11 个**：`person / place / organization / event / emotion / topic / work / activity / product / food` + 结构锚点 `entry`（`:17-32`；`graph-view.constants.ts` 的配色表可交叉确认）。
- **边类型仅 6 个**：`mentions / participates_in / located_at / evokes / role_of / relates_to`（`:36-43`）。这是「带类型的边」，与 Meowlisis 的自由文本 tag 是两种东西。
- **边的时间有效性**：`valid_from / valid_to / is_current`（`:103-133`）。事实变化时旧边置 `is_current=false` 而**不删除**——这是它替代「衰减」的核心手法。
- **`mention_count`**：该节点作为端点的 `current` 且未删除边数，抽图后重算回写（`graph.repository.mutate.ts:504-549`）。它是**结构性重要度**，但**不参与任何加权打分**。

**确定性 ID 的代价**：`md5(vaultId \0 nodeType \0 normalizeGraphName(name))` ⇒ **同名必然同节点**，「同名不同人」在机械上存不下，必须靠用户手工拆分写 `discriminator`（`unified-organize-plan.md` §1.4、§3）。这是有意为之：它换来跨设备免协商去重。

### 3.3 写路径（三个触发点，全部离线/异步）

1. **`memory_store` 工具**（LLM 自主调用）：先 JSONL 落盘 → 再 `embed`(sourceType=memory) → `commitIndexed`（`ai/src/tools/memory-store.tool.ts:136-167`）。去重是**三级阈值 + LLM 裁决**：`>0.92` 跳过 / `0.70–0.92` 调对话模型判 `skip|merge|new`（merge 时删旧记忆）/ `<0.70` 直接存；任何异常 fallback 成 `stored`（不丢记忆）（`ai/src/rag/memory-deduplication.service.ts:28-32,74-80`）。
2. **日记 → 抽图**（主力）：**每篇日记一次 LLM 调用**，正文硬截 12000 字符，`temperature=0.1`，只输出严格 JSON `{entities, edges}`，枚举越界 clamp 到 `topic`/`relates_to`（`core/src/graph/graph-llm-extraction.prompt.ts:186-206`）。**顺序门槛是硬的**：原文向量未完成不许抽图（`GRAPH_EXTRACT_DIARY_NOT_EMBEDDED`）。批次攒 30 篇落盘一次，LLM 并发默认 10/上限 20。
3. **`graph_upsert` 工具**（LLM 自主写关系，需 Gate 确认）：同名同类型更新该节点、**永不自动合并两个已有节点**、边改删必须带 edge id、端点歧义则跳过。

**成本画像**：估算 600 token/篇（floor）×1.25，2–4 秒/篇（`graph-llm-extraction.prompt.ts:20-26,45-52`）。抽 100 篇日记 ≈ 75k token、3–7 分钟。**这是一笔明确的离线批处理成本，不进入对话延迟。**

### 3.4 实体对齐（质量的核心闸门）

`alignEntityPool`（`core/src/graph/graph-entity-align.ts:118-266`）顺序：
1. 批内按 `entityAlignKey(nodeType, name)` 去重、并别名；
2. **名字/别名等值命中 → 直接复用**（`mergedBy:'name'`，零成本）；
3. 同名多候选 → 可选 `judgeNameCandidates`，**只允许从候选 id 里挑**，挑不出就挂裸名 + `reviewStatus=pending`；
4. 名字零命中才走向量召回 `topK=5`，**只保留相似度 > 0.7** 的候选（文档写 0.5，代码是 0.7 且严格大于 —— **文档与代码不一致**）；
5. 二次 LLM 判定 `merge / new`；**模型失败或未配置 → 全部新建，绝不因向量近而硬合并**（`:113-117`）。

一条产品硬约束被写进了文档：「**是否合并始终由二次模型判定，不因向量近就硬合并**」。

**质量闸门**：`confidence < 70` 的实体/边一律 `reviewStatus='pending'`，**pending 永不到达 Agent**（`graph-rag.service.ts:250-252`）。实体 confidence 默认 80、边默认 75。

### 3.5 整理 / 合并 / 遗忘（这里与 Meowlisis 完全相反）

| 动作 | 实现 | 触发 |
|---|---|---|
| 软删除 | `deleted_at` | 用户 / 工具 |
| 事实变更 | 旧边 `is_current=false` + `valid_to=now`，**保留可查** | 重抽同一篇日记时 supersede（仅当本批至少写入 1 条边才允许） |
| 待复核 | `review_status = pending` | confidence<70、多候选、可疑扫描 |
| 合并 | `mergeDiaryGraphNodes`：别名并集、`mentionCount` 相加、边全部改挂后删 loser | **用户手动** |
| 拆分 | `graph-split-node.ts` + `discriminator` | **用户手动** |
| 可疑扫描 | 互斥关系类型、出处跨 18 个月、出处数≥3 等信号 → 最多 40 次 LLM 调用写「怀疑理由」 | 整理流水线，**只标记不自动拆分** |
| 相似待合并 | 模型吃不准时新建 + `props.similarPending`（阈值 0.7） | 抽图时 |

**全仓没有任何时间衰减或遗忘曲线**（`decay|forget|衰减|遗忘` 只命中画布力导向动画参数与测试）。陈年记忆与新记忆在检索中同权。

> 这不是缺陷，是产品立场。白守把自己定义为「外部海马体 / 个人史」：README 的设计哲学一节写着「**拥抱冗余**…如果你在日记里写了十次『我爱你』，RAG 可能会去重，但白守会把它们都留下来，因为重复的频率本身就是羁绊的厚度」。**衰减与「保留冗余」在目标上是互斥的。**

### 3.6 召回路径（两个通道，全部由 LLM 主动调用）

**关键前提：没有任何「每轮自动注入」。** 两条通道都是 agent tool。比「靠模型自觉」更值得注意的是**两条通道的强制力度不同**：

- 系统级规范（注入 system prompt）只点名了 `diary_search` / `vector_search` / `session_list` / `message_search`，原文是：
  > 「涉及具体人名、地点、事件、日期或用户过往经历时，若当前对话上下文（含压缩摘要）中没有明确依据，**不得猜测、推断或编造**。」
  > 「**必须**先调用 diary_search… 和/或 vector_search… 查阅，再回答。」
  （`packages/ai/src/agent/tool-usage-guidelines.util.ts:35-49`，**我独立复核**）
- **`recall_relations`（记忆图谱）不在这份强制清单里**。它只能靠自己的工具描述去争取被调用（描述里写了「当用户像提起熟人一样提到某人/某地、问两件事怎么相关、或在写入前确认谁已在图里时调用」）。

也就是说：**白守的「关系图谱」其实是它所有记忆入口里唯一没有系统级调用保障的那一个**。这与 §5.3-B1' 叠加，构成图谱召回的第二重衰减：先可能不被调用，被调用了也可能因名字短路走错锚点。

以下两个通道的算法本身都是纯算法的——不含 LLM rerank、不含 query rewrite、不含 HyDE。

#### 通道 A：`vector_search`（向量分块 / 混合）

参数：`mode`（默认 hybrid）、`start_date`/`end_date`、`min_score`（默认 **0.4**）；topK 取用户配置 `rag_top_k`（clamp 1–200，默认 **20**）。

```
1. embedQuery(query)                        # API embedding 模型，切片 2048 token / overlap 128
2. searchSimilar → 三级降级：vec_distance_cosine → vector_top_k → JS 全表余弦
   score = 1.0 - distance
3. 阈值只筛向量候选（注释明写：关键词 RRF 分数量级太小，不能被同一阈值洗掉）
4. "FTS" 分支：LIKE 分词（≤8 词，按空白/标点切）+ 命中计数排序，score = limit - i
5. RRF 融合
```

RRF 实现（`ai/src/rag/hybrid-search.ts`）：

```js
RRF_K = 60
ftsScore    = 0.3 / (i + 60)          // :42
vectorScore = cosine × 0.7            // :75
total       = ftsScore + vectorScore  // :81-86
// 对外报告的 score 却是「原始余弦」而非总分 :103
```

**两个可验证的结构性缺陷**：
1. **量纲不对称**：FTS 分支上限是 `0.3/60 = 0.005`，向量分支是 `0.7 × cosine`（≥0.4 才留，即 ≥0.28）。**纯关键词命中（0.005）永远排在所有向量命中之后**，FTS 只在两路都命中时充当微小的 tie-breaker。
2. **关键词通道对中文退化**：`tokenizeKeyword()` 只按空白与标点切词（`/[\s,，、;；|/\\。.!！?？:：]+/u`，≤8 个），**没有任何中文分词**。因此「主人昨天说想买显卡」会退化成 `chunk_text LIKE '%主人昨天说想买显卡%'`——必须原文连续出现才命中。**对中文而言，这条「混合检索」实际上是纯向量检索。**

#### 通道 B：`recall_relations`（GraphRAG）

参数：`entity` / `mode ∈ {search, neighbors, network, timeline}`（默认 network）/ `depth ∈ {1,2,3}`（neighbors 默认 1，network 默认 3）/ `limit`（1–20，默认 **12**）。

**锚点解析**（`graph-rag.service.ts:280-319`）——**这是全链路最脆弱的一步**：

```js
for (part of parts) { byName = searchNodesByName(part, limit=8) }   // name LIKE '%q%' 或 name_normalized 等值，按 mention_count 排序
if (seen.size > 0) return rankAnchorsByExact(...)                   // ← 有名字命中就立刻返回
if (resolveQueryVector) { hits = searchNodesByVector(vector, 5) }   // ← 只有零命中才走向量，且无相似度阈值
return []
```

即 **「名字有命中即短路」**：只要名字 LIKE 命中了任何一条（哪怕命中的是错的长尾节点），向量通道就完全不启动。用户的说法与节点名不一致（「我妈」vs 存的是「妈妈」；「那个游戏」vs「异环」）时，只要 `LIKE '%我妈%'` 意外命中某个记载了「我妈」两字的边缘节点，就会被当成锚点，然后沿错误锚点展开 3 跳。

**遍历成本控制**（`graph.repository.traverse.ts`）：
- 逐跳 SQL BFS，hops clamp 1–3；
- `GRAPH_MAX_NEIGHBORS_PER_HOP = 40`（**已核验**），超限时按**查询向量距离**在 SQL 内裁剪，不足用 `mention_count` 补；
- 最短路径 BFS 带**枢纽剪枝** `hubDegreeThreshold = 40`（度数超阈值的中间节点不展开）；
- `network` 深度写死 2–3 跳，主锚点比对其余最多 4 个锚点，**最多 6 条路径**；
- `neighbors` 截到 `limit+1` 且保留中心；`timeline` 默认 80 条边，含已失效边。

**图谱侧没有任何打分**：`GraphRagResult` 只有 `anchors/subgraph/nodes/paths`，**没有 score 字段**。排序只来自三处：`mention_count`、BFS 层序（跳数少的优先）、40 上限处的向量距离。

### 3.7 注入格式

- `vector_search` 输出纯文本，**带完整流水线自述**（每步的命中数与过滤后数量，如 `✂️ 向量相似度过滤 (≥0.40): 18 → 7 条`），每条含 `类型 / memory_id / 时间 / 内容 / 相似度`。
- `recall_relations` 输出 markdown：`## 锚点`(≤8) + `## 关系路径（最短，≤3 跳）`(≤12)，每条边渲染成 `from —edgeType→ to id=… [来源:…] [validFrom:YYYY-MM-DD] 「摘要(≤80字)」`，失效边标「（已失效）」。
- **没有显式 token 预算**：唯一规模控制是 `topK≤200（默认 20）` × 单切片 ≤2048 token。一次 `vector_search` 最多可能塞 20 × 2048 token 的原文。

### 3.8 已定位的缺陷

| 编号 | 缺陷 | 位置 | 影响 |
|---|---|---|---|
| **B1** | 锚点「名字有命中即短路」，向量仅在零命中时兜底，且兜底无阈值 | `graph-rag.service.ts:302-313` | 名字一变即召回失败；错命中会放大成整条错链 |
| **B2** | 「FTS」实为 LIKE 整句子串，无中文分词、无 IDF、无长度归一 | `hybrid-search.repository.vector-search.ts:18-25` | 中文混合检索实际是纯向量 |
| **B3** | RRF 量纲不对称（0.3/60 vs 0.7·cos） | `ai/src/rag/hybrid-search.ts:42,75` | 关键词通道近乎无效 |
| **B4** | 图谱召回完全没有打分/排序函数 | `graph-rag.service.ts:16-23` | 无法做可解释的 top-k |
| **B5** | 热门节点无降权（只有「度数>40 不展开」的硬剪枝） | 文档自述 `unified-organize-plan.md:231` | 高频实体淹没结果 |
| **B6** | 同名必然同节点（ID 是名字哈希 + 部分唯一索引） | `schema/graph.ts:74-85` | 同名不同人必须人工拆分 |
| **B7** | 无时间衰减；`mention_count` 不参与打分 | 全仓 grep | 陈年与新近同权 |
| **B8** | 无 token 预算；`topK` 最大 200 | `vector-search.constants.ts:2-4` | 上下文可能被单次召回打爆 |
| **B9** | 文档/代码阈值不一致（0.5 vs 0.7） | `unified-organize-plan.md:70` vs `graph-similar-pending.util.ts:6` | 维护者认知漂移 |
| **B10** | 无 `vec0` ANN，向量检索是 `ORDER BY vec_distance_cosine(...) LIMIT n` 全表扫描 | `hybrid-search.repository.vector-search.ts:189-199` | O(N)，大库变慢 |

---

## 4. 对比矩阵

### 4.1 架构定位

| 维度 | Meowlisis 摘要记忆 | BaiShou-Next 记忆图谱 |
|---|---|---|
| 记忆单元 | 一条「事件概括」（~38 字）+ tags/topics/joint/evidence | 节点（实体）+ 带类型的边 + 向量分块（原文切片） |
| 语义关系 | 隐式（tag/topic 集合相交） | **显式**（6 种 typed edge，带 `valid_from`、`sourceExcerpt`） |
| 时间建模 | 只有一个 `time` 字段 + 衰减公式 | `valid_from/valid_to/is_current` 的事实有效期 + `entry` 锚点 |
| 召回触发 | **自动**，每轮提示词构建时无条件执行 | **显式**，LLM 决定是否调用工具 |
| 召回执行 | 纯算法（jieba + 子串 + 加权和） | 纯算法（嵌入 + LIKE + RRF + BFS） |
| 是否有在线 LLM | **有，2 次同步往返** | 无（决策由主对话模型在同一轮里顺带做出） |
| 写入成本 | 每 50 行触发：≤80 轮工具循环 + 1 次审查 LLM（异步） | 每篇日记 1 次抽图 LLM（离线批处理）+ 对齐二次判定 |

### 4.2 召回算法对照

| | Meowlisis | BaiShou 通道 A（向量） | BaiShou 通道 B（图谱） |
|---|---|---|---|
| 候选生成 | 全量扫（O(N)），无索引 | `vec_distance_cosine` 全表扫描（O(N)） | 名字 LIKE + 别名表，按 `mention_count` 取 8 |
| 关键词信号 | 单向子串包含，**单词即满分** | LIKE 整句（中文等于无效） | 无 |
| 语义信号 | 无 | cosine（API embedding） | 向量 top-5，**仅名字零命中时启用**，无阈值 |
| 结构信号 | topic/tags 集合相交（写时）；读时加权 | 无 | 图游走（2–3 跳，每跳≤40，枢纽>40 不展开） |
| 打分 | `0.20s+0.10a+0.45r+0.15t+0.10i` | RRF `0.3/(i+60) + 0.7·cos` | **无打分** |
| 硬闸门 | `relevance ≥ 0.15`（实测易被满足） | `cos ≥ 0.4`（只筛向量） | `approved` only + `confidence≥70` |
| 返回规模 | `min(30, 通过闸门数)`，实测中位 17 | topK 默认 20（上限 200） | limit 默认 12（上限 20） |
| 去重/多样性 | 按 event 文本精确去重 | 无 | 无 |
| 决定权 | 代码写死 | 模型选工具与 query | 模型选 entity 与 mode |

### 4.3 成本与延迟

| | Meowlisis | BaiShou |
|---|---|---|
| 每轮对话额外延迟 | **+1 次 LLM 往返**（群聊阈值触发路径 +2：`decide` 与 `reply` 各自构建一次 prompt，而 `decide_recall` 无缓存） | 0（若模型不调工具）/ +1 次工具往返（若调） |
| 每轮固定 token 开销 | ~2400 token（30 条 × 104 字符） | 0（不自动注入） |
| 写路径成本 | 每 50 行消息：多轮工具调用 + 审查 | 每篇日记：1 次抽图 + 少量对齐判定 |
| 索引 | **无** | 图索引 + 向量列（无 ANN，靠函数扫描） |
| 依赖 | jieba（纯本地） | embedding API（网络）+ sqlite-vec/libsql |

### 4.4 质量保障

| | Meowlisis | BaiShou |
|---|---|---|
| 写入去重 | 稳定主键（文本+参与人 hash），实测 0 组重复 | 三级阈值 + LLM 裁决 + 可回滚 tombstone |
| 人工闸门 | 无（仅异步审查 LLM） | `pending` 复核队列、同名拆分、相似待合并页、可疑扫描 |
| 可解释性 | 可（每项权重固定） | 高（返回边 + 出处 + 有效期） |
| 冲突处理 | `disputation` + 归档 | 旧边 `is_current=false`（**保留历史**） |
| 遗忘 | 有（半衰期 + 归档） | **无**（刻意保留冗余） |

---

## 5. 「记录多了就不准」的根因分解

### 5.1 共性问题（两者都中）

**P1　候选集随 N 线性增长，精排判别力不随 N 增长。**
两边的召回都是「全量扫 + 一个固定公式 + 取 top-k」。当 N 从 400 涨到 4000，候选集从 22 涨到 220，而 top-k（30 / 20 / 12）不变。于是**进入 top-k 的比例从 100% 掉到 14%**，排名函数的任何偏差都被放大 k 倍。这是信息检索里最经典的失效模式，两边都没有做「候选集规模归一化」（如按 N 调整阈值、或按分位数取 top-p 而非 top-k）。

**P2　都有一条「结构上失效的第二通道」，导致退化为单信号。**
- Meowlisis：`tags`(0.2) + `topic`(0.2) + `joint`(0.1) 合计 0.5 的预算，实测几乎不提供区分度——topic 只有 5 个取值且「日常」一条就覆盖 248/432 = **57.4%** 的记录、tags 72% 单例且与 topic 冗余、joint 89% 条目键漂移。**实际只剩「子串命中」一个信号，且已饱和。**
- BaiShou：RRF 的 FTS 分支上限 0.005，且对中文退化为整句 LIKE。**实际只剩 cosine 一个信号。**

两者都以为自己是「多信号融合」，实测都是「单信号 + 一堆常数」。

**P3　都没有「负证据」与「查询-记忆不相关的显式表达」。**
Meowlisis 的 `disputation` 只在写入时由 LLM 判定，实测 254 条里只有 3 条非零；BaiShou 完全没有。于是「召回错了」这件事在系统里**没有留下任何可学习的痕迹**——精度问题无法自我修正。

### 5.2 Meowlisis 特有

**M1　相关性是布尔值（F1）**：一个词命中 = 满分。这使「相关性」与「查询复杂度」无关，导致闸门恒被满足（实测中位 17 条通过，且全部 `text_similarity==1.0`）。闸门一失效，排序就由 `recency(0.15) + importance(0.10) + strength(0.20)` 决定，而这三者对「是否该被召回」毫无信息量。**这正是用户观察到的「大量记录时调用不精准」的直接机制。**

**M2　先验权重 > 相关性权重（F5）**：`relevance` 上限 0.45 < 先验合计 0.55。即使相关性判对，一条「相关但旧、且 importance 低」的记忆也会输给「无关但新、且 importance 高」的记忆。

**M3　元数据挤占预算（F10）**：48% 的注入字符是 `[话题｜标签｜参与｜时间]`。在固定 30 条预算下，等于把一半上下文留给模型基本不用的字段。

### 5.3 BaiShou 特有

**B1'　入口短路（B1）**：名字一次 LIKE 命中就永久关闭向量通道。随图谱变大，任意短名字（2 字）的 LIKE 命中率单调上升 → **短路概率上升 → 走错锚点的概率上升**，而一旦锚点错，2–3 跳展开全错，且没有任何分数能让模型看出「这次结果不可信」。〔推断，机制由代码确定；具体劣化速率需真实数据验证〕

**B1''　调用本身没有系统级保障**：`recall_relations` 不在 system prompt 的「必须先调用」清单里（只有 diary_search / vector_search / session_list / message_search 在）。所以图谱召回的失效是**两段串联的**：先可能不被调用（依赖模型读工具描述），被调用了还可能被名字短路。两段概率相乘，这解释了为什么用户会觉得「图谱明明建了却没用上」。〔推断，机制确定〕

**B2'　结构重要度 ≠ 查询相关度（B5）**：`mention_count` 同时用于名字搜索排序和邻居裁剪补齐。热门实体在每个查询里都排前面，`limit=12` 极易被「主人/喵呜/日常」这类枢纽吃满。〔推断，机制确定〕

**B3'　决定权交给模型，但模型没有「我该查什么」的索引视图**：模型的 query 是一句自然语言，系统只能拿它做 `LIKE '%q%'` 或 embedding。**中间缺一层「在线实体归一」**——用户说「我妈」，图里存「妈妈」，别名表能救一部分（但别名同样由抽图产生，不会自动把口语称谓映射到存档称谓），而 embedding 兜底**只在名字零命中时**才启用。所以「口语 → 存档名」这条最常见的鸿沟，恰好落在这套机制的两个空档之间。

### 5.4 一句话总结

> 两者都在用「一次线性扫描 + 一个加权公式」代替「索引 + 结构化匹配」。随着 N 增长，公式里的常数项（先验/结构性重要度）逐渐主导排序，而它们与查询无关。**精度损失的本质是「先验吃掉了似然」。**

---

## 6. 适用场景判定

| 场景特征 | 更适合 | 理由 |
|---|---|---|
| 实时对话陪伴、每秒都要回、不能加延迟 | **Meowlisis 的形态**（但要修掉同步 LLM） | 白守的工具调用需要额外一轮往返；且模型可能不调用 |
| 记录以「事件/偏好」为主，条数几千级 | Meowlisis | 单条 38 字的概括，注入成本低；无 embedding 依赖 |
| 记录以「人/关系/地点」为主，用户会问「A 和 B 什么关系」 | **白守** | typed edge + 最短路径是唯一能答这类问题的结构；Meowlisis 无法表达关系 |
| 需要回答「去年这个时候」这类时间问题 | **白守**（`valid_from` + `timeline` + `entry` 锚点） | Meowlisis 只有单点 `time` + 衰减，历史会被衰减吃掉 |
| 事实会变（换工作、搬家、分手） | **白守**（旧边失效但保留） | Meowlisis 只能靠 `disputation` 削弱，会丢失「曾经如此」 |
| 强调「不要遗忘、要保留冗余」的个人史 | **白守** | 显式设计立场，README 有明确论述 |
| 强调「忘掉不重要的、别被旧事干扰」 | **Meowlisis** | 有半衰期 + 归档，这是白守明确不做的 |
| 完全离线、无 embedding 服务 | Meowlisis | 白守的 `memory_store`/`vector_search` 在无嵌入时被注册表禁用 |
| 数据量 10 万条以上 | **两者都不够** | 见 P1；都需要倒排索引 + ANN |

**判定树（简版）**

```
要回答「关系/随时间演变的事实」吗？
├─ 是 → 需要显式边 + 时间有效性 → 图谱形态（白守思路）
└─ 否 → 要「快、且不能有额外 AI 决策」吗？
      ├─ 是 → 摘要 + 索引化召回（Meowlisis 形态，需修闸门）
      └─ 否 → 允许 agent 自己查 → 工具化召回（白守形态）
```

---

## 7. 方案设计（**不实施**，仅供决策）

### 7.1 硬约束

1. **提示词构建路径上不允许出现网络调用。** 当前 `decide_recall` 必须移出热路径（这是唯一无争议的改动方向）。
2. **不引入「AI 思考决策」**：不允许「先让 LLM 决定查什么再查」的模式（即排除白守的在线 agent 召回）。
3. **精度可量化**：必须有 gold set 与可复现的 precision@k / recall@k，否则无法验证改善。
4. 现有 `evidence` 衰减、写路径工具循环、`pending` 式的概念都保留，只改**召回层**。

### 7.2 三条路线

| 路线 | 内容 | 延迟 | 精度预期 | 工程量 |
|---|---|---|---|---|
| **A 最小修复** | 只改参数与公式：`OVERLAP_SATURATION` 改为按 query 词数归一 + 加 IDF；`RELEVANCE_THRESHOLD` 提到 0.35；先验权重压到 ≤0.30；剔除数字/昵称 token；修 `joint` 键漂移；`decide_recall` 改成正则/关键词触发 | **≈0** | 中（闸门有效，但仍是 O(N) 线性扫） | 小（~5 个文件） |
| **B 索引化召回** | 离线维护倒排索引 + 实体倒排 + 时间桶；在线纯 CPU 查表 + 对称 RRF + 硬闸门 + 分级预算 | **+3～8 ms** | 高 | 中（新增索引模块 + 写路径挂钩） |
| **C 借白守图** | 离线抽「实体/关系」（复用现有 joint + tags 即可起步），在线只做**查表**，不做 agent 决策 | +3～10 ms | 高（能答关系类问题） | 大（抽取成本 + 对齐 + 人工闸门） |

**推荐：A 立即做（修正确性），B 作为主体（解决增长性），C 只借「结构」不借「在线决策」，在有真实关系类需求时再上。**

### 7.3 推荐方案（A+B）的分层设计

```
【离线 / 写路径已有异步线程，只挂增量钩子】——不增加在线延迟
  L0-1 倒排索引    token → [(doc_id, tf, field)]        字段：event(权重高) / tags / joint
  L0-2 实体倒排    {meowid, nickname, alias} → [doc_id]
  L0-3 时间桶      YYMM → [doc_id]
  L0-4 标签清洗    tag 与 topics 枚举同名者降权为 0；单例 tag 不进索引主表
  L0-5 IDF 表      每个 token 的 df，写时累加即可（O(1)）

【在线 / 提示词构建】——纯 CPU，禁止网络调用
  步骤 1  查询分析（确定性的、无模型）
      jieba 切词 → 去停用词 → 丢弃纯数字 / 长度<2 / 命中昵称表的碎片
      → 若命中时间正则（今天/昨天/上周/去年/YY-MM），产出时间窗
      → 若命中人物别名表，产出 entity_id
  步骤 2  三路取候选（并集，每路各取 top-M，M≈20）
      a) 倒排：BM25 = Σ idf(t) · tf·(k1+1)/(tf + k1·(1-b+b·|d|/avgdl))
      b) 实体：entity_id 精确 → 全部 doc_id
      c) 时间：时间窗内 doc_id
  步骤 3  对称 RRF 融合（修掉白守的 B3）
      score(d) = Σ_over_lists  w_list / (rank_list(d) + 60)      ← 三条列表用同一量纲
  步骤 4  硬闸门（不再用「任一 token 即过」）
      必须满足其一：BM25 ≥ 该 token 组的自适应阈值  |  实体精确命中  |  时间窗命中
      → 参考做法：阈值取「本次候选 BM25 的 P75」而非固定常数（自动随 N 缩放，解决 P1）
  步骤 5  分级预算
      核心 ≤3 条（实体/时间精确命中）+ 补充 ≤5 条（BM25 头部）
      → 硬上限 8 条，取代当前 limit=30
  步骤 6  注入瘦身
      元数据从 48% 压到 ≤25%：只保留 `[时间｜参与]`，topic/tags 移到行尾或省略
      目标：8 条 × ≤90 字符 ≈ 720 字符（当前 3214 字符，降 78%）

【离线 / 可选的「结构」借力（C 的轻量版）】
  用现有 joint(参与人) + tags 构建「共现图」，只用于**扩展候选**（1 跳），不做在线决策：
    entity 命中的 doc → 取与其共享 ≥2 个 tag 的 doc 作为二跳候选（上限 5 条）
  成本：写时 O(1) 增量；在线 1 次哈希查表
```

### 7.4 这套设计如何逐一拆掉 §5 的根因

| 根因 | 对策 |
|---|---|
| P1 候选线性增长 / 精排失效 | 自适应阈值（候选集 P75）+ 三路并集后再取 top-k；候选规模与 N 解耦 |
| P2 第二通道失效 | 三路**对称 RRF**（同一量纲）；BM25 带 IDF，稀有词自动高权；实体路精确命中直接给核心位 |
| P3 无负反馈 | 记录「注入了哪些、下一轮模型是否引用」到日志，作为离线评估集（不改在线行为） |
| M1 相关性是布尔值 | BM25 取代子串命中：分数随命中数与词权重连续变化 |
| M2 先验 > 相关性 | 先验只用于**平局打破**（tie-break），不进入主排序；主排序 = RRF 分 |
| M3 元数据挤预算 | 注入瘦身到 ≤25% |
| B1' 入口短路 | 三路并行取候选，实体/关键词/时间互不短路 |
| B3' 缺实体归一 | 别名表（现有 `joint` + `id_signup` 昵称表已经是现成的） |

### 7.5 可量化验收指标

| 指标 | 当前（实测） | 目标 |
|---|---|---|
| 提示词构建额外 LLM 往返 | 1（群聊阈值路径 2） | **0** |
| 注入条数 = `min(30, 通过闸门数)` | 上限 30；实测中位 ≈17、均值 22.3 | ≤8 |
| 注入字符数（满 30 条时） | 3214 字符 ≈ 2400 token | ≤900 |
| 通过闸门的条数（语料 432） | 中位 17 / 均值 22.3 / max 54 | ≤8 |
| 其中 relevance 已饱和（`text_sim==1.0`）的比例 | **100%**（与通过数完全相同） | 不应饱和 |
| precision@5（人工标 50 条 query） | 未测（**必须先建 gold set**） | ≥0.7 |
| recall@8 | 未测 | ≥0.8 |
| 构建耗时（不含主模型） | 未测；结构上含 1 次 LLM 往返 | <15 ms，0 次网络调用 |

### 7.6 风险

1. **BM25 需要索引一致性**：当前 `save()` 是整月重写（`load_abmem.py:120-147`），索引必须挂在同一把锁上，否则会读到半更新状态。
2. **IDF 需要全量 df**：增量维护 df 表即可，但首次需全量构建（432 条毫秒级，10 万条秒级）。
3. **注入条数从 30 降到 8 会改变模型行为**：这是**最大的行为风险**。必须用 shadow 模式（先记录新旧两套的召回结果，不切换），用真实对话验证「记忆使用率」不下降。
4. **不要同时动写路径**：写路径（工具循环、审查、去重）实测质量良好（0 组重复），改动它只会引入新变量。

---

## 8. 附录

### 8.1 Meowlisis 事实清单（带行号）

- 相关性满分阈值 `OVERLAP_SATURATION = 1.0` — `func/catbrain/AbstractMem/load_abmem.py:26`
- 相关性权重 `{text:0.5, tags:0.2, topic:0.2, joint:0.1}` — `:28`
- 排序权重 `{strength:0.20, accuracy:0.10, relevance:0.45, recency:0.15, importance:0.10}` — `:30-31`
- 注入闸门 `RELEVANCE_THRESHOLD = 0.15` — `:40`
- 子串包含打分 `hits = sum(1 for w in words if w in event)`；`min(1.0, hits/1.0)` — `:322-333`
- tag 相似度只看 `tags[:3]`，分母为 tag 分词数 — `:258-272`
- joint 相似度 `match(item, uid_of(uid), uid)` — `:274-278`；键漂移在 `joint_util.py:34-52`
- 综合分与负分剔除 — `:344-370`
- 选取：沿总分降序、过滤 relevance<0.15、按 event 文本去重 — `:394-407`
- `limit = max(limit, summary_relevance_guarantee)` — `:416`
- 提示词行格式 `- [话题:… | 标签:… | 参与:… | 时间:…] event` — `:421-433`
- `decide_recall` 同步 LLM + `force_tool_call`（3 次重试）— `:209-242`，`port/__init__.py:5-20`
- `_current_topic` 缓存 `topic_update_interval`（60s），背后是 1 次 LLM — `:149-207`
- `load()` 每次全量读全部 `meow-*.json`，无缓存 — `:80-109`
- 提示词构建入口两次调用 `_decide_recall` — `func/catbrain/prompt_builder.py:89,117`
- 群聊阈值路径会建两次 prompt（decide + reply）— `func/toolbox/napcat/llm/napcat_group_llm.py:192,219`
- 证据衰减：强化 30 天 / 质疑 180 天半衰期 — `process/evidence.py:40-58`
- 归档：净分 ≤ -2 且负分累计 ≥14 天 — `:64-71`，`process/archive.py:24-50`
- 写时范围召回：topics 相交且 tags 相交 — `record/update_abmem.py:210-227`
- 工具循环上限 80 轮、grep ≤10 次、范围回传上限 80 条 — `:268,267,250-252`
- `MAX_EVENTS = 6`（`config.max_events: 10` 为死配置）— `record/summary_tool.py:14` vs `func/catbrain/config.py:47`
- 写触发：`record.txt` 行数达 `summary_rounds`(50) → 后台线程 — `record/get_memory.py:40-56`
- 线上配置真值 — `config.yml:34-70`（`summary_top_limit: 30`、`rank_recency_half_life_days: 14`、`rank_evidence_saturation: 5`、`llm_type: deepseek` / `deepseek-flash`）
- 实测语料：432 条 / 3 文件 / 275 唯一 tag / 72.4% 单例 / tags.json 词表 69 / 覆盖 78.9% / accuracy=5 占 91.0% / reinforcement=0 占 47.0% / 近似重复 0 对 / wrong_mem 25 条 / joint 键 `id` 425 条 vs `meowid` 53 条

### 8.2 BaiShou-Next 事实清单（`main@645f43a`）

- 节点 11 类（10 实体 + `entry` 锚点），边 6 类 — `packages/database/src/schema/graph.ts:17-45`
- 节点 ID = `md5(vaultId \0 nodeType \0 normalizeGraphName(name))`，确定性 — `packages/shared/src/utils/graph-identity.util.ts:152-166`
- 节点 embedding 语料固定 `${name}\n${summary}` — 同上 `:172-214`
- `confidence < 70` → `review_status='pending'`，pending 永不到达 Agent — `graph-extract-confidence.util.ts:3,17-19`；`graph-rag.service.ts:250-252`
- 抽图 prompt：正文硬截 12000 字符、`temperature=0.1`、严格 JSON — `packages/core/src/graph/graph-llm-extraction.prompt.ts:186-206`
- 抽图攒 30 篇落盘、LLM 并发 10/20 — `graph-extract-batch.util.ts:8-13`
- 实体对齐：名字等值先复用 → 零命中才向量 topK=5、阈值 **>0.7** → 二次 LLM 判 merge/new → 模型失败全新建 — `graph-entity-align.ts:118-266,292-305,113-117`
- `memory_store` 去重三级 0.92 / 0.70 / TOP_K=5，Tier2 交给对话模型 — `packages/ai/src/rag/memory-deduplication.service.ts:28-32`
- `vector_search` 默认 topK=20、min_score=0.4；topK clamp 1–200 — `vector-search.constants.ts:2-4`
- RRF：`RRF_K=60`、`ftsWeight=0.3`、`vectorWeight=0.7`，`ftsScore=0.3/(i+60)`、`vectorScore=cos×0.7` — `packages/ai/src/rag/hybrid-search.ts:7,42,75`
- 阈值只筛向量候选 — `packages/ai/src/tools/vector-search.tool.ts:141-148`
- 「FTS」实为 LIKE 分词（≤8 词，按空白/标点切，**无中文分词**），`score = limit - i` — `packages/database/src/repositories/hybrid-search.repository.vector-search.ts:18-25,104-115`（**我独立复核**）
- 向量检索三级降级 `vec_distance_cosine → vector_top_k → JS 全表余弦` — 同上 `:146-180`
- `recall_relations` 默认 `network`、limit 默认 12（1–20） — `packages/ai/src/tools/recall-relations.tool.ts:30-36,118`
- 锚点：名字 LIKE/等值（limit 8，按 `mention_count` 排序）→ **有命中即短路** → 零命中才向量 topK=5 且无阈值 — `packages/core/src/graph/graph-rag.service.ts:280-319,302`
- **系统级「必须先调用」清单只含 `diary_search` / `vector_search` / `session_list` / `message_search`，不含 `recall_relations`** — `packages/ai/src/agent/tool-usage-guidelines.util.ts:35-49`（**我独立复核**）
- `vector_search` / `memory_store` 受 `ragEnabled` + 嵌入能力门控（无嵌入时被注册表禁用），`recall_relations` 不受此限 — `packages/ai/src/tools/tool-registry.ts:102-119`（子 agent 核实）
- 每跳邻居上限 `GRAPH_MAX_NEIGHBORS_PER_HOP = 40`，枢纽剪枝 `hubDegreeThreshold = 40` — `packages/shared/src/utils/graph-view.constants.ts:35`（**我独立复核**）；`graph.repository.traverse.ts:297-313`
- 路径深度写死 2–3 跳、最多 6 条路径 — `graph-rag.service.ts:86-147`
- 图谱召回**无 score 字段、无打分公式** — `graph-rag.service.ts:16-23`
- `mention_count` = 该节点作为端点的 current 且未删除边数，不参与打分 — `graph.repository.mutate.ts:504-549`
- 重抽时旧 AI 边 supersede（`is_current=false`）不删除 — `raw-data/managers/graph.raw-manager.ts:365-389`
- **全仓无时间衰减/遗忘曲线** — grep `decay|forget|衰减|遗忘` 仅命中画布动画与测试
- 无 `vec0` ANN；向量检索是 `ORDER BY vec_distance_cosine(...) LIMIT n` 全表扫描 — `hybrid-search.repository.vector-search.ts:189-199`
- 文档自述「热门节点没有降权机制」 — `packages/core/src/graph/docs/unified-organize-plan.md:231`
- 文档 0.5 vs 代码 0.7 阈值不一致 — `unified-organize-plan.md:70` vs `graph-similar-pending.util.ts:6`

### 8.3 未核验 / 边界（不写进结论）

1. **Meowlisis 的实测数字来自公式复刻，不是线上日志**。复刻已逐行对齐 `_score/_relevance/_select/build_prompt`，但 topic 固定为线上真实值「日常」，`need_recall` 分支未纳入统计（该分支只做整体前置排序，不改变闸门与条数）。
2. **Meowlisis 构建耗时的绝对数值未测**（需真实 API key 与网络）；本文只断言「存在 1 次同步往返」这一结构事实。
3. **BaiShou 的真实召回命中率与延迟未测**（无数据集、无运行环境）。所有相关判断都限定为「机制由代码确定，劣化速率需实测」。
4. **BaiShou 的 `vector_search` 是否还有别处使用真 FTS5 未穷举**：`knowledge_chunks_fts` 确实存在且 `knowledge-search.service.ts` 用的是真 FTS5 MATCH（我读过该文件），但 `vector_search`（记忆通道）走的是 LIKE。**两者的措辞在注释里都写成 FTS，容易混淆**——这是它自己 `searchFts` 命名造成的。
5. **`ai/src/agent/system-prompt.builder.ts` 中「滚动摘要」的具体注入范围未逐行核验**（仅从 `vector_search` 的工具描述里看到「including any rolling summary」这一措辞）。因此本文讨论「自动注入」时只指图谱/向量通道，不包含该滚动摘要。
6. BaiShou 当前**没有可对照的真实图谱规模**，故 B1'/B2' 的劣化速率无法量化。

---

## 9. 如果只能记住三件事

1. **Meowlisis 的精度问题不在「摘要」，在「打分函数的量纲」**：`hits/1.0` 把一个连续信号压成了布尔值，于是 0.55 的权重被与查询无关的先验拿走。修这一处，收益最大、风险最小。
2. **Meowlisis 的「速度优先」当前是假的**：`decide_recall` 在热路径同步调 LLM。这一处与「精准」无关，但它是唯一一处**纯粹浪费**的延迟。
3. **白守的图谱值得学的是「结构」，不是「在线决策」**：`valid_from/is_current` 的事实有效期、6 种 typed edge、`pending` 人工闸门、`confidence` 门槛——这些都可以在不引入任何在线 AI 决策的前提下移植；而它「让模型自己决定查什么」的那一层，与速度优先原则直接冲突，不该抄。它的另一半问题（入口短路、RRF 量纲、LIKE 无分词）也不该抄。
