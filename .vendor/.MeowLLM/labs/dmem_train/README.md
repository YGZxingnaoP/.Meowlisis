# labs/dmem_train —— δ-mem 训练与云端实验包

训练与推理**分开**：

```
labs/dmem_train/        训练（可整目录搬到云上，只依赖 torch/transformers）
meowllm/dmem/           推理（引擎加载，不依赖训练代码）
```

两边共用同一份 `DeltaMem` 实现（`meowllm/dmem/`）。训练产物是一个
`.safetensors` 权重文件，推理侧按 `config.yml` 的 `memory.delta_mem.weights` 加载。

---

## 0. 路径约定（唯一出处：`cloud_paths.py`）

这套包以前散着 4 个不同的远端根、3 个不同的权重家目录，改一处必错一处。现在
**所有路径都从 `cloud_paths.py` 取**，规则一句话：

```
本地 = 权威，配置里只写相对模块根（.vendor/.MeowLLM/）的路径
云端 = 同一棵树换个根
```

| | 本地 | 云端 |
|---|---|---|
| 模块根 | `D:\.Meowlisis\.vendor\.MeowLLM` | `/root/autodl-tmp/MeowLLM` |
| backbone | `models/Qwen3-0.6B` | `<根>/models/Qwen3-8B` |
| 训练数据 | `labs/dmem_train/data/sft.jsonl` | 同一相对路径 |
| 训练产物 | `labs/dmem_train/out/<run>/` | 同一相对路径 |
| 下载回本地 | `models/<run>/dmem.safetensors` | — |

于是**同一份 `config.yml` 在两边都能直接用**，上云不用改任何路径。
随机器变的只有两样，可用环境变量覆盖：

```powershell
$env:MEOWLLM_REMOTE_ROOT   = "/root/autodl-tmp/MeowLLM"
$env:MEOWLLM_REMOTE_PYTHON = "/root/miniconda3/bin/python3"
```

## 1. 文件

**入口（可直接跑）**

| 文件 | 作用 |
|---|---|
| `webui.py` | 训练面板（FastAPI + 原生 JS，服务端画 SVG 曲线）：起停训练、看 loss/lr/ETA、看数据画像、看留出集 gap |
| `train_sft.py` | 训练主程序（backbone 冻结，只训 δ-mem） |
| `build_data.py` | 数据合成（模板 / 教师模型） |
| `build_from_real.py` | 从真人语料（LoCoMo / PerLTQA）构造样本 |
| `mix.py` | 把多份 jsonl 按配比混成 `sft.jsonl` |
| `cloud.py` | 云端运维 CLI：`check / upsync / setup / sync-model / fetch-data / serve / all / run` |
| `remote.py` | 远端执行层 + 启停 CLI（`start` / `stop` / `status` / `files` / `dataset`） |
| `download_artifacts.py` | 把云端 run 拉回本地 `models/<run>/`（附 `MANIFEST.json`，含 sha1） |

**库**：`cloud_paths.py`（路径唯一出处）、`dataset.py`（编码/切分/画像）

**Windows 一键**：`upload_cloud.bat`（= `cloud.py`）、`start_train_cloud.bat`
（= `remote.py start`）、`start_dashboard_remote.bat`（= `webui.py --remote`）、
`download_artifacts.bat`

**AutoDL 侧脚本**：`setup_autodl.sh`、`run_webui.sh`、`presets/r64.yaml`

## 2. 数据

```bash
python build_data.py --mode template --limit 2000          # 离线，先看管线通不通
python build_data.py --mode llm --limit 20000 --workers 8  # 教师模型合成
python mix.py --out data/sft.jsonl                         # 按配比混合
```

样本一行一条：

```json
{"id":"abmem-000001","event_id":"9f2c...","context":"以下是我记住的事情：...",
 "query":"我之前跟你提过「打上花火」的事吗？","response":"你说国庆前想把混响调好",
 "segments":[23,31,18],"source":"abstract_memory/llm"}
```

- `context` 只进状态，**不进** backbone 输入；
- `event_id` 用于 train/holdout 分组，防止同一事件两边都有；
- `segments` 是段长，留给 SSW（`--chunk`）参考，当前实现按固定 chunk 切。

