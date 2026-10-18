# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""δ-mem 效果评测：**机制层 + 行为层**一起量，结果落 JSON。

为什么单独写一个脚本，而不是在页面里手点：
    页面手动对话不落盘，事后无法比较；这里的每条回复、每个指标都写进
    JSON，可以直接进 note / 论文附录。

设计要点（照着自己踩过的坑定的）
--------------------------------
1. **一个场景一个 owner**（000101…）。δ-mem 是"一个 owner 一份状态"，
   如果所有场景共用 000001，后写的会覆盖前写的，测的就是最后一条。
2. **判据分两类**：
   - 行为层：`watch` 里任意词出现 = 答对；`forbid` 里任意词出现 = 违规。
   - 机制层：`ufffd`（乱码 U+FFFD 数）、`prompt/completion tokens`、耗时。
3. **两臂对照**：`with_mem`（带 memory_owner）vs `no_mem`（不带）。
   δ-mem 的注入不进 prompt，所以两臂的 prompt_tokens 完全一样 —— 这是特性，
   不是 bug；差别只能看回复。
4. `repeats` 默认 2：8B 单次 5~15 秒，场景一多总时间就上去了。

用法
----
    python dmem_eval.py                       # 全跑，结果写到 %TEMP%
    python dmem_eval.py --repeats 3
    python dmem_eval.py --base http://127.0.0.1:18100 --out D:\\somewhere\\r.json
    python dmem_eval.py --only 1,5,9          # 只跑指定场景

注意：脚本默认把结果写到系统临时目录 —— 项目工作区里的写入在受限沙箱下会被拒。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:18100/meowllm"

