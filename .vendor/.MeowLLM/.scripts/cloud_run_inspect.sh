#!/usr/bin/env bash
# 在云端用纯标准库解析两个 GGUF 文件（不需要 GPU、不加载模型）
set -u
PY=/root/miniconda3/bin/python
DIR=/root/autodl-tmp/models/Qwen3.8-27B-GGUF

echo "### 文件清单"
ls -l "$DIR"

echo ""
echo "### 解析权重"
$PY /root/autodl-tmp/gguf_inspect.py \
    "$DIR/Qwen3.8-27B-UD-Q6_K.gguf" \
    "$DIR/mmproj-F16.gguf"
