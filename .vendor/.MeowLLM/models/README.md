# models/ —— 本模块的权重目录（本地与云端同一套结构）

```
models/
├── Qwen3-0.6B/            backbone（本机跑管道用）
├── Qwen3-8B/              backbone（云端训练用；本地没有）
└── <run>/                 δ-mem 训练产物，一个 run 一个目录
    ├── dmem.safetensors        ← config.yml 的 memory.delta_mem.weights 指这里
    ├── dmem.step.safetensors
    ├── eval.json  metrics.jsonl  status.json  train.log
    └── MANIFEST.json           ← download_artifacts.py 生成（含每个文件的 sha1）
```

## 为什么要有这个约定

`config.yml` 里所有路径都写**相对 `.vendor/.MeowLLM/`**：

```yaml
engine:
  dualstream:
    model_dir: models/Qwen3-0.6B
memory:
  delta_mem:
    weights: models/<run>/dmem.safetensors
```

因为云端就是把这一整棵树换个根（`/root/autodl-tmp/MeowLLM`），
所以**同一份 config.yml 在本地和云端都能直接跑**，不需要"到了云端再改路径"。
转换只发生在 `labs/dmem_train/cloud_paths.py` 一处。

## 不要做的事

* 不要把权重放进 `docs/output/`、`labs/dmem_train/out/` 或 `.dmem_work/`
  —— 那会把"权重在哪"变成三个互相矛盾的答案（这正是之前出过的坑）。
* 不要把 `models/` 用 `cloud.py upsync` 传上去：通常 1.5 GB+。
  云端用 `python cloud.py setup`（下 0.6B）或 `python cloud.py sync-model`（推本地已有的）。
* 换权重后旧状态会被拒绝加载：每个用户的状态里记着 `weights_sha1` 与
  `cfg_fingerprint`（rank / N / chunk / 层号），对不上就不读 —— 这是故意的。

## 现有内容

| 目录 | 是什么 | 能用吗 |
|---|---|---|
| `Qwen3-0.6B/` | Qwen3-0.6B 原始权重（hidden 1024 / 28 层） | ✅ 本机 backbone |
| `dmem-261018/` | δ-mem 训练产物（hidden 4096 / q_dim 4096 / 36 层，α≈15.97，gap 4.6603） | ⚠ 只配 **Qwen3-8B**；本地 0.6B 会被引擎拒绝挂载 |

本地要真正跑起来 δ-mem，需要针对 `models/Qwen3-0.6B` 重新训一份
（`labs/dmem_train/train_sft.py --model models/Qwen3-0.6B`），产物放
`models/<新run>/` 后改 `config.yml` 的 `weights`。
