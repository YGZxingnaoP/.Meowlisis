#!/usr/bin/env bash
# 一键起 δ-mem 训练面板（AutoDL / 本地通用）
#
#   bash run_webui.sh                 # 默认 127.0.0.1:6006
#   bash run_webui.sh 7007            # 换端口
#   bash run_webui.sh 6006 0.0.0.0    # 允许外部直连（默认只监听回环，更安全）
#
# AutoDL 上推荐：实例里监听回环，本机用 SSH 隧道
#   ssh -L 6006:127.0.0.1:6006 -p <实例端口> root@<实例地址>
# 然后浏览器打开 http://127.0.0.1:6006
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-6006}"
HOST="${2:-127.0.0.1}"
MODEL="${MODEL:-/root/autodl-tmp/dmem/models/Qwen3-0.6B}"
OUT="${OUT:-out}"

command -v python >/dev/null || { echo "找不到 python"; exit 1; }
python - <<'PY' || { echo "缺依赖：pip install fastapi uvicorn"; exit 1; }
import fastapi, uvicorn  # noqa: F401
PY

mkdir -p "$OUT"
echo "面板： http://${HOST}:${PORT}"
echo "模型： ${MODEL}（面板里可选，留空则用 train_sft 的默认）"
echo "输出： $(cd "$OUT" && pwd)"
export DMEM_MODEL="$MODEL"
exec python webui.py --host "$HOST" --port "$PORT" --out "$OUT"
