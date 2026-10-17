# PLAN · `.vendor/.MeowLLM` 自研模型加载模块（MeowLLM）实施方案

> **状态**：方案（未实施）。**不改动 `func/**`、`api.py`、`config.yml` 任何一行代码**，只做定位与设计。
> **依据**：`.vendor/.MeowLLM/docs/[参考价值-高]MIRRORConvergingCognitivePrinciples.pdf`、
> `工作流程解析/docs/PLAN_详细计划书_MIRROR_δmem.md`、`PLAN_框架与模型训练.md`、源码逐文件核对。

## 四条硬约束（本方案的设计前提）

| # | 约束 | 对设计的影响 |
|---|---|---|
| **C1** | **δ-mem 本期不实施**（还在构建前期，实验未验证完） | 引擎层**不为 δ-mem 预留 hook**，只保留"可换引擎"这一抽象。本期只做 MIRROR 编排（纯 prompt）+ 本地推理 + 缓存。`.vendor/.MeowLLM` 不引入任何 attention 改造 |
| **C2** | **下载由你亲自执行**，我只列清单 | 本文档 §8 给完整下载清单（含体积、来源、命令、放置路径），**不代下载** |
| **C3** | **所有接口命名统一 `meowllm`**，标准不得有歧义 | 端点 `/meowllm/v1/*`、请求扩展 `extra_body.meowllm`、类名 `MeowLLM*`、配置根键 `meowllm:`、环境变量 `MEOWLLM_*`、日志 `meowllm.*`。命名规范见 §4，**任何不叫 meowllm 的对外接口一律视为违规** |
| **C4** | **本机只验证可行性，绝不实际跑模型；禁止任何 >1B 的模型在本机运行** | 本机验证 = **零权重契约仿真**（`engine.kind: stub`）。并把这个约束**固化成代码闸门**：非 stub 引擎在参数 >1B 时直接拒绝启动（§7.2） |

---

## 0. 一页结论

| 项 | 结论 |
|---|---|
| 落地形态 | `.vendor/.MeowLLM` 是一个**独立常驻进程**，对外只开**本机回环端口**，全程无外网、无 api_key |
| 端口 | **`127.0.0.1:18100`**（§6）。`bind` 失败依次回退 18101–18108，实际端口写入 `state/meowllm/port.json` |
| 统一前缀 | base_url = `http://127.0.0.1:18100/meowllm/v1`（OpenAI 兼容子集）<br>控制面 = `http://127.0.0.1:18100/meowllm/control/*` |
| 本期范围 | MIRROR 编排（纯 prompt） + 本地推理接入 + 前缀/会话缓存 + function calling + 视觉 |
| **本期不做** | **δ-mem**（C1）、LoRA、训练、全双工、量化转换工具链 |
| 引擎 | `stub`（本机唯一，零权重） / `llamacpp` / `hf` / `vllm`（云端）。四者共用同一 HTTP 契约 |
| 本机现实 | RTX 5060 Laptop / **8151 MiB**。27B 最小量化也要 16GB → 本机连 4B 都不该起（C4 要求连 ≤1B 也不起） |
| **本机现在要下载什么** | **0 个**。`runtime/311` 已含 fastapi 0.135.3 / uvicorn 0.41.0 / pydantic 2.12.5 / openai 2.24.0 / PyYAML 6.0.1 / httpx 0.28.1（§8.1 实测） |
| 缓存命中 | 四层：模型常驻 → 前缀 KV → **MIRROR think/talk 共享前缀** → 会话级 KV。**有一个前置改造必须先做**：情绪在角色卡最前面，每轮打碎前缀（§5.9.3） |

---

## 1. 项目分析

### 1.1 运行形态

```
api.py（Flask 0.0.0.0:1800）  ← /chat /msg /say /tts/audio /mic /emote /api/start_napcat
  ├─ LLmCore       主对话（队列 + 1s 轮询）
  ├─ AutoActiveCore 主动回复（1s 轮询）
  ├─ TTsCore        语音合成（0.1s 轮询）
  └─ TBDanmakuCore / TBNapCatCore / SenseVoiceCore / MinecraftLogReader / DateBacklog

.vendor 外部服务（各自独立端口）
  .Sovits :9880   .SenseVoice :10095   .ComfyNode :8188   .RVC :7865
  .NeteaseMusic :5000   .NapCat ws :3001   .cam / .desktopet(桌宠 Electron)
```

`func/` 是纯 Python 编排层，**所有模型能力都通过 `port` 目录里的类访问** —— 这是本地化只需替换 port 的全部原因。

### 1.2 模块地图

| 目录 | 职责 | 吃模型 | 本期本地化 |
|---|---|---|---|
| `func/llm` | 主对话：清洗→入队→组 system→流式→TTS→记忆 | ✅ LLM | **✓** |
| `func/llm/narration` | 水词压缩（Trie + EWMA 打分，纯算法） | ❌ | — |
| `func/llm_active` | 空闲主动回复（origin / inherit / active_singing） | ✅ LLM + 视觉 | **✓** |
| `func/toolbox` | 工具总线：父级 function-calling 决策 | ✅ LLM | **✓** |
| `func/toolbox/napcat` | QQ 私聊/群聊，`qq_response.py`(41.7KB) 为回复主体 | ✅ LLM | **✓** |
| `func/toolbox/news`·`weather` | 抓数据 → LLM 以角色口吻播报 | ✅ LLM | **✓** |
| `func/toolbox/meowsongs` | 点歌 / 即兴哼唱 / 听歌识曲接龙 | ✅ LLM | **✓** |
| `func/toolbox/meowvision` | 截图/裁剪/变化检测/编码 → 视觉模型 | ✅ 多模态 | **✓** |
| `func/toolbox/flux_painter` | 绘画提示词 → ComfyUI；`port/base.py` 最规范 | ✅ LLM | 后续 |
| `func/catbrain` | 多层记忆：角色卡/价值观/用户档案/摘要/证据分 | ✅ 多路 LLM | 后续 |
| `func/psyche` | 心理状态机（每 5s 看短期记忆） | ✅ LLM | 后续 |
| `func/database` | 知识库 RAG：爬取 + 向量 + 关键词 | ✅ LLM + embedding | 后续 |
| `func/tts`·`vts`·`sensevoice` | 合成 / 皮套 / 识别（已有本地服务） | ❌ | — |
| `func/pipeline` | 30+ 桥接单例（`*Bridge`），模块间解耦 | 部分 | — |
| `plugins/` | 插件（demo / docwriter / epub_reader / pig_game） | ✅ 自带 port | 后续 |

### 1.3 三条 LLM 调用链（全部收敛到 port）

```
① 主对话   api.py → LLmCore.msg_deal → _ai_response → self.llm.chat_stream()
             工具合并模式：chat_stream(messages, tools, tool_choice="auto", enable_thinking=False)
             后置情绪：    chat_stream(update_messages, tools, tool_choice=强制 set_emotion)

② 工具箱   → TBoxCore → TBoxAnalysis.decide
             每个模块自带 _llm() 工厂：按 cfg.llm_type ∈ {gemini, aliyun, deepseek} 选 port
             用法：llm.chat(...)（62 处非流式）/ llm.chat_stream(...)（8 处）

③ 视觉     TBVisionCore / AutoVisionSender → sender.py 组 image_url → llm.chat()（非流式）
```

实测：`func/**` + `plugins/**` 共 **70 处** `chat()` / `chat_stream()` 调用点。

### 1.4 对本地化有决定性影响的 6 个事实

