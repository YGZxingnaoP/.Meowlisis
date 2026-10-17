#!/usr/bin/env bash
. /etc/network_turbo >/dev/null 2>&1

/root/miniconda3/bin/python - <<'PY'
import json, urllib.request, urllib.error

def probe(repo):
    url = f"https://huggingface.co/api/models/{repo}?blobs=true"
    print("URL:", url)
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            print("HTTP", r.status)
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print("HTTPError", e.code, e.reason)
        return
    except Exception as e:
        print("ERR", type(e).__name__, e)
        return
    print("top keys:", list(d)[:12])
    sib = d.get("siblings", [])
    print("siblings:", len(sib))
    for s in sib[:15]:
        size = s.get("size")
        lfs = (s.get("lfs") or {}).get("size")
        print(f"  {s.get('rfilename'):<48} size={size} lfs={lfs}")

for repo in ("Qwen/Qwen3-8B", "Qwen/Qwen3-8B-Instruct"):
    print("=" * 60)
    probe(repo)
PY
