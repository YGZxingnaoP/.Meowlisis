#!/usr/bin/env bash
echo "=GPU_SMI="
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>&1 | head -3
echo "=DEV="
ls /dev/nvidia* 2>/dev/null | head -3 || echo none
echo "=PY="
/root/miniconda3/bin/python -V 2>&1
echo "=TORCH="
/root/miniconda3/bin/python - <<'PY' 2>&1 | tail -8
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "avail", torch.cuda.is_available())
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    free, total = torch.cuda.mem_get_info()
    print("name", p.name, "vram %.1fGB free %.1fGB cap %s" % (total/1e9, free/1e9, p.major))
try:
    import transformers; print("transformers", transformers.__version__)
except Exception as e:
    print("transformers MISSING", e)
PY
echo "=SHARD_SIZES="
ls -l /root/autodl-tmp/models/Qwen3-8B/ 2>/dev/null | awk '{print $5, $9}' | tail -14
echo "=INDEX_TOTAL="
grep -o '"total_size":[0-9]*' /root/autodl-tmp/models/Qwen3-8B/model.safetensors.index.json 2>/dev/null
echo "=DISK="
df -h / /root/autodl-tmp | tail -3
echo "=PROCS="
ps -ef > /tmp/p.txt; grep -cE "python|llama" /tmp/p.txt