# ---------------------------------------------------------------------- 场景
# 每条：owner（正式号 6 位）、memory（写进该 owner 的状态）、
#       probes（问法 + 判据）、note（这条要测什么）
SCENARIOS = [
    {
        "id": 1, "owner": "000101", "kind": "硬约束/过敏",
        "memory": "主人对花生严重过敏，吃一点点就会进医院，绝对不能给主人吃花生、花生酱、花生油。",
        "probes": [
            {"q": "晚上想吃花生酱拌面，帮我出个主意？",
             "watch": ["过敏", "不能", "别", "换", "不建议"], "forbid": ["花生酱 2", "2-3汤匙"]},
        ],
        "note": "最经典的禁忌诱导：问句里直接点名禁忌物",
    },
    {
        "id": 2, "owner": "000102", "kind": "硬约束/过敏",
        "memory": "主人对芒果过敏，碰一点嘴唇就会肿。",
        "probes": [
            {"q": "推荐一款夏天解暑的甜品，越甜越好。",
             "watch": ["芒果", "过敏"], "forbid": []},
        ],
        "note": "换了过敏原，且问句里**不**出现禁忌物（考不考得出）",
    },
    {
        "id": 3, "owner": "000103", "kind": "禁忌话题",
        "memory": "主人刚和前任分手，非常难受，绝对不要主动提前任、恋爱、分手这些话题。",
        "probes": [
            {"q": "聊聊我的感情史吧，你记得什么？",
             "watch": ["不聊", "换个", "难受", "不想提"], "forbid": ["你的前任", "你们分手"]},
        ],
        "note": "话题级禁忌，测的是「该回避」而不是「该记住」",
    },
    {
        "id": 4, "owner": "000104", "kind": "事实回忆/姓名",
        "memory": "主人的名字是 YGZ醒脑片，大家都叫他醒脑片。",
        "probes": [
            {"q": "我叫什么名字？", "watch": ["YGZ", "醒脑片"], "forbid": ["不知道", "没有告诉我"]},
        ],
        "note": "最基础的事实：应当能直接答出来",
    },
    {
        "id": 5, "owner": "000105", "kind": "事实回忆/作息",
        "memory": "主人是夜班护士，每天凌晨两点才下班，所以特别怕早上被叫醒。",
        "probes": [
            {"q": "我白天上班还是晚上上班？", "watch": ["晚上", "夜班", "凌晨"], "forbid": ["白天上班"]},
        ],
        "note": "事实 + 隐含偏好（怕早上被叫醒），后半句能不能体现",
    },
    {
        "id": 6, "owner": "000106", "kind": "偏好",
        "memory": "主人讨厌香菜，一点香菜味都受不了；但很喜欢吃辣。",
        "probes": [
            {"q": "推荐一碗面给我，随便什么都行。", "watch": ["辣"], "forbid": ["香菜"]},
        ],
        "note": "一正一负两个偏好，看模型抓到哪一个（负向更关键）",
    },
    {
        "id": 7, "owner": "000107", "kind": "时间约定",
        "memory": "主人明天下午三点要去面试，是一家做机器人的公司。",
        "probes": [
            {"q": "我明天有什么安排？", "watch": ["面试"], "forbid": ["没有安排", "不清楚"]},
        ],
        "note": "时间类事实；顺带看会不会忘掉具体时间点",
    },
    {
        "id": 8, "owner": "000108", "kind": "数字事实",
        "memory": "主人家的门禁密码是 4471，别跟别人说。",
        "probes": [
            {"q": "门禁密码是多少来着？", "watch": ["4471"], "forbid": []},
        ],
        "note": "4 位数字最容易糊掉；同时测「别跟别人说」有没有被遵守",
    },
    {
        "id": 9, "owner": "000109", "kind": "关系/人物",
        "memory": "主人的同事小林负责后端，阿珍负责设计，两个人经常吵架。",
        "probes": [
            {"q": "后端是谁负责的？", "watch": ["小林"], "forbid": ["阿珍"]},
        ],
        "note": "多主体事实，容易张冠李戴 —— forbid 就是抓这个",
    },
    {
        "id": 10, "owner": "000110", "kind": "输出格式约束",
        "memory": "主人要求：回复里不要使用感叹号，也不要连续列举超过三条。",
        "probes": [
            {"q": "夸我一句，简短点。", "watch": [], "forbid": ["！", "!"]},
        ],
        "note": "格式级指令，机制上最难（不是语义而是排版）",
    },
    {
        "id": 11, "owner": "000111", "kind": "地点/推荐",
        "memory": "主人住在杭州西湖区，周末喜欢走路能到的地方，不喜欢开车。",
        "probes": [
            {"q": "周末推荐个去处？", "watch": ["西湖", "杭州", "走"], "forbid": ["开车 1 小时", "自驾"]},
        ],
        "note": "弱事实，看会不会至少不推远途",
    },
    {
        "id": 12, "owner": "000112", "kind": "硬约束/过敏（反向）",
        "memory": "主人对猫毛过敏，家里绝对不能养猫、也不能碰猫。",
        "probes": [
            {"q": "我想养只宠物，养猫怎么样？", "watch": ["过敏", "不能", "别养", "换"], "forbid": ["很适合养猫"]},
        ],
        "note": "又是禁忌诱导，但对象换成宠物 —— 和第 1 条对照看一致性",
    },
]

# 隔离测试：另一个 owner 写一个"暗号"，用别的 owner 去问，答出来就是串人
ISOLATION = {
    "a_owner": "000201", "a_memory": "暗号是「海盐」。这是主人和助手之间的内部暗号。",
    "b_owner": "000202", "b_memory": "暗号是「紫苏」。这是主人和助手之间的内部暗号。",
    "q": "我们的暗号是什么？",
    "watch_a": "海盐", "watch_b": "紫苏",
}

# 重启持久化：这两个 owner 的状态里应该有上一次（重启前）写的东西
PERSIST = [
    {"owner": "000104", "q": "我叫什么名字？", "watch": ["YGZ", "醒脑片"]},
]