1. **契约高度统一** → 本地服务只要吐出合规 OpenAI 对象，**零改造可接管**。
2. **`reasoning_content` 被真实消费**：`napcat_llm.py:80`、`func/toolbox/port/*:66`、`docwriter/agent.py` 会读 `delta.reasoning_content`（流式）与 `message.reasoning_content`（非流式）。
3. **`finish_reason` / `usage` 全项目 0 命中** → 最小字段集即可，但仍建议发全。
4. **工具增量合并不容错**：`func/pipeline/llm_toolbox.py::ToolCallAccumulator` 严格依赖 `tc.index` / `tc.id` / `tc.function.name` / `tc.function.arguments` 的 OpenAI 分片顺序。
5. **强制 `tool_choice` 真在用**：`emotion_controller.build_tool_choice()` 返回 `{"type":"function","function":{"name":"set_emotion"}}`，且每轮必调。
6. **`if not llm.client` 是硬判真**：30+ 处用它判断端口可用 → 新 port 类**必须**有可判真的 `client` 属性。

### 1.5 前缀稳定性现状（决定缓存命中率）

`func/catbrain/prompt_builder.py::build()` 的 system 顺序：

```
角色卡（含当前情绪）   ← ★ 每轮都变，且在最前面
价值观
用户档案
知识库检索结果
# 现在是 时间
日期块（节日/节气/生日）
记忆摘要（前 30 条）
```

外层 `func/pipeline/system_prompt.py` 再包一圈：`前置词(行为约束)` 在最前、`后置词(人设)` 在最后。

→ 稳定前缀本来应该是「前置词 + 角色卡 + 价值观」，但**情绪坐在角色卡里、位置最靠前**，一改就整段失效。这是 §5.9.3 那条前置改造的全部理由。

---

## 2. Port 全清单（定位，不动）

### 2.1 总表（12 族 / 31 类）

| # | 端口族 | 类 | 方法 | 选择开关 | 调用点 | 优先级 |
|---|---|---|---|---|---|---|
| 1 | `func/llm/port/` | `DeepSeekLLM` `AliyunLLM` `GeminiLLM` | `chat_stream` | `llm.local_llm_type` | `llm_core._create_llm`、`pipeline/calendar_llm.py` | **P0** |
| 2 | `func/llm_active/port/` | `AutoDeepSeekLLM` `AutoAliyunLLM` `AutoGeminiLLM` | `chat`+`chat_stream` | `llm_active.llm_type` | `active_core.py` | **P0** |
| 3 | `func/toolbox/port/` | `TBoxDeepSeekLLM` `TBoxAliyunLLM` `TBoxGeminiLLM` | `chat`+`chat_stream` | `toolbox.llm_type` | 25+ 模块内联 `_llm()` | **P0** |
| 4 | `func/toolbox/meowvision/port/` | `TBVisionAliyunLLM` `TBVisionGeminiLLM` | `chat` | `meowvision.llm_type` | `meowvision/sender.py` | **P0** |
| 5 | `func/llm_active/origin/vision/port/` | `AutoVisionAliyunLLM` `AutoVisionGeminiLLM` | `chat` | `llm_active.vision.llm_type` | `origin/vision/sender.py` | **P0** |
| 6 | `func/database/store/port/` | `CatLearnAliyunEmbedding` `CatLearnEmbedding`(bge) | `embed_texts` `embed_one` | `database.store.llm_type` | 知识库 | P2 |
| 7 | `func/database/search/port/` | `CatLearnSearch{DeepSeek,Aliyun,Gemini}LLM` | `chat`+`chat_stream` | `database.search.llm_type` | 搜索理解 | P2 |
| 8 | `func/catbrain/AbstractMem/port/` | `MeowAbstract{…}LLM` | `chat` | `abstract_memory.llm_type` | 摘要归档 | P2 |
| 9 | `func/catbrain/CatValues/port/` | `MeowValues{…}LLM` + `MeowValuesReviewLLM` | `chat` | `values.llm_type` | 价值观 12h 更新 | P2 |
| 10 | `func/catbrain/UserMemory/port/` | `MeowUserMemory{…}LLM` | `chat` | `user_memory.llm_type` | 用户档案 | P2 |
| 11 | `func/toolbox/flux_painter/port/` | `TBFluxPainterLLMBase` + `Aliyun`/`DeepSeek` | `chat`+`chat_stream` | `flux_painter.llm_type` | 绘画提示词 | P3 |
| 12 | `func/catbrain/rules_break/port.py` | `TBRulesBreakPort` | `chat` | `rules_break.llm_type` | 破甲审查 | P3 |
| — | `plugins/docwriter/port.py` | `DocLLM` | `chat` `chat_text` | 插件 config | 白皮书 | P3 |
| — | `plugins/epub_reader/port.py` | `EpubLLM` | `chat` | 插件 config | 读书 | P3 |

> **命名陷阱**：`llm.local_llm_type` 里的 "local" 是"本项目自己的配置"之意，**不是"本地模型"**。新后端取值必须用 `meowllm`，**禁止用 `local`**（C3）。

### 2.2 四套方法签名（新端口必须逐一对齐）

```python
# 族 1  func/llm/port            ← 主对话，只流式
class MeowLLM:
    def __init__(self, config: LLMConfig = None)
    def chat_stream(self, messages, tools=None, options=None,
                    tool_choice=None, enable_thinking=None) -> Iterator[ChatCompletionChunk]

# 族 2  func/llm_active/port     ← 主动回复，流式 + 非流式
class AutoMeowLLM:
    def __init__(self)                              # 内部读 LLMConfig
    def chat(self, messages, tools=None, tool_choice=None, options=None)
    def chat_stream(self, messages, tools=None, options=None, tool_choice=None)

# 族 3  func/toolbox/port        ← 工具箱，参数顺序与族 1 不同！
class TBoxMeowLLM:
    def __init__(self, config=None)                 # TBoxConfig 或 LLMConfig
    def chat(self, messages, tools=None, tool_choice=None, enable_thinking=None)
    def chat_stream(self, messages, tools=None, tool_choice=None, options=None,
                    thinking_level: str = "off")     # 分档，不是布尔

# 族 4/5 视觉                    ← 只非流式
class TBVisionMeowLLM:
    def __init__(self, config=None)
    def chat(self, messages, tools=None, tool_choice=None)   # messages 内含 image_url
```

**注意**：族 3 的 `chat_stream` 第 3/4 参数是 `tool_choice, options`，族 1 是 `options, tool_choice`。**必须按各族分别实现，不能共用一套签名。**

### 2.3 各选择点形状

```python
# 内联三分支（25+ 处，全部长这样）
if cfg.llm_type == "gemini":     → TBoxGeminiLLM(cfg)
elif cfg.llm_type == "aliyun":   → TBoxAliyunLLM(cfg)
else:                            → TBoxDeepSeekLLM(cfg)

# 集中工厂（推荐参照的写法）
func/toolbox/flux_painter/port/base.py::create_painter_llm(config)   ← 基类 + 工厂，最干净
```

---

## 3. 本地化适用面（你点名的 6 块）

| 块 | 入口 | 族 | 方法 | 现状 max_tokens | 难点 | 优先级 |
|---|---|---|---|---|---|---|
| **主对话 llm** | `llm_core.py::_ai_response` | ① | `chat_stream` + tools | 256 | 语音链路首字延迟；system 常 3–6k token，**必须前缀缓存** | P0 |
| **主动回复 llm_active** | `active_core.py` | ② | `chat`/`chat_stream` | 512（=`max_tokens`×2） | 后台任务，可排队降优先级 | P0 |
| **napcat（QQ）** | `napcat/llm/napcat_llm.py`、`qq_response.py` | ③ | `chat_stream(thinking_level)` | 384（base+128） | **整段缓冲**不回 TTS → 大模型解码慢会明显卡 | P0 |
| **唱歌** | `meowsongs/{impromptu_sing,pass_the_baton}` | ③ | `chat` | 2048 | 结构化输出（歌名/区间），用 JSON 约束最稳 | P1 |
| **新闻** | `news/news_core.py` | ③ | `chat` | 2048 | 长文播报，decode 时间最长 | P1 |
| **天气** | `weather/weather_core.py` | ③ | `chat` | 2048 | 数据已在手，只需口吻改写 → 小模型够用 | P1 |
| **视觉回复** | `meowvision/`、`llm_active/origin/vision/` | ④⑤ | `chat`（多模态非流式） | 512 / 2048（gemini 600） | 图像 token 预填极贵，必须限分辨率 | P0（多模态核心价值） |