> ⚠ `data/` 里默认只有一个 `.keep`。云端 launcher 硬要求 `data/sft.jsonl`
> （否则 `NO_DATA`），所以上云前先把数据放到 `labs/dmem_train/data/`
> —— 它会随 `labs/dmem_train` 一起被 `upsync` 上去。

配比建议（目标 1 万条）：单跳 50% / 多跳 20% / 时间 10% / 偏好 10% / **记忆里没有 10%**。

## 3. 本地训练

```bash
# 干跑（2 步，查形状/显存）
python train_sft.py --data data/sft.jsonl --dry-run

# 正式
python train_sft.py --data data/sft.jsonl --preset presets/r64.yaml --out out
```

显存/速度（本机 8G 卡实测，bf16 backbone，batch=1）：

| context | 峰值显存 | 速度 |
|---|---|---|
| 768 | ~3 GiB | 3.2 s/样本 |
| 1024 | ~4 GiB | 4 s/样本 |
| 2048 | ~6 GiB | 7 s/样本 |

## 4. 训练面板

```powershell
..\..\..\..\runtime\311\python.exe webui.py --port 8123
```

- 本地模式：直接读写 `out/<run>/status.json|metrics.jsonl|train.log`
- 远端模式（`--remote`）：同样的文件改成 SFTP 拉；带 2 秒快照缓存（`?fresh=1` 强制刷新）
- `--out` 在远端模式下是**相对 `labs/dmem_train` 的路径**（面板传绝对路径会被
  `cloud_paths.out_rel()` 规整掉 —— 以前这里会把 `D:\...\out` 拼到远端路径里，
  于是面板永远读不到训练目录）
- `--model` 是相对模块根的 backbone 名（默认 `models/Qwen3-8B`）

## 5. 云端

```powershell
python cloud.py check          :: 看卡/盘/Python
python cloud.py upsync         :: 上传训练包（跳过同尺寸文件）
python cloud.py setup          :: pip 依赖 + 在 <根>/models/ 下准备 0.6B
python cloud.py sync-model     :: 或直接把本地模型推上去（比云端下行快）
python cloud.py serve          :: 后台起面板并打印隧道命令
python cloud.py all            :: check + upsync + setup + fetch-data + serve
```

凭据从 `labs/autoDL/` 读（已被 .gitignore 排除）：
`登录指令.txt`（`ssh -p <port> user@host`）+ `密码.txt`。

远端根、远端 python 全部来自 `cloud_paths.py`；`upsync` 上传的是
`labs/dmem_train` + `meowllm/dmem` + `docs/notes` + `config.yml`
（**不含** `models/` —— 1.5GB+，由 `setup` 在云端按同结构准备）。

## 6. 评测与回传

训练结束自动跑留出集：

```
no-context 6.3939   with-state 5.2219   gap 1.1700
```

`gap` = 状态里到底有没有信息。**gap ≈ 0 说明白训了**，去查：

1. 数据里 response 是不是真依赖 context；
2. `chunk` 是不是太大（段被平均糊掉了）；
3. `alpha` 是不是被学成 0（`out/eval.json` 与权重里的 `log_alpha`）。

回传：

```powershell
python download_artifacts.py             :: 最新一次完成的 run
python download_artifacts.py out/run2     :: 指定 run
python download_artifacts.py --dest models/xxx
```

落到 `models/<run>/`：`dmem.safetensors`、`dmem.step.safetensors`、`eval.json`、
`metrics.jsonl`、`status.json`、`train.log`、`MANIFEST.json`；数据落回
`labs/dmem_train/data/`。

## 7. 挂到 MeowLLM

```yaml
memory:
  delta_mem:
    enabled: true
    weights: models/<run>/dmem.safetensors    # 相对 .vendor/.MeowLLM/
```

重启后：

```bash
curl http://127.0.0.1:18100/meowllm/control/dmem/status      # enabled 应为 true
curl -X POST http://127.0.0.1:18100/meowllm/control/dmem/write \
  -H "Content-Type: application/json" \
  -d '{"owner":"000001","text":"...","mode":"replace"}'
```

**权重必须与 backbone 配套**：权重里记着 `hidden_size / q_dim / head_dim / layers`，
和当前 backbone 对不上时引擎会**拒绝挂载**并在 `dmem/status.reason` 里写明原因
（不会拿随机权重硬挂）。现有 `models/dmem-261018` 是给 8B（hidden 4096 / 36 层）
练的，本地 0.6B（hidden 1024 / 28 层）用不了。
