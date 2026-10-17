#!/usr/bin/env bash
echo "=DNS="
getent hosts huggingface.co || echo "dns_fail"

echo "=CURL_HF="
curl -sS -m 8 -o /dev/null -w "%{http_code}\n" https://huggingface.co/api/models/Qwen/Qwen3-8B 2>&1 | tail -2

echo "=CURL_MIRROR="
curl -sS -m 8 -o /dev/null -w "%{http_code}\n" https://hf-mirror.com/api/models/Qwen/Qwen3-8B 2>&1 | tail -2

echo "=TURBO_FILE="
ls -l /etc/network_turbo 2>/dev/null && cat /etc/network_turbo || echo "no /etc/network_turbo"

echo "=AFTER_TURBO="
( . /etc/network_turbo 2>/dev/null && env | grep -i proxy ; curl -sS -m 12 -o /dev/null -w "%{http_code}\n" https://huggingface.co/api/models/Qwen/Qwen3-8B 2>&1 | tail -2 )

echo "=PIPCONF="
cat /etc/pip.conf 2>/dev/null || true
cat /root/.pip/pip.conf 2>/dev/null || true
cat /root/.config/pip/pip.conf 2>/dev/null || true