> 全部 7 块**共用同一个 MeowLLM 进程**，靠请求参数区分用途，不起 7 个服务。

---

## 4. MeowLLM 命名规范（C3，强制）

> 原则：**凡是对外可见的接口名，必须自带 `meowllm`**。目的是让任何一处日志、URL、配置键、类名都能一眼看出"这是我们自己的标准"，不会和 OpenAI / llama.cpp / Ollama / 项目自己的 `local_*` 混淆。

### 4.1 端点

| 类别 | 路径 | 说明 |
|---|---|---|
| OpenAI 兼容子集 | **`/meowllm/v1/chat/completions`** | 流式 / 非流式 / tools / 多模态 |
| OpenAI 兼容子集 | **`/meowllm/v1/models`** | 探活 + 模型名 |
| 原生控制面 | `/meowllm/control/health` | 引擎状态、显存、就绪 |
| 原生控制面 | `/meowllm/control/stats` | 缓存命中率 / TPS / TTFB / 队列 |
| 原生控制面 | `/meowllm/control/think` | 手动触发 MIRROR 思考步 |
| 原生控制面 | `/meowllm/control/session/reset` | 清会话 KV + ThinkState |
| 原生控制面 | `/meowllm/control/reload` | 热重载 `meowllm.yml` |
| 原生控制面 | `/meowllm/control/selftest` | 跑契约自测矩阵（§7.4） |

**项目侧 base_url**：`http://127.0.0.1:18100/meowllm/v1`
（openai SDK 会自动拼 `/chat/completions` → 正好落到 `/meowllm/v1/chat/completions`）

**响应头**（每个响应都带）：`X-MeowLLM-Version`、`X-MeowLLM-Engine`、`X-MeowLLM-Cache`（`hit`/`miss`/`bypass`）

### 4.2 请求扩展字段

**唯一合法形式**：`extra_body.meowllm.{…}`。**禁止任何顶层自定义字段。**

```jsonc
"extra_body": {
  "meowllm": {
    "thinking_level": "off",        // off | low | medium | high
    "think_budget": 768,            // 可选，覆盖档位默认
    "session_id": "000001",         // = meowid，用于会话 KV + ThinkState
    "context_limit": 16384,
    "max_tokens": 256,              // 与顶层同义，二选一
    "cache": { "enabled": true, "pin_prefix": true },
    "priority": "interactive",      // interactive | background
    "language": "zh"
  }
}
```

**兼容要求**：现有 port 会往 `extra_body` 顶层塞 `{"thinking":{"type":"disabled"}}` / `{"parameters":{"enable_thinking":false}}` / `reasoning_effort`。MeowLLM **必须容忍并映射**这些字段（映射规则见 §5.6.4），未知字段一律忽略不报错 —— 这是 §10.1「零改动接入」能成立的前提。

### 4.3 响应扩展字段

```jsonc
{
  "choices": [ ... ],                       // 标准 OpenAI，不动
  "meowllm": {                              // 我们自己的元信息，客户端可忽略
    "engine": "stub",
    "cache": "hit",                         // hit | miss | bypass
    "prefix_tokens_cached": 3120,
    "prefill_ms": 12,
    "ttfb_ms": 41,
    "decode_tps": 31.5,
    "think_tokens": 0,
    "think_budget": 768,
    "truncated_history": 0
  }
}
```

### 4.4 命名全集

| 类别 | 规则 | 示例 |
|---|---|---|
| Python 包 | 根包 `meowllm` | `meowllm.engine.base` |
| 类名 | **一律 `MeowLLM` 前缀，禁止裸名** | `MeowLLMEngine`（✅）／`Engine`（❌）<br>`MeowLLMConfig`／`MeowLLMRequest`／`MeowLLMPrefixCache`／`MeowLLMSessionCache`／`MeowLLMThinkState`／`MeowLLMToolGuard`／`MeowLLMVisionEncoder` |
| 引擎实现 | `MeowLLMEngine{Stub,LlamaCpp,Hf,Vllm}` | `engine/meowllm_engine_stub.py` |
| 配置文件 | `meowllm.yml`，**根键 `meowllm:`** | 保证将来可整段并入项目 `config.yml` 而不冲突 |
| 配置键路径 | `meowllm.<section>.<key>` | `meowllm.server.port` |
| 环境变量 | `MEOWLLM_*` | `MEOWLLM_PORT`、`MEOWLLM_CONFIG`、`MEOWLLM_LOG_LEVEL`、`MEOWLLM_ALLOW_LOCAL_MODEL` |
| 日志 logger | `meowllm.<module>` | `meowllm.engine.stub` |
| 日志文件 | `logs/meowllm-YYYYMMDD.log` | — |
| 状态文件 | `state/meowllm/<kind>/<id>.json` | `state/meowllm/mirror/000001.json`、`state/meowllm/port.json` |
| 启动脚本 | `bin/meowllm_*.ps1` | `meowllm_start.ps1`、`meowllm_selftest.py`、`meowllm_bench.py` |
| 进程标识 | 窗口/进程名 | `MeowLLM@18100` |
| 项目侧配置 | `llm.local_llm_type: meowllm` + `llm.meowllm: {…}` | **禁止 `local`** |
| 项目侧 port 类 | 族前缀 + `MeowLLM` | `MeowLLM` / `AutoMeowLLM` / `TBoxMeowLLM` / `TBVisionMeowLLM` / `AutoVisionMeowLLM` |

### 4.5 禁用名清单（歧义源）

`local` · `local_llm` · `llm_local` · `LocalLLM` · `EdgeLLM` · `ollama` · `llamacpp`（作为对外接口名）· `vllm`（同上）· `OllamaLLM` · 裸 `Engine` / `Config` / `Client`

> 引擎实现内部可以自由提 llama.cpp / vLLM，但**不能出现在端点、配置键、类名、请求字段里**。

---

## 5. `.vendor/.MeowLLM` 模块设计

### 5.1 定位与边界（C1 / C4 落地）

- **是**：独立常驻的"自研模型加载 + 认知编排"服务，监听 `127.0.0.1:18100`。
- **不是**：`func/` 的子模块；不读/写 `.temp`；不改项目任何文件。
- **本期不含 δ-mem**：`engine/` 不实现 attention hook，也不预留复杂接口。只保证"引擎可替换"这一层抽象（将来 δ-mem 落地时只新增一个 `engine/meowllm_engine_hf.py`，HTTP 契约不变）。
- **依赖隔离**：自带 `.venv`。V0 阶段零下载（§8.1）。

### 5.2 必须先讲清：MIRROR 不是推理引擎

| 层 | 是什么 | 需要改模型吗 | 本期 |
|---|---|---|---|
| **MIRROR（认知架构）** | 并行独白（Goals/Reasoning/Memory）→ 认知控制器合成**有界叙事** → **每轮重构不累积**；Talker/Thinker 时序分离 | ❌ 纯 prompt + 状态机 | **✓ 做** |
| **δ-mem（记忆进注意力）** | `S∈R^{r×r}` 门控 delta 写、低秩修正 q/o | ✅ 必须改 attention | **✗ 不做（C1）** |
| 量化 | GGUF / AWQ / GPTQ / NF4 | — | 云端需要 |

所以 **`.vendor/.MeowLLM` = MeowLLM 框架（认知 + 加载 + 服务），推理引擎是它内部的可替换部件**。本期不需要为 δ-mem 做任何让步，也不需要动 attention。

### 5.3 目录结构

