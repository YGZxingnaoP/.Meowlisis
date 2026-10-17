#!/usr/bin/env bash
D=/root/autodl-tmp/models/Qwen3-8B
A=$(du -sb "$D" 2>/dev/null | cut -f1)
sleep 12
B=$(du -sb "$D" 2>/dev/null | cut -f1)
echo "T0_BYTES=$A"
echo "T1_BYTES=$B"
if [ -n "$A" ] && [ -n "$B" ]; then
  echo "DELTA=$((B-A)) bytes / 12s  =>  $(( (B-A)/12/1024 )) KB/s"
fi
echo "=PART="
ls -la "$D"/*.part 2>/dev/null | tail -4
echo "=FINISHED_SHARDS="
ls "$D"/*.safetensors 2>/dev/null | wc -l
echo "=FREE="
df -h /root/autodl-tmp | tail -1