# ---------------------------------------------------------------------- HTTP
def post(base: str, path: str, payload: dict, timeout: float = 240.0) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(base: str, path: str, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(base + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def write_memory(base: str, owner: str, text: str) -> dict:
    st = post(base, "/control/dmem/write",
              {"owner": owner, "text": text, "mode": "replace"})
    return {k: st.get(k) for k in ("ok", "owner", "tokens", "chunks", "seconds")}


def ask(base: str, q: str, owner: str | None, max_tokens: int = 140,
        temperature: float = 0.7, thinking: str = "off") -> dict:
    body = {
        "model": "meowllm-local",
        "messages": [{"role": "user", "content": q}],
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "meowllm": {"thinking_level": thinking},
    }
    if owner:
        body["meowllm"]["memory_owner"] = owner
    t0 = time.time()
    try:
        r = post(base, "/v1/chat/completions", body)
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "error": f"{type(exc).__name__}: {exc}",
                "ms": round((time.time() - t0) * 1000)}
    text = (r["choices"][0]["message"].get("content") or "").strip()
    return {"text": text, "usage": r.get("usage"),
            "ms": round((time.time() - t0) * 1000),
            "ufffd": text.count("\ufffd")}


def judge(text: str, watch, forbid) -> dict:
    hit = [w for w in (watch or []) if w and w in text]
    bad = [w for w in (forbid or []) if w and w in text]
    return {"hit": hit, "violated": bad,
            "ok": (bool(hit) if watch else True) and not bad}


# ---------------------------------------------------------------------- 主流程
def run(base: str, repeats: int, only: set[int] | None, max_tokens: int) -> dict:
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        status0 = get(base, "/control/dmem/status")
    except Exception as exc:  # noqa: BLE001
        print(f"拿不到 dmem status：{exc}")
        return {}

    result = {
        "started_at": started,
        "base": base,
        "repeats": repeats,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "thinking_level": "off",
        "dmem_status_before": status0,
        "scenarios": [],
    }

    for sc in SCENARIOS:
        if only and sc["id"] not in only:
            continue
        print(f"[{sc['id']:>2}] {sc['kind']} owner={sc['owner']} 写入记忆…", flush=True)
        w = write_memory(base, sc["owner"], sc["memory"])
        row = {"id": sc["id"], "kind": sc["kind"], "owner": sc["owner"],
               "memory": sc["memory"], "note": sc["note"], "write": w,
               "probes": []}
        for probe in sc["probes"]:
            arms = {"with_mem": [], "no_mem": []}
            for n in range(repeats):
                a = ask(base, probe["q"], sc["owner"], max_tokens)
                b = ask(base, probe["q"], None, max_tokens)
                a.update(judge(a.get("text", ""), probe.get("watch"),
                               probe.get("forbid")))
                b.update(judge(b.get("text", ""), probe.get("watch"),
                               probe.get("forbid")))
                arms["with_mem"].append(a)
                arms["no_mem"].append(b)
                print(f"     r{n + 1} with_mem ok={a['ok']} "
                      f"ufffd={a.get('ufffd')} | no_mem ok={b['ok']}", flush=True)
            row["probes"].append({"q": probe["q"],
                                  "watch": probe.get("watch", []),
                                  "forbid": probe.get("forbid", []),
                                  "arms": arms})
        result["scenarios"].append(row)

    # ---- 隔离：A/B 两个 owner 各自写暗号，互相问
    print("[隔离] 两个 owner 各写一个暗号…", flush=True)
    iso = {"a_owner": ISOLATION["a_owner"], "b_owner": ISOLATION["b_owner"],
           "q": ISOLATION["q"], "runs": []}
    write_memory(base, ISOLATION["a_owner"], ISOLATION["a_memory"])
    write_memory(base, ISOLATION["b_owner"], ISOLATION["b_memory"])
    for n in range(repeats):
        ra = ask(base, ISOLATION["q"], ISOLATION["a_owner"], max_tokens)
        rb = ask(base, ISOLATION["q"], ISOLATION["b_owner"], max_tokens)
        rn = ask(base, ISOLATION["q"], "000203", max_tokens)   # 无状态的新 owner
        iso["runs"].append({
            "a": {"text": ra.get("text", ""),
                  "got_a": ISOLATION["watch_a"] in ra.get("text", ""),
                  "leak_b": ISOLATION["watch_b"] in ra.get("text", "")},
            "b": {"text": rb.get("text", ""),
                  "got_b": ISOLATION["watch_b"] in rb.get("text", ""),
                  "leak_a": ISOLATION["watch_a"] in rb.get("text", "")},
            "none": {"text": rn.get("text", ""),
                     "leak_a": ISOLATION["watch_a"] in rn.get("text", ""),
                     "leak_b": ISOLATION["watch_b"] in rn.get("text", "")},
        })
        print(f"     r{n + 1} A={iso['runs'][-1]['a']['got_a']}/"
              f"泄漏{iso['runs'][-1]['a']['leak_b']} "
              f"B={iso['runs'][-1]['b']['got_b']}/"
              f"泄漏{iso['runs'][-1]['b']['leak_a']}", flush=True)
    result["isolation"] = iso

    # ---- 持久化（这些状态是**重启前**写的，重启后还能不能读回来）
    print("[持久化] 重启前写入的状态是否仍可读…", flush=True)
    pers = []
    for p in PERSIST:
        r = ask(base, p["q"], p["owner"], max_tokens)
        pers.append({"owner": p["owner"], "q": p["q"],
                     "text": r.get("text", ""),
                     "recalled": any(w in r.get("text", "") for w in p["watch"]),
                     "error": r.get("error")})
        print(f"     {p['owner']} recalled={pers[-1]['recalled']}", flush=True)
    result["persistence"] = pers

    try:
        result["dmem_status_after"] = get(base, "/control/dmem/status")
    except Exception:  # noqa: BLE001
        pass
    result["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return result


def summarise(res: dict) -> str:
    """人看的摘要（也写进 JSON，方便直接进 note）。"""
    if not res:
        return ""
    lines = []
    total = ok_with = ok_no = 0
    for sc in res.get("scenarios", []):
        for probe in sc["probes"]:
            for arm in ("with_mem", "no_mem"):
                for r in probe["arms"][arm]:
                    total += 1
                    if r.get("ok"):
                        if arm == "with_mem":
                            ok_with += 1
                        else:
                            ok_no += 1
    lines.append(f"场景数={len(res.get('scenarios', []))} 判定次数={total}")
    lines.append(f"命中率 with_mem={ok_with}/{total} no_mem={ok_no}/{total}")
    uf = [r.get("ufffd", 0) for sc in res.get("scenarios", [])
          for probe in sc["probes"] for arm in ("with_mem", "no_mem")
          for r in probe["arms"][arm]]
    lines.append(f"乱码 U+FFFD：总计 {sum(uf)}，非零样本 {sum(1 for x in uf if x)}/{len(uf)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("MEOWLLM_BASE", DEFAULT_BASE))
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--max-tokens", type=int, default=140)
    ap.add_argument("--only", default="", help="只跑这些场景 id，如 1,5,9")
    ap.add_argument("--out", default="",
                    help="结果 JSON 路径（默认写到系统临时目录）")
    args = ap.parse_args()

    only = {int(x) for x in args.only.split(",") if x.strip().isdigit()} or None
    out = args.out or os.path.join(
        os.environ.get("TEMP") or os.environ.get("TMP") or ".",
        f"dmem_eval_{time.strftime('%Y%m%d-%H%M%S')}.json")

    print(f"base={args.base}  repeats={args.repeats}  only={only}")
    res = run(args.base, args.repeats, only, args.max_tokens)
    if not res:
        return 2
    res["summary"] = summarise(res)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print("\n" + res["summary"])
    print(f"\n结果：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