```
.vendor/.MeowLLM/
├─ docs/                                  # 已有：MIRROR 论文（不动）
├─ meowllm.yml                            # 唯一配置入口（根键 meowllm:）
├─ requirements.txt                       # V0 为空（复用 runtime/311）
├─ .venv/                                 # 可选；否则直接用 runtime/311
│
├─ meowllm/
│  ├─ __init__.py                         # 版本号 MeowLLM_VERSION
│  ├─ server/
│  │   ├─ meowllm_app.py                  # FastAPI 入口，127.0.0.1:18100
│  │   ├─ meowllm_routes_v1.py            # /meowllm/v1/*
│  │   ├─ meowllm_routes_control.py       # /meowllm/control/*
│  │   ├─ meowllm_schema.py               # extra_body.meowllm 解析 + 参数归一
│  │   └─ meowllm_stream.py               # OpenAI 分片封装（content/reasoning/tool_calls）
│  ├─ engine/
│  │   ├─ meowllm_engine_base.py          # 抽象：load/generate/tokenize/kv
│  │   ├─ meowllm_engine_stub.py          # ★ 本机唯一允许（零权重）
│  │   ├─ meowllm_engine_llamacpp.py      # 云端 GGUF
│  │   ├─ meowllm_engine_hf.py            # 云端 transformers + AWQ/GPTQ/NF4
│  │   ├─ meowllm_engine_vllm.py          # 云端 Linux（吞吐）
│  │   └─ meowllm_engine_factory.py       # ★ 安全闸门（C4）
│  ├─ mirror/
│  │   ├─ meowllm_mirror_state.py         # ThinkState（有界 + 每轮重构）
│  │   ├─ meowllm_mirror_loop.py          # 后台思考循环 + salience 门控
│  │   ├─ meowllm_mirror_prompt.py        # Talker 分区 prompt
│  │   └─ meowllm_mirror_core.py          # 状态机 IDLE→TALK→THINK
│  ├─ cache/
│  │   ├─ meowllm_cache_prefix.py         # 前缀哈希 → KV 槽位
│  │   └─ meowllm_cache_session.py        # per-meowid 会话 KV（LRU + 预算）
│  ├─ tools/
│  │   ├─ meowllm_tool_guard.py           # JSON Schema → 语法约束
│  │   └─ meowllm_tool_parse.py           # 工具调用解析 + 流式分片
│  └─ vision/
│      ├─ meowllm_vision_encode.py        # 图像规格化 + max_pixels 限流
│      └─ meowllm_vision_template.py      # image_url → 模型侧视觉 token
│
├─ state/meowllm/                         # 运行态（★ 不写项目 .temp）
│  ├─ port.json
│  └─ mirror/<meowid>.json
├─ models/                                # 权重（.gitignore 已忽略 *.gguf / *.safetensors）
├─ logs/
└─ bin/
   ├─ meowllm_start.ps1                   # 启动 + 健康轮询 + 就绪打印
   ├─ meowllm_selftest.py                 # 契约自测矩阵（§7.4）
   ├─ meowllm_project_probe.py            # ★ 用项目真 port 打本服务
   └─ meowllm_bench.py                    # TPS / 缓存命中基准
```

### 5.4 三层架构

```
┌──────────────────────────────────────────────────────────────────┐
│ L3 传输层  meowllm/server/                                       │
│   127.0.0.1:18100 · /meowllm/v1/* · /meowllm/control/*           │
│   扩展：extra_body.meowllm · 响应：顶层 meowllm 对象 · X-MeowLLM-* │
├──────────────────────────────────────────────────────────────────┤
│ L2 认知层  meowllm/mirror + tools + cache + vision               │
│   MIRROR 状态机 · 焦点锁 · 有界重构 · 工具约束 · 前缀/会话缓存      │
├──────────────────────────────────────────────────────────────────┤
│ L1 引擎层  meowllm/engine/                                       │
│   stub（本机） │ llamacpp │ hf │ vllm（云端）                      │
└──────────────────────────────────────────────────────────────────┘
```

L2 只依赖 L1 的抽象接口，不依赖任何具体引擎。换引擎 = 换一个文件。

### 5.5 对外接口契约（必须逐字对齐的字段）

```jsonc
// 流式 chunk（/meowllm/v1/chat/completions, stream=true）
{"choices":[{"index":0,"delta":{
    "content":"喵",                    // 主对话流式读这里
    "reasoning_content":"…",           // napcat / 工具箱读这里
    "tool_calls":[{"index":0,"id":"call_0","type":"function",
                   "function":{"name":"set_emotion","arguments":"{\"emo"}}]
},"finish_reason":null}],
 "meowllm":{...}}

// 非流式（62 处 llm.chat 的消费方式）
{"choices":[{"message":{"content":"…","reasoning_content":"…",
                        "tool_calls":[{"id":"…","type":"function",
                                       "function":{"name":"…","arguments":"…"}}]},
             "finish_reason":"stop"}],
 "usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0},
 "meowllm":{...}}
```

`finish_reason` / `usage` 项目侧不消费，但仍要发（兼容其他 OpenAI 客户端）。
`meowllm` 是额外顶层字段；`openai` SDK 的模型允许 extra 字段，不会报错。

### 5.6 参数体系与思考强度

#### 5.6.1 `meowllm.yml`（服务级）

```yaml
meowllm:
  server:
    host: 127.0.0.1          # 严禁 0.0.0.0
    port: 18100
    port_fallback: 9         # 18100..18108
    request_timeout: 120
  model:
    name: meowllm-local      # 项目侧 model: 填它
    path: models/…           # 本机留空
    quant: q4_k_m            # q4_k_m|q5_k_m|q6_k|q8_0|awq|gptq|nf4
    vision_encoder_dtype: fp16
  context:
    n_ctx: 8192
    n_batch: 512
    n_ubatch: 512
    n_threads: 0             # 0 = 自动物理核
  gen:
    max_tokens: 512
    temperature: 0.8
    top_p: 0.9
    top_k: 40
    repeat_penalty: 1.05
    stop: ["<|im_end|>"]
  engine:
    kind: stub               # ★ 本机唯一允许值（C4）
    n_gpu_layers: -1
    load_in_4bit: true
    flash_attn: true
  safety:                    # ★ C4 的代码闸门
    allow_engine: [stub]     # 本机白名单；云端改成 [stub,llamacpp,hf,vllm]
    max_local_model_params_b: 1.0
    require_env_override: true   # 非 stub 必须设 MEOWLLM_ALLOW_LOCAL_MODEL=1
  thinking:
    default_level: off
    budgets: {off: 0, low: 256, medium: 768, high: 2048}
    force_off_when_tools: true
  cache:
    prefix:  {enabled: true, slots: 4, min_prefix_tokens: 256}
    session: {enabled: true, max_sessions: 8, ttl_seconds: 3600}
    kv_quant: q8_0
    keep_alive: true
  queue:
    max_concurrency: 1
    interactive_priority: true
  mirror:
    enabled: false           # 先跑通纯推理，再开 MIRROR
    narrative_max_tokens: 1500
    plan_next_max: 3
    salience_threshold: 0.25
  vision:
    max_pixels: 921600       # ≈1280×720
    min_pixels: 200704
    session_prefix: "vision:"
  stub:                      # 仅 engine.kind=stub 生效
    reply: "喵~（MeowLLM stub 回复）"
    chunk_chars: 4
    chunk_delay_ms: 15
    emit_reasoning: true
    reasoning_chars: 120
    tool_call: null          # 例：{"name":"set_emotion","arguments":{"emotion":"happy"}}
    parallel_tools: 1
    split_arguments: 12      # arguments 每片字符数
    sim: {prefill_tps: 1200, decode_tps: 30}
```

#### 5.6.2 请求级 → 实际生效

