#!/usr/bin/env bash
# 从已上传的轮子安装 transformers，并验证能 import
set -u
echo "=INSTALL="
/root/miniconda3/bin/python -m pip install --no-cache-dir \
    /root/autodl-tmp/transformers-5.3.0-py3-none-any.whl 2>&1 | tail -12

echo "=VERIFY="
/root/miniconda3/bin/python - <<'PY'
try:
    import transformers
    print("transformers", transformers.__version__)
except Exception as e:
    print("IMPORT FAIL", type(e).__name__, e)
    raise SystemExit(1)
try:
    import accelerate
    print("accelerate", accelerate.__version__)
except Exception as e:
    print("accelerate MISSING:", e)
PY
