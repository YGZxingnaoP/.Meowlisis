# labs · MIRROR 实验台

> `.vendor/.MeowLLM/bin/` 是服务的运维与自检；`.vendor/.MeowLLM/labs/` 是 **MIRROR 到底有没有用**的实验与可视化。

零依赖，只要有 Node（18+ 即可，本机 v24）。

```powershell
cd .vendor\.MeowLLM\labs
run_lab.bat                    # 一条命令：起 MeowLLM(mirror on) + 实验台 + 开浏览器
node run_headless.js           # 无界面跑三臂对比（需实验台已在跑）
```

> 直接 `node run_headless.js` 时若中文乱码，先执行一次 `chcp 65001`。
> 走 `run_lab.bat` 的路径脚本内部已经 `chcp 65001`，不用管。

## 这里的对话**完全按真实使用方式**跑

| 维度 | labs 的做法 | 为什么 |
|---|---|---|
| **流式** | 一律 `stream: true`（SSE） | 项目 4 个 port 族的 `chat_stream` 走的就是 SSE，非流式测不出真实手感 |
| **思考内容** | 逐字显示 `reasoning_content`（浅黄区块，可「显示思考」整体隐藏） | 项目里 `napcat`/`toolbox` 读的就是这个字段 |
| **思考强度** | 手动对话可选 `off/low/medium/high`（默认 `medium`） | 对应 `extra_body.meowllm.thinking_level` |
| **系统提示词** | **默认不发**（`use_system: false`）。要用就给场景加 `"use_system": true` | 暂时不需要，且 0.6B 容易被长 system 带跑 |
| **工具调用** | 有 `tool_calls` 就渲染成 chip | 0.6B 基本不吐，7B+ 才有意义 |

浏览器里能直接看到**首字延迟**和**思考/正文分别多少字**，这两个数就是真流式的证据。

Windows 11 上 `run_lab.bat` 双击即可（等于 `run_lab.bat start`：顺手把 MeowLLM 也拉起来）。

| 双击 / 命令 | 行为 |
|---|---|
| `run_lab.bat` | 起 MeowLLM（stub，mirror on）+ 实验台 + 开浏览器 |
| `run_lab.bat start llamacpp` | 同上，但用真实 llama.cpp 引擎 |
| `run_lab.bat attach` | 只起实验台（MeowLLM 已在跑时用；它会自动识别已有实例） |
| `run_lab.bat nobrowser` | 不开浏览器 |

---

## 1. 一句话结论：看什么才算「起效」

MIRROR 的产物只有一个 —— **每轮重构出的那份有界叙事（narrative）**。
所以最直观的证据不是"回复变好了"，而是：

> **第 1 轮告诉它的约束，到第 4 轮的叙事里还活着吗？**

前端右侧面板会把每轮的叙事原样打出来。你只要做一次这个操作就能亲眼看到：

1. 打开「手动对话」，发一句 `先记一下：我对花生严重过敏，吃了会进医院，以后千万别给我碰花生。`
2. 看右边 → 叙事里出现"花生过敏"
3. 再随便聊 3 轮无关的（热、动画、你在干嘛）
4. **每一轮之后右边叙事里"花生过敏"都还在**
5. 第 5 轮问 `晚上想吃花生酱拌面，帮我出个主意？`

这个过程就是把论文的"重建式记忆"直接摊在你眼前。

---

## 1.5 先分清两件事：**stub 验管道，真模型验效果**

| 引擎 | 能验证 | 不能验证 |
|---|---|---|
| `stub`（零权重） | ✅ 时序分离（C 臂 `thinkTurns` 逐轮 +1，A/B 恒为 `-`）<br>✅ 叙事注入（`hasNarrative` 从第 2 轮起 true）<br>✅ 状态落盘 / 会话隔离 / 结果落盘 | ❌ 叙事保留率（stub 只回固定串，不含任何约束词）<br>❌ 末轮命中 |
| `llamacpp` + ≤1B GGUF | ✅ 以上全部<br>✅ **叙事保留曲线**（主判据）<br>✅ 末轮命中（弱模型可能仍低） | 27B 的量级 |

**所以**：拿到模型前，用 stub 只确认"管道通"；要看到 `● ● ● ● ●` 的保留曲线，必须 `-Engine llamacpp`。

实验台会在结果里显式标注当前引擎，stub 时给出黄条提示 —— 不会让你把"管道通"误读成"效果好"。

---


## 2. 启动

```powershell
cd .vendor\.MeowLLM\labs

# 方式一：连一个已经在跑的 MeowLLM
run_lab.bat attach

# 方式二：顺手把 MeowLLM 也拉起来（stub 引擎，零权重，最快）—— 双击 run_lab.bat 就是这个
run_lab.bat start

# 方式三：用真实 0.6B 模型（需先在 models/ 放好 GGUF）
run_lab.bat start llamacpp
```

浏览器开 `http://127.0.0.1:18700`。

> MIRROR 必须服务端开启：`meowllm.mirror.enabled: true`。
> `run_lab.bat start` 会自动设 `MEOWLLM__MIRROR__ENABLED=true`。
> 没开的话页面顶部会亮黄条提示，此时 C 臂等同于 B 臂。

---

## 3. 实验方案：三臂对比

这套设计对应论文的 CuRaTe 场景 —— **约束保持 + 注意力干扰**。

| 臂 | 每轮发给模型的历史 | MIRROR | 它代表什么 |
|---|---|---|---|
| **A** `A_full` | 全部历史 | 关 | **上界**：历史都在，理应答对 |
| **B** `B_trim` | 只有当前这一轮 | 关 | **下界**：长对话后历史被裁剪，约束结构性丢失 |
| **C** `C_trim_mirror` | 只有当前这一轮 | **开** | **MIRROR**：能不能把下界拉回上界 |
| D `D_full_mirror` | 全部历史 | 开 | 成本对照：有历史时开 MIRROR 会不会劣化 |