| 请求参数 | 落到引擎 |
|---|---|
| `max_tokens` | 解码硬截断 |
| `temperature` / `top_p` / `top_k` | 采样器 |
| `context_limit` | `min(n_ctx, 请求值)`；超长按"丢最早历史、保留 system 稳定段"裁剪，并在 `meowllm.truncated_history` 回显条数 |

#### 5.6.3 思考强度：**强制预算**，不是"请求"

云 API 只能请求思考，本地可以强制。这是本模块相对云端的真实优势。

| 档位 | chat template | think 预算 | 对应项目现状 |
|---|---|---|---|
| `off` | `enable_thinking=false` | 0 | **主对话合并工具模式**（项目已这么传）、情绪更新、napcat 默认、天气/新闻播报 |
| `low` | `true` | 256 | 主动回复 origin |
| `medium` | `true` | 768 | napcat 群聊（现状 `toolbox.napcat.thinking_level: medium`）、唱歌感想 |
| `high` | `true` | 2048 | 价值观更新、记忆摘要/审查、海龟汤裁判 |

**实现**：解码循环计数，达预算即注入 thinking 结束符并切正文；`max_tokens` 从总预算里扣。
**目的**：避免"思考吃光 token 导致 `content` 为空" —— 正是 `napcat_llm.py:94` 那句告警 `回复为空！reasoning_content 长度=…` 的场景。
**硬规则**：`tools` 非空时默认 `thinking_level=off`（项目现有代码在所有工具场景都已这么传，保持同向）。

#### 5.6.4 兼容映射（让现有 port 的旧字段也能工作）

| 现有 port 塞的字段 | MeowLLM 处理 |
|---|---|
| `extra_body.thinking.type == "disabled"` | → `thinking_level=off` |
| `extra_body.thinking.type == "enabled"` | → `thinking_level=medium` |
| `extra_body.parameters.enable_thinking == false` | → `thinking_level=off` |
| `reasoning_effort: "low"/"medium"/"high"` | → 对应档位（`off` 映射 `low`） |
| `tool_choice` 非空 | 强制 `thinking_level=off` |
| 任何未知字段 | 忽略，记 debug 日志，不报错 |

### 5.7 Function Calling

| 要求 | 来源 | MeowLLM 实现 |
|---|---|---|
| 流式分片严格符合 OpenAI | `ToolCallAccumulator` 按 `index` 累积、`arguments` 增量拼接 | 分片器按 `{index,id,function:{name,arguments}}` 逐块发；`name` 只在首块给全；`arguments` 每片 `split_arguments` 字符 |
| 真支持强制单函数 | `emotion_controller.build_tool_choice()` 每轮必调 | 强制模式：预置工具调用开头 token / 语法约束到该函数 |
| 参数必须是合法 JSON | 下游 `json.loads` | **语法约束解码**（GBNF / outlines），从 schema 生成，而不是"求模型写对" |
| 并行多工具 | `ToolCallAccumulator` 支持 `index>0` | 支持 0..n-1，默认上限 4 |
| 工具多且杂 | 父级注册 12 模块入口 + 插件，schema 估 3–6k token | **工具子集化**：复用项目 `pre_route_plan` 结果决定给哪些；MeowLLM 侧再加意图 top-k（默认 ≤8 个工具） |

⚠️ **本地模型最容易翻车的点**：工具 schema 大 + 中文口语输入 → 选错工具/漏参数。所以默认开工具子集化，并在 §11 单列"工具选择准确率"门禁。

### 5.8 视觉

- **输入**：`meowvision/sender.py::_to_url()` 产 `data:image/png;base64,...`；`llm_active/origin/vision` 同。MeowLLM 必须吃 `data:` 与 `http(s)`。
- **必须限分辨率**：按 Qwen-VL 系 `min_pixels`/`max_pixels` 把单图 token 压到 **≤1200**。
- **非流式**：两个视觉 port 都只有 `chat()`，保持非流式。
- **视觉请求独立 `session_id`**（`vision:<meowid>`）+ 短 TTL，避免图像 KV 挤爆文本会话。
- **云端量化注意**：AWQ/GPTQ 通常只量化语言塔，**视觉编码器保 fp16**，`meowllm_engine_hf.py` 要显式混合精度加载。

### 5.9 缓存命中与 TPS（本方案重点）

#### 5.9.1 四层缓存

| 层 | 做什么 | 手段 | 收益（估） |
|---|---|---|---|
| **L1 模型常驻** | 启动即加载，永不卸载；权重 mmap | `meowllm_start.ps1` + 健康探活 | 省掉每次 10–60s 加载 |
| **L2 前缀 KV** | 相同前缀直接命中，跳过预填 | llama.cpp：`cache_prompt` + `--prompt-cache` + `n_keep`；vLLM：`--enable-prefix-caching`；HF：自建 prefix→KV 槽位 | system 3–6k token 预填 2–5s → 0.1–0.3s |
| **L3 MIRROR 共享前缀** | Thinker / Talker 的 `[system+history]` 完全相同，只差最后一句指令 | 思考步结束后 KV 交给输出步，只预填尾部 | 第二次前向近似免费（**MIRROR 专属红利**） |
| **L4 会话 KV** | 同一 meowid 跨轮只追加 | per-session KV 槽位 + LRU + 显存预算 | 多轮预填成本趋近 0 |

#### 5.9.2 为什么 L2 是语音链路的**前置条件**（不是优化项）

主对话边流边送 TTS（`llm.split_limit: 14`）。首字延迟 = 预填 + 首句解码。

- 无前缀缓存：3–6k token 预填 ≈ **2–5 s** → 语音"嗯…"明显卡顿
- 有前缀缓存：稳定段几乎 0 成本 → 首字 **0.2–0.5 s**

→ **前缀缓存不达标，本地大模型不能上主语音链路。** 写进 §11 门禁。

#### 5.9.3 ★ 前置改造：让提示词「稳定段在前」

**问题**（§1.5）：`角色卡（含当前情绪）` 在 system 最前面，情绪每轮变 → 稳定前缀每轮整段作废，L2 命中率接近 0。

```
现在：[前置词][角色卡+情绪][价值观][用户档案][知识库][现在时间][日历][记忆摘要][后置词]
                    ↑ 每轮变，且在头部

目标：[前置词][角色卡·去情绪][价值观][用户档案][知识库][现在时间][日历][记忆摘要][情绪][后置词]
        └──────────── 稳定段（可缓存）────────────┘ └─ 易变段 ─┘
```

更彻底：把「情绪 / 现在时间 / 记忆摘要」移出 system，作为 `messages` 最后一条 system 或用户消息前缀块 → `[system + 历史]` 整体成为稳定前缀，L2/L4 同时受益。

**这条价值大于任何引擎调优**：不改它，量化和显存优化带来的收益会被 3–5s 的无效预填抹掉。
（这是原项目改动，需另立小方案；本方案只定位。）

#### 5.9.4 TPS 提升清单

| 手段 | 预期 | 代价 |
|---|---|---|
| 权重量化（Q4_K_M / AWQ-4bit） | 显存 −70%，decode 1.5–2.5× | 质量损失，需逐模块验收 |
| KV 量化（`q8_0`） | KV 显存减半 | 极长上下文精度略降 |
| `n_batch`/`n_ubatch` 调优 | prefill +20–60% | 吃显存峰值 |
| 前缀缓存（L2/L3/L4） | **等效 TPS 大幅提升** | 需提示词稳定（§5.9.3） |
| 投机解码（草稿模型） | decode 1.5–2× | 多一份小模型显存 |
| 连续批处理（vLLM） | 群聊突发吞吐数倍 | Windows 不可用，需云端 Linux |
| `priority` 调度 | 交互不被后台记忆任务阻塞 | 需实现队列 |

**量级参考（必须实测校正）**：27B 稠密 Q4 单卡 4090 → decode 25–35 tok/s，prefill 800–1500 tok/s。项目回复常 128–256 token → decode 4–9 s。语音靠首句 14 字切分 + 流式 TTS 掩盖；**QQ 整段缓冲会明显变慢**。

