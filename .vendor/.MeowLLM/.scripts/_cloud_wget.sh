#!/usr/bin/env bash
# 云端直连 hf-mirror 补下第一片（比本机 SFTP 上传快一个数量级）
set -u
D=/root/autodl-tmp/models/Qwen3-8B
URL=https://hf-mirror.com/Qwen/Qwen3-8B/resolve/main/model-00001-of-00005.safetensors

. /etc/network_turbo >/dev/null 2>&1 || true

# 删掉被截断的旧文件与半成品
rm -f "$D/model-00001-of-00005.safetensors" "$D/model-00001-of-00005.safetensors.1" 2>/dev/null

cd "$D" || exit 1
nohup wget -c -q --show-progress -O model-00001-of-00005.safetensors.part "$URL" \
    > /root/autodl-tmp/dl_shard1.log 2>&1 &

echo "STARTED pid=$!"
sleep 8
echo "=PROGRESS="
ls -l "$D"/model-00001-of-00005.safetensors.part 2>/dev/null | awk '{print $5}'
tail -c 300 /root/autodl-tmp/dl_shard1.log 2>/dev/null
