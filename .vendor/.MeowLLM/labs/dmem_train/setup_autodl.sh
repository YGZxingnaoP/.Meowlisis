#!/usr/bin/env bash
# 在 AutoDL 上准备 δ-mem 训练环境（RTX 5090 / 32G，镜像 PyTorch 2.8.0 + cu128）
#
# 用法（在 AutoDL 终端里，数据盘根目录）：
#   bash setup_autodl.sh
#
# 说明
# ----
# * AutoDL 的系统盘只有 30G，模型权重和数据都必须放 /root/autodl-tmp（数据盘）。
# * 镜像自带 torch 2.8.0+cu128，够跑（本项目本机用 2.11 也验证过）。
# * 不要 pip install transformers 的最新版：双流引擎对 5.x 的注意力派发表有依赖，
#   实测 5.3.0 可用；4.5x 也可（compat.py 里有自检）。
set -euo pipefail

WORK=/root/autodl-tmp/dmem
mkdir -p "$WORK"/{models,data,out}

echo "== 1/4 检查 torch =="
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.version.cuda, torch.cuda.is_available())"

echo "== 2/4 安装依赖 =="
pip install -q "transformers==5.3.0" safetensors pyyaml openai fastapi uvicorn
python -c "import transformers; print('transformers', transformers.__version__)"

echo "== 3/4 拉模型（AutoDL 学术加速，HuggingFace 走镜像更快） =="
source /etc/network_turbo 2>/dev/null || true
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
python - <<'PY'
import os
from huggingface_hub import snapshot_download
local = os.environ.get("MODEL_DIR", "/root/autodl-tmp/dmem/models/Qwen3-0.6B")
snapshot_download(repo_id="Qwen/Qwen3-0.6B", local_dir=local,
                  allow_patterns=["*.json", "*.safetensors", "*.txt"])
print("模型就绪：", local)
PY

echo "== 4/4 提示 =="
cat <<'EOF'
接下来：
  1. 把整个 .vendor/.MeowLLM 目录传上来（含 meowllm/dmem 与 labs/dmem_train）
     建议：rsync -avz .vendor/.MeowLLM/ root@<autodl-host>:/root/autodl-tmp/MeowLLM/
  2. 生成数据（详见 docs/notes/2026-10-19_delta-mem数据来源清单.md）
     cd /root/autodl-tmp/MeowLLM/labs/dmem_train
     python build_data.py --mode llm --limit 20000 --workers 8 \
            --abmem /root/autodl-tmp/MeowLLM/character/abstract_memory
  3. 起可视化面板（推荐：启动/停止/曲线/日志都在浏览器里点）
     bash run_webui.sh
     # 在**你本机**（不是实例里）建隧道：
     #   ssh -L 6006:127.0.0.1:6006 -p <实例端口> root@<实例地址>
     # 浏览器打开 http://127.0.0.1:6006
  4. 或直接命令行训：
     python train_sft.py --data data/sft.jsonl \
            --model /root/autodl-tmp/dmem/models/Qwen3-0.6B \
            --preset presets/r64.yaml --out out
  5. 拉回权重：out/dmem.safetensors -> .vendor/.MeowLLM/labs/dmem_train/out/
EOF