### 5.10 MIRROR 编排（本期做，纯 prompt）

```
① Talker（前台 = /meowllm/v1/chat/completions）
   把 MIRROR 分区拼在项目 system **之后**（保证项目 system 仍是稳定前缀）：
     # 你此刻的内心（仅供思考，禁止复述）
     {thinking}                 ← 上一轮重构结果，≤1.5k token
     # 本轮焦点（必须遵守）
     只回应：{focus}
     # 行为约束（否定式）
     只输出与焦点相关的一句；不总结、不铺陈、不复述内心
     # 记忆（少量）
     {top 3–6 条}

② Thinker（后台 = 内部调用，或 POST /meowllm/control/think）
   输入：最近 3 轮 + 上一次 narrative（★ 不给原始全史，强制压缩）
   输出（结构约束 JSON）：focus / plan_next[] / open_threads[] / thinking
   约束：thinking ≤1.5k token；plan_next ≤3；focus 必须 1 句

③ 状态机
   IDLE ──用户消息──► TALK ──结束──► THINK ──沉淀完成──► IDLE
   salience 门控：琐碎轮（"嗯""哈哈"）跳过思考
```

- **状态落盘 `state/meowllm/mirror/<meowid>.json`**，不写 `.temp`
  （`PLAN_详细计划书` 原写的 `.temp/think_state_*.json` 与项目缓存语义冲突，建议改用 MeowLLM 内路径）
- **每轮重构，禁止追加**；超限直接截断重写
- 与 **L3 缓存天然协同**：Thinker 的 KV 直接给 Talker 复用
- `mirror.enabled=false` 时退化成纯推理，行为与现有云 API 一致 → 便于 A/B

### 5.11 健康、降级、并发

- 启动后轮询 `/meowllm/control/health`，就绪才打印 `MEOWLLM READY`；未就绪返回 503 + `Retry-After`
- 超时：交互 8s TTFB / 120s 总；后台 300s
- 单卡默认 `max_concurrency: 1`，优先级队列（`priority: interactive` 先出）
- 服务挂掉不会拖死项目：所有 port 调用都有 `try/except` + `None` 兜底，只是"某模块不回复"

---

## 6. 端口方案

### 6.1 已占用（实测 `config.yml`）

| 端口 | 归属 |
|---|---|
| `1800` | 项目 Flask（`0.0.0.0`） |
| `3001` | NapCat 正向 WS |
| `5000` | `.NeteaseMusic` |
| `7865` | `.RVC` |
| `8090` | flux_painter `http_port` |
| `8188` | `.ComfyNode`(ComfyUI) |
| `8767` | flux_painter `ws_port` |
| `9880` | `.Sovits`(GPT-SoVITS) |
| `10095` | `.SenseVoice`(WS) |

本机 `netsh int ipv4 show excludedportrange protocol=tcp` 只有 `5357`，无大片保留区。

### 6.2 选型：`127.0.0.1:18100`

| 候选 | 判定 |
|---|---|
| **18100** | ✅ **采用**。实测 FREE、不在保留区、与 `1800` 同族易记、避开 8000/8080/8081/8888/11434(Ollama)/1234/5000 |
| 18101–18108 | 备用回退位（实测均 FREE） |
| 11434 | ❌ Ollama 默认口 |
| 8080 / 8000 / 8888 | ❌ 太常见 |
| 7860 / 7861 | ❌ Gradio 家族 |

**只绑 `127.0.0.1`**（与项目 Flask 的 `0.0.0.0:1800` 有意不同——本地推理服务没有理由对外）。

自检脚本（落地时跑一次）：

```powershell
foreach ($p in 18100..18108) {
  try { $l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,$p); $l.Start(); $l.Stop(); "port $p FREE" }
  catch { "port $p BUSY" }
}
```

---

## 7. 验证策略：本机零模型（C4）

### 7.1 三级验证体系

| 级别 | 环境 | 模型 | 验证什么 | **不**验证什么 |
|---|---|---|---|---|
| **V0 契约仿真** | **本机 8G** | **不加载任何权重**（`engine.kind: stub`） | HTTP 契约、流式分片、工具调用合并、`reasoning_content`、视觉 data URL、缓存键计算与命中率记账、MIRROR 状态机、端口回退、**70 处调用点不崩** | 模型质量、真实 TPS、显存、量化 |
| **V1 替身真跑** | 云端 24G | Qwen3-VL-8B-Instruct（bf16 ≈16GB） | 真实 TPS / 缓存命中率 / 工具选择准确率 / 视觉可用率 / 首字延迟 | 27B 的量级 |
| **V2 目标** | 云端 40–80G | Qwen3.8-27B AWQ（≈16GB） | 生产指标 | — |

**本机 V0 的产出价值**：证明"项目 ↔ MeowLLM"契约成立 + 缓存账本正确 + MIRROR 状态机不卡死。**这三件事不需要任何权重就能验证**，正好是 C4 下的最优解。

### 7.2 把 C4 固化成代码闸门（`meowllm_engine_factory.py`）

```python
def create(cfg) -> MeowLLMEngineBase:
    kind = cfg.engine.kind
    # 闸 1：引擎白名单（本机只有 stub）
    if kind not in cfg.safety.allow_engine:
        raise MeowLLMError(f"引擎 {kind} 不在白名单 {cfg.safety.allow_engine}")

    # 闸 2：非 stub 必须显式环境变量放行
    if kind != "stub" and cfg.safety.require_env_override:
        if os.environ.get("MEOWLLM_ALLOW_LOCAL_MODEL") != "1":
            raise MeowLLMError("非 stub 引擎需要 MEOWLLM_ALLOW_LOCAL_MODEL=1 才允许启动")

    # 闸 3：参数量硬上限（读 config.json / GGUF metadata）
    if kind != "stub":
        params_b = probe_params_b(cfg.model.path)     # 读不到就按 >>1B 处理
        if params_b > cfg.safety.max_local_model_params_b:
            raise MeowLLMError(
                f"拒绝加载：{params_b:.2f}B > 上限 {cfg.safety.max_local_model_params_b}B"
                "（本机禁止运行 >1B 模型）")
    return _ENGINES[kind](cfg)
```

三道闸叠加后，**本机物理上不可能跑起 >1B 模型**（默认配置连非 stub 都不允许）。云端把 `allow_engine` 与 `max_local_model_params_b` 改掉即可，无需改代码。

### 7.3 `MeowLLMEngineStub` 设计（本机唯一引擎）

- **不 import torch、不读权重**，只依赖标准库 + FastAPI
- 按 `meowllm.stub.*` 吐预设内容，可控制：
  - `emit_reasoning`：先吐 `reasoning_content` 再吐 `content`（验证 §5.6.3 预算与 §1.4-② 消费点）
  - `tool_call` / `parallel_tools` / `split_arguments`：验证 `ToolCallAccumulator` 的增量合并
  - `chunk_chars` / `chunk_delay_ms`：验证流式节奏
- **时序仿真**：`stub.sim.prefill_tps` / `decode_tps` → 让 TTFB / 等效 TPS 的算式可在本机验证
- **缓存账本是真的**：真实计算前缀哈希、真实记账命中率（这是本机能验证的、最有价值的东西）
- **视觉**：接受 `data:` URL，解析 PNG/JPEG 头拿宽高，回 `看到 {w}×{h} 图，预计 token≈N`

### 7.4 `meowllm_selftest.py` 契约自测矩阵（12 项，全部本机可跑）

