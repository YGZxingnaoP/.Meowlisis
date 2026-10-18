# -*- coding: utf-8 -*-
"""实测：主项目真实提示词（uid=000001）→ 云端 8B 双流。

只读：提示词用 labs/build_prompt.py 构建（ShortMemory 写入口已打桩），
短期记忆文件 sha1 前后一致才继续。
"""

from __future__ import annotations

import json
import os
import sys

PROJ = r"D:\.Meowlisis"
MODULE = os.path.join(PROJ, ".vendor", ".MeowLLM")
sys.path.insert(0, os.path.join(MODULE, "labs"))
sys.path.insert(0, os.path.join(MODULE, "labs", "dmem_train"))

import build_prompt  # noqa: E402
import cloud  # noqa: E402
import cloud_paths  # noqa: E402

CASES = [("写个 300 字的小故事，讲一只猫在雨天出门，分三段，每段之间空一行", 700)]
RUNNER = r"""
import json, sys, urllib.request
body = json.load(open("__REQ__", encoding="utf-8"))
req = urllib.request.Request("http://127.0.0.1:18100/meowllm/v1/chat/completions",
    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=900) as resp:
    data = json.loads(resp.read().decode("utf-8"))
meta = data.get("meowllm") or {}
msg = data["choices"][0]["message"]
text = (msg.get("content") or "").strip()
print("CONTENT", text)
print("REASON", (msg.get("reasoning_content") or "")[:100].replace("\n", " "))
keys = ("steps","thinker_tokens","thinker_stop","writer_tokens","probes","probe_yes",
        "probe_no","last_p_yes","last_p_no","pauses","pause_paragraph","resumes")
print("SUMMARY", json.dumps({"finish": data["choices"][0].get("finish_reason"),
      "chars": len(text), "blanklines": text.count("\n\n"),
      **{k: meta.get(k) for k in keys}}, ensure_ascii=False))
"""

root = cloud_paths.remote_root()
cl = cloud.Cloud(quiet=True)
try:
    with cl.sftp.open(f"{root}/.post_runner.py", "w") as fh:
        fh.write(RUNNER)
    for text, max_tokens in CASES:
        built = build_prompt.build("000001", text, 20)
        if not built["memory_unchanged"]:
            print("!! 短期记忆被抓改，停止", flush=True)
            break
        body = {"model": "meowllm-local", "stream": False, "max_tokens": max_tokens,
                "temperature": 0.7, "meowllm": {"thinking_level": "low"},
                "messages": built["messages"]}
        with cl.sftp.open(f"{root}/.req.json", "w") as fh:
            fh.write(json.dumps(body, ensure_ascii=False))
        print(f"\n=== 「{text[:18]}」 system {built['system_chars']} 字 / "
              f"历史 {built['history_rounds']} 条 / max_tokens {max_tokens} "
              f"/ 记忆未变 {built['memory_unchanged']} ===", flush=True)
        code, out = cl.run(f"cd {root} && sed -i 's|__REQ__|.req.json|' .post_runner.py; "
                           f"/root/miniconda3/bin/python3 .post_runner.py 2>&1 | tail -6",
                           timeout=1800)
        print(out, flush=True)
finally:
    cl.close()
