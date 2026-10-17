#!/usr/bin/env bash
set -u
echo "=ACCELERATE="
/root/miniconda3/bin/python -m pip install --no-cache-dir accelerate 2>&1 | tail -3
/root/miniconda3/bin/python -c "import accelerate; print('accelerate', accelerate.__version__)" 2>&1

echo "=SHARD_SIZE="
ls -l /root/autodl-tmp/models/Qwen3-8B/model-00001-of-00005.safetensors 2>/dev/null | awk '{print $5}'

echo "=DISK="
df -h /root/autodl-tmp | tail -1