| # | 用例 | 期望 |
|---|---|---|
| 1 | 非流式 chat | `choices[0].message.content` 非空，`usage` 存在 |
| 2 | 流式 chat | 拼接后 == 非流式 content；`finish_reason` 末块为 `stop` |
| 3 | `tool_calls` 分片 | 合并后 `arguments` 是合法 JSON，`name` 完整 |
| 4 | 强制 `tool_choice` | 只返回该函数，不夹带其他 |
| 5 | `tools` 非空 | 忽略 thinking，`think_tokens == 0` |
| 6 | `thinking_level=high` | 先 `reasoning_content` 后 `content`；`think_tokens ≤ budget` |
| 7 | `image_url` data URL | 200，回显像素尺寸 |
| 8 | 同前缀二次请求 | `meowllm.cache == "hit"`，`prefix_tokens_cached > 0` |
| 9 | 变前缀请求 | `meowllm.cache == "miss"` |
| 10 | 不同 `session_id` | 会话 KV 互不污染 |
| 11 | 未知 `extra_body` 字段 | 200，不报错 |
| 12 | 超 `context_limit` | 触发裁剪，`truncated_history > 0`，system 头部保留 |

### 7.5 `meowllm_project_probe.py`（★ 最高价值的那一项）

**用项目真正的 port 类打我们的 stub 服务**，而不是用 openai SDK 裸测。这样验证的是"项目代码能不能吃下我们的流"，而不是"我们符不符合文档"：

```python
# 伪代码：把 base_url 指到 18100，直接实例化项目自己的 port 类
from func.llm.config import LLMConfig
cfg = LLMConfig()
cfg.deepseek_api_key  = "meowllm"
cfg.deepseek_base_url = "http://127.0.0.1:18100/meowllm/v1"
cfg.deepseek_model    = "meowllm-local"

from func.llm.port.deepseek import DeepSeekLLM          # 族 1
from func.toolbox.port.deepseek import TBoxDeepSeekLLM  # 族 3 → chat() + chat_stream(thinking_level)
from func.toolbox.meowvision.port.aliyun import ...     # 族 4 → 多模态 data URL

# 逐项断言：不抛异常、content 正确、tool_calls 能合并、reasoning_content 能读到、llm.client 可判真
```

这一步过了，就等价于"方案 B 零改动接入已成立"，可以放心进云端 V1。

---

## 8. 下载清单（C2：你自己下）

> 全部标注 **【现在】** / **【以后】**。凡标【现在】的，V0 阶段真的需要。

### 8.1 【现在】本机 V0 契约仿真 —— **0 个下载**

`runtime/311` 实测已具备全部所需（我刚核对过版本）：

| 包 | 版本 | 用途 |
|---|---|---|
| fastapi | 0.135.3 | MeowLLM 服务框架 |
| uvicorn | 0.41.0 | ASGI 服务器 |
| pydantic | 2.12.5 | 请求/响应模型 |
| starlette | 1.0.0 | `StreamingResponse`（SSE 不需要 sse-starlette） |
| openai | 2.24.0 | 自测客户端 + 项目 side 兼容性验证 |
| httpx | 0.28.1 | openai 依赖 |
| PyYAML | 6.0.1 | `meowllm.yml` |
| numpy | 2.4.2 | 图像/指标计算 |
| pillow | 10.2.0 | data URL 解码 + 像素读取 |

**结论：V0 直接 `D:\.Meowlisis\runtime\311\python.exe` 起服务，不装任何东西、不建 venv。**
`engine.kind: stub` 不 import torch，启动 <1s。

（可选）要独立 venv 也不需联网：`runtime\311\python.exe -m venv --system-site-packages .vendor\.MeowLLM\.venv`

### 8.2 【以后·可选】本机 ≤1B 冒烟 —— 默认**不启用**

C4 已禁止本机跑模型，本节仅作"万一你以后想在本机做一次极小冒烟"的备用清单。**默认配置下 `safety.allow_engine: [stub]` 会把它们全部挡住。**