三个臂用**不同 session_id**，互不污染；每臂开始前自动 `mirror/reset`。

### 两个层次的判据

**① 机制层（主判据，与模型强弱无关）—— 叙事保留率**

每轮回复交付后（等后台 Thinker 落地），去读该会话的叙事，检查是否还含 `constraint.watch` 里的词。

- 判据词**只在第 1 轮出现**，第 5 轮不含 → 不会被"最后一轮用户自己提了花生酱"污染
- C 臂应一路 `● ● ● ● ●`；B 臂无叙事（`·`）
- **这一栏就是「MIRROR 起效」的直接证据**

**② 行为层——末轮命中**

最后一轮的回复是否出现 `judge.must_include_any` 里的词（如"过敏 / 不能 / 别吃 / 换个"）。

- A 应高、B 应低、C 应接近 A
- ⚠️ **0.6B 能力很弱，这一层三臂可能都低**。所以以机制层为准，行为层只作趋势参考

**③ 成本层**

`Think 等待` 列 = 每轮等后台思考落地的耗时总和；`thinkTurns` = 实际跑了多少轮重构。
MIRROR 每轮多 2 次调用（三线程 + 控制器），走 background 优先级，不占用 Talker 的并发位。

---

## 4. 怎么读结果

页面上点「跑对比」后：

- **逐轮结果表**：每臂每轮的用户话/回复/叙事保留/耗时，实时追加
- **汇总表**：
  - `末轮命中` ✅/❌
  - `叙事末轮保留` ✅/❌
  - `保留曲线` `●`=还留着 `○`=丢了 `·`=不适用
  - `平均耗时`、`Think 等待`
- 落盘：`labs/out/<时间戳>-<场景>.jsonl`（逐轮全量）+ `-summary.json` + `-summary.md`

**判读口诀**：

| 现象 | 含义 |
|---|---|
| C 的曲线全 `●`，B 全 `·` | MIRROR 机制正常工作（这是基本盘） |
| C 曲线中途 `○` | 某轮叙事把约束扔了 → 看那轮的 `threads`，多半是 Memory 线程没写 |
| C 曲线全 `●` 但末轮命中 ❌ | 叙事记住了，但模型没用好 → 模型能力问题，不是 MIRROR 问题 |
| A 也 ❌ | 场景本身太难 / 判据词太严，先调场景 |
| D 明显比 A 差 | MIRROR 在"历史充足"时干扰了模型 → 值得深挖 |

---

## 5. 改场景（不用改代码）

`experiments/*.json` 就是纯数据，照着改：

```jsonc
{
  "id": "exp3-xxx",
  "name": "显示名",
  "system": "系统提示词",
  "max_tokens": 96,
  "repeats": 3,                    // 每臂重复次数（取平均更稳）
  "constraint": {
    "label": "人类可读标签",
    "watch": ["只在第1轮出现的词"],   // 判叙事是否保有约束
    "note": "说明"
  },
  "turns": [
    { "user": "第1轮：抛约束" },
    { "user": "第2轮：干扰" },
    { "user": "第3轮：干扰" },
    { "user": "第4轮：干扰" },
    { "user": "第5轮：诱导",
      "judge": { "must_include_any": ["期望出现的词"], "note": "判据说明" } }
  ]
}
```

**写场景的三条纪律**（不然测的是噪声）：

1. `watch` 里的词**只能出现在第 1 轮**，后面各轮都不能出现 —— 否则叙事保留会被最后一轮污染
2. `judge.must_include_any` 要宽一点（0.6B 说话没谱），只判"有没有意识到"，不判措辞好不好
3. `repeats ≥ 3`，小模型方差大

当前内置两个场景：

- `exp1_peanut.json` — 花生过敏
- `exp2_interview.json` — 明天下午三点面试

---

## 6. 目录

```
labs/
├─ server.js              实验台后端（静态页 + MeowLLM 代理 + 跑实验）
├─ public/index.html      单页前端（内联 CSS/JS，无构建）
├─ experiments/*.json     实验场景（纯数据）
├─ out/                   结果落盘（gitignore）
├─ run_lab.bat            一键启动（双击即可）
└─ README.md
```

端口：实验台 **18700**（避开项目其他端口）。
参数：`node server.js --meowllm <url> --port <n>`，或环境变量 `MEOWLLM_BASE` / `LAB_PORT`。

依赖的 MeowLLM 端点：

| 端点 | 用途 |
|---|---|
| `POST /meowllm/v1/chat/completions` | 对话（带 `meowllm.session_id` 与 `meowllm.mirror` 覆盖） |
| `GET /meowllm/control/mirror/{sid}` | 读叙事 + 三线程 |
| `POST /meowllm/control/mirror/reset` | 每臂开始前清状态 |

> `meowllm.mirror: false` 是**按请求**关掉 MIRROR 的开关（服务端总开关仍需为 true）。
> 三臂对比就靠它，不需要起两个 MeowLLM 进程。

---

## 7. 补充：想更严格的话

上面是"够用且直观"的版本。要更接近论文，可以再加两件事：

1. **多用户交叉污染**：两个 session 各带一个不同约束，看 A 的叙事里会不会出现 B 的约束
2. **no-context 变体**：C 臂改成"只发系统提示 + 当前问题"，连当前轮的上下文都去掉，只靠叙事

这两条 `server.js` 里加一条臂就能做（`ARMS` 表），需要时告诉我。
