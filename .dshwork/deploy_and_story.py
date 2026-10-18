# -*- coding: utf-8 -*-
"""一体化：传 config → 重启 → 立刻探活（不等固定时长） → 跑一条故事请求。

要点（针对"空等"）：
  * 探活用 0.8s 间隔，**一拿到 200 立刻继续**，最长 90s；
  * 不再 sleep 45s 之类；每个阶段打印耗时。
"""

from __future__ import annotations

import json
import os
import sys
import time

MODULE = r"D:\.Meowlisis\.vendor\.MeowLLM"
sys.path.insert(0, os.path.join(MODULE, "labs"))
sys.path.insert(0, os.path.join(MODULE, "labs", "dmem_train"))

import build_prompt  # noqa: E402
import cloud  # noqa: E402
import cloud_paths  # noqa: E402

PROMPT = "写个 300 字的小故事，讲一只猫在雨天出门，分三段，每段之间空一行"
root = cloud_paths.remote_root()
t0 = time.time()
cl = cloud.Cloud(quiet=True)
try:
    # 1) 强制回传 config（_same 已改成 大小+时间）
    local_cfg = os.path.join(MODULE, "config.yml")
    cl.put_file(local_cfg, f"{root}/config.yml")
    print(f"[{time.time()-t0:5.1f}s] config.yml 已上传", flush=True)
    code, out = cl.run(f"grep -E 'stall_guard|dual_max' {root}/config.yml", show=False)
    print("[cfg]", out.replace("\n", " | "), flush=True)

    # 2) 重启
    cl.run("pkill -f '[m]eowllm.server.app' ; sleep 1 ; echo killed", timeout=30)
    chan = cl.client.get_transport().open_session()
    try:
        chan.exec_command(f"cd {root} && setsid nohup bash serve.sh "
                          "> /root/autodl-tmp/meowllm_server.log 2>&1 < /dev/null &")
        time.sleep(0.5)
    finally:
        chan.close()
    print(f"[{time.time()-t0:5.1f}s] 已发启动", flush=True)

    # 3) 立刻轮询（0.8s 一次，拿到 200 就走）
    ready = False
    while time.time() - t0 < 90:
        code = cl.run("curl -s -o /dev/null -w '%{http_code}' "
                      "http://127.0.0.1:18100/meowllm/control/health",
                      show=False)[1].strip()
        if code == "200":
            ready = True
            break
        time.sleep(0.8)
    print(f"[{time.time()-t0:5.1f}s] 健康={ready}", flush=True)
    if not ready:
        print(cl.run("tail -5 /root/autodl-tmp/meowllm_server.log", show=False)[1])
        raise SystemExit(1)

    # 4) 一条故事请求
    built = build_prompt.build("000001", PROMPT, 20)
    if not built["memory_unchanged"]:
        print("!! 短期记忆被改动，停止", flush=True)
        raise SystemExit(1)
    body = {"model": "meowllm-local", "stream": False, "max_tokens": 700,
            "temperature": 0.7, "meowllm": {"thinking_level": "low"},
            "messages": built["messages"]}
    with cl.sftp.open(f"{root}/.req.json", "w") as fh:
        fh.write(json.dumps(body, ensure_ascii=False))
    runner = (
        "import json,urllib.request\n"
        "body=json.load(open('.req.json',encoding='utf-8'))\n"
        "req=urllib.request.Request('http://127.0.0.1:18100/meowllm/v1/chat/completions',"
        "data=json.dumps(body,ensure_ascii=False).encode(),"
        "headers={'Content-Type':'application/json'})\n"
        "d=json.loads(urllib.request.urlopen(req,timeout=900).read().decode())\n"
        "m=d.get('meowllm') or {}\n"
        "t=(d['choices'][0]['message'].get('content') or '').strip()\n"
        "print('SUMMARY', json.dumps({'finish':d['choices'][0].get('finish_reason'),"
        "'chars':len(t),'blank':t.count('\\n\\n'),"
        "'steps':m.get('steps'),'think':m.get('thinker_tokens'),"
        "'write':m.get('writer_tokens'),'probes':m.get('probes'),"
        "'no':m.get('probe_no'),'py':m.get('last_p_yes'),'pn':m.get('last_p_no'),"
        "'pauses':m.get('pauses'),'resumes':m.get('resumes'),"
        "'forced':m.get('forced_resumes')},ensure_ascii=False))\n"
        "print('TEXT', t)\n"
    )
    with cl.sftp.open(f"{root}/.story.py", "w") as fh:
        fh.write(runner)
    code, out = cl.run(f"cd {root} && /root/miniconda3/bin/python3 .story.py 2>&1",
                       timeout=1800)
    print(out.strip(), flush=True)
    print(f"[{time.time()-t0:5.1f}s] 完成", flush=True)
finally:
    cl.close()