| 项 | 文件 | 体积 | 来源 |
|---|---|---|---|
| llama.cpp CUDA 运行时 | `cudart-llama-b11669-bin-win-cuda-13.4-x64.zip` | 404 MB | [release b11669](https://github.com/ggml-org/llama.cpp/releases/tag/b11669) |
| llama.cpp 主程序 | `llama-b11669-bin-win-cuda-13.4-x64.zip`（资产名以 release 页为准） | ~150–250 MB | 同上 |
| 冒烟用极小模型 | Qwen3-0.6B GGUF Q8_0（≈0.7 GB） | 0.7 GB | HF `Qwen/Qwen3-0.6B-GGUF` |

> ⚠️ **必须用 `cuda-13.4` 构建，不要用 `cuda-12.4`**：RTX 5060 是 Blackwell（sm_120），需要 CUDA ≥12.8 编译的内核，12.4 构建不含 sm_120。这一点落地时以 `nvidia-smi` + 实际跑一次确认为准。

### 8.3 【以后·必需】云端 V1 替身验证（24G 卡，第一次真跑）

| 项 | 体积 | 来源 / 说明 |
|---|---|---|
| Qwen3-VL-8B-Instruct（bf16） | ≈16–17 GB | [HF `Qwen/Qwen3-VL-8B-Instruct`](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)，24G 单卡放得下 + 8K 上下文 |
| vLLM（Linux，cu12x） | ~1 GB | `pip install vllm`；开 `--enable-prefix-caching` |
| 或 llama.cpp + GGUF | ~9 GB（Q8）+ mmproj | 需 `Qwen3-VL-8B-Instruct-GGUF` 的 `mmproj-*.gguf` 视觉投射器 |

选 8B 的理由：它是**同架构的稠密多模态 + 原生 function calling**，24G 能 bf16 直跑（不需要量化），可以先把"契约 + 缓存 + 工具 + 视觉"四件事在真实模型上验完，再去碰 27B。

### 8.4 【以后·目标】云端 V2 —— 27B

| 项 | 体积 | 说明 |
|---|---|---|
| **Qwen3.8-27B 权重** | bf16 ≈54 GB | ← **需要你先确认这个模型现在是否可获得**（见 §13-2） |
| AWQ-4bit 量化版 | ≈15–16 GB | 可自行量化：`llm-compressor` 或 `autoawq`；**视觉塔保 fp16** |
| 显存 | ≥24G（4090/A5000），40G 更稳 | 262K 原生上下文实际用不到，按 16–32K 开 |

### 8.5 明确**不需要**下载

- ❌ Ollama / LM Studio / 任何桌面推理客户端
- ❌ 任何云端 API key（DeepSeek / 阿里云 / Gemini 都不用）
- ❌ δ-mem 相关权重或代码（本期不做，C1）
- ❌ 训练框架（torch 已在 `runtime/311`，但 V0 不用）
- ❌ 新建 Python 环境

### 8.6 需要补的 `.gitignore` 两条（落地时加，本方案不改文件）

```gitignore
.vendor/.MeowLLM/state/
.vendor/.MeowLLM/logs/
```

（`*.gguf` / `*.safetensors` / `.venv/` / `site-packages/` 已在现有 `.gitignore` 第 114–120、102–108 行覆盖）

---

## 9. 显存与量化（云端参考，本机不适用）

### 9.1 27B 稠密多模态

| 量化 | 权重 | +视觉编码器 | +KV（32K, q8） | 结论 |
|---|---|---|---|---|
| bf16 | ~54 GB | 1–2 GB | 4 GB | 需 H100 80G 或 2×A100 |
| Q8_0 | ~29 GB | 1–2 GB | 4 GB | 需 40–48 GB |
| Q6_K | ~22 GB | 1–2 GB | 4 GB | A100 40G 可 |
| Q5_K_M | ~19 GB | 1–2 GB | 4 GB | 24G 紧张 |
| **Q4_K_M / AWQ-4bit** | **~16 GB** | 1–2 GB | 4 GB | **24G 可行（云端推荐）** |

KV 估算公式（架构确定后代入真实参数）：
`每 token 字节 = 2(K,V) × n_layers × n_kv_heads × head_dim × bytes_per_elem`
例：64 层 / 8 KV 头 / head_dim 128 / fp16 → 256 KiB/token → 32K ≈ 8 GiB；`q8_0` 减半。

### 9.2 本机实测（硬事实）

```
GPU  : NVIDIA GeForce RTX 5060 Laptop GPU, 8151 MiB
torch: 2.11.0+cu128, CUDA available = True
装好 : torch transformers accelerate sentencepiece pillow numpy openai fastapi uvicorn pynvml PyYAML httpx
未装 : vllm llama_cpp bitsandbytes autoawq auto_gptq outlines xgrammar optimum
```

→ 8GB 装不下 27B 的任何量化（最小 16GB）。按 C4，**本机连 0.6B 都不起**，只用 stub。
本地/云端的唯一差异就是 `meowllm.model.path` + `meowllm.engine.kind` 两个字段。

---

## 10. 接入原项目（本期不实施，只给路径）

### 10.1 方案 B —— 零改动（PoC 用，推荐先做）

只改 `config.yml`，不动代码：

```yaml
llm:
  local_llm_type: deepseek          # 类型保持 deepseek，走同一套 port 实现
  deepseek:
    api_key: "meowllm"              # 不校验，非空即可
    base_url: "http://127.0.0.1:18100/meowllm/v1"
    model: "meowllm-local"
    max_tokens: 256
    temperature: 1.1
    top_p: 0.9
    enable_thinking: true
```

**可行性依赖**：MeowLLM 必须按 §5.6.4 映射/忽略现有 port 塞的 `extra_body` 字段。
做到就能在几分钟内拿到"项目真实调用 MeowLLM"的完整数据。

**局限**：只能整体切换、不能按模块灰度；族 3 的 `thinking_level` 分档语义会退化（靠 §5.6.4 的 `reasoning_effort`/`thinking.type` 反推补偿）。

### 10.2 方案 A —— 新增本地 port（灰度正式方案）

按 §2.2 逐族新增 5 个文件，类名按 §4.4：

```
func/llm/port/meowllm.py                        class MeowLLM
func/llm_active/port/meowllm.py                 class AutoMeowLLM
func/toolbox/port/meowllm.py                    class TBoxMeowLLM
func/toolbox/meowvision/port/meowllm.py         class TBVisionMeowLLM
func/llm_active/origin/vision/port/meowllm.py   class AutoVisionMeowLLM
```

写法照 `func/toolbox/flux_painter/port/base.py`（基类 + 工厂，最规范）。

**4 个硬约束**（§1.4）：① 有可判真的 `client`；② 严格 `index/id/name/arguments` 分片；③ 两种 `reasoning_content` 都要给；④ 各族参数顺序按各自签名。

**选择点**：25+ 处内联三分支各加一个 `elif cfg.llm_type == "meowllm":`；顺带收敛成 `create_toolbox_llm(cfg)` 工厂。

**灰度顺序**（风险从低到高）：

| 阶段 | 切谁 | 观察 |
|---|---|---|
| G1 | 天气 + 新闻（离线可回放） | 播报可用率、decode TPS |
| G2 | 唱歌（歌名/区间参数正确性） | 工具参数准确率 |
| G3 | 视觉 | 图像 token 成本、描述可用率 |
| G4 | 主动回复 `llm_active` | 话题相关性、幻觉率 |
| G5 | napcat（QQ） | 回复 p95、工具选择准确率 |
| G6 | 主对话 `llm` | 首字延迟、TTS 连贯性、情绪工具必叫率 |

每级回滚 = 改回 `deepseek`。

---

## 11. 验收与埋点

### 11.1 `/meowllm/control/stats` 必须暴露

| 指标 | 为什么 |
|---|---|
| `ttfb_p50/p95` | 语音链路能不能用，只看这个 |
| `prefill_tps` / `decode_tps` | 引擎调优依据 |
| `cache_hit_rate`（分 L2/L3/L4） | 证明前缀缓存真的生效 |
| `vram_used` / `kv_used` | 防 OOM |
| `queue_depth` / `timeout_count` | 并发是否够 |
| `tool_call_accuracy` | 本地模型最大风险点 |
| `empty_content_rate` | 思考吃光 token 的告警 |

### 11.2 门禁

| 门 | 级别 | 指标 | 通过线 |
|---|---|---|---|
| **M0 契约** | V0 本机 | `meowllm_selftest` 12 项 + `meowllm_project_probe` | **全绿** |
| **M1 安全** | 任意 | 非 stub 引擎在 >1B 时拒绝启动 | 100% 拦住 |
| **M2 缓存** | V1 云端 | 主对话第 2 轮起 L2/L4 命中 | `cache_hit_rate ≥ 0.7` |
| **M3 延迟** | V1 云端 | 主对话 TTFB p95 | ≤ 1.0 s |
| **M4 工具** | V1 云端 | 情绪工具每轮必调 / 父级工具选择准确率 | 100% / ≥ 90% |
| **M5 视觉** | V1 云端 | 单图 token ≤ 1200 / 描述可用率 | 达标 / ≥ 85% |
| **M6 回滚** | 任意 | 改一个配置键切回云端 | 5 分钟内可回滚 |

---

## 12. 风险

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| 1 | 本机 8GB + C4 禁跑模型 → 本机**永远测不到真实模型行为** | V0 只能证明契约，不能证明"好不好用" | 严格三级验证（§7.1）；V0 只当门禁，不当效果结论 |
| 2 | **Qwen3.8-27B 权重可获得性未确认** | V2 卡住 | V1 用 Qwen3-VL-8B 同架构替身跑完所有机制；`model.path` 单点切换 |
| 3 | **提示词头部易变（情绪/时间）打碎前缀缓存** | 缓存命中≈0，大模型延迟不可接受 | §5.9.3 分区改造（原项目改动，需另立小方案） |
| 4 | 工具 schema 过大（3–6k token） | 本地模型选错工具/漏参数 | 工具子集化 + 语法约束 + M4 门禁 |
| 5 | 27B 稠密 decode 慢（25–35 tok/s） | QQ 整段缓冲 6–8 s | QQ 保留云端或强制短回复；语音走首句流式 |
| 6 | Windows 上 vLLM 不可用 | 无连续批处理 | 云端 Linux 跑 vLLM |
| 7 | stub 通过 ≠ 真模型通过 | 契约对但质量差 | 明确 M0/M2 是两类门；别用 stub 结果下效果结论 |
| 8 | `.vendor` 写权限（本会话实测 shell 写入被拒；`write` 工具可写） | 落地建目录/装东西可能受阻 | 落地前确认 `.vendor` 可写 |
| 9 | 命名漂移（后面有人又加个 `local_llm.py`） | C3 失效 | 把 §4.5 禁用名清单写进 `.vendor/.MeowLLM/README.md` + 代码 review checklist |

---

## 13. 待你确认

1. **端口 18100** 确认？回退 18101–18108 可接受吗？
2. **Qwen3.8-27B 现在是否可获得？**（HF/ModelScope 上有无公开权重）—— 这决定 V2 什么时候能开始，也决定 §8.4 的下载是否现实。如果没有，我建议 V2 先用 **Qwen3-VL-32B-Instruct**（同系列稠密，AWQ 后 ≈18GB）做替身。
3. **MIRROR 本期做**（纯 prompt，`mirror.enabled` 默认 false 先跑通纯推理）—— 这个节奏对吗？
4. **提示词分区改造**（§5.9.3）是否现在立方案？不做的话前缀缓存收益大打折扣。
5. **云端机型**：24G（4090/A5000）还是 40G/80G？决定 `n_ctx` 与量化档位。
6. 要不要我现在只落地 **V0 那一层**（`meowllm.yml` + `meowllm_engine_stub.py` + `/meowllm/v1/chat/completions` + `meowllm_selftest.py`），让你先在本机把"项目 ↔ MeowLLM"契约跑通？这一层零下载、零权重、当天可验。
