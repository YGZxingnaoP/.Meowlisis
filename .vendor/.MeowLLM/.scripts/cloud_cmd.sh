#!/usr/bin/env bash
echo "=LSPCI_GPU="
lspci 2>/dev/null | grep -i nvidia || echo "no nvidia pci device"

echo "=START_TAIL="
tail -32 /root/autodl-tmp/start_server.sh 2>/dev/null

echo "=MODELS_TREE="
ls -la /root/autodl-tmp/models 2>/dev/null
du -sh /root/autodl-tmp/models/* 2>/dev/null

echo "=BINS_VER="
cd /root/autodl-tmp/llamacpp 2>/dev/null && ./llama-120 --version 2>&1 | head -3

echo "=LOGS="
ls -la /root/autodl-tmp/logs 2>/dev/null | tail -5
