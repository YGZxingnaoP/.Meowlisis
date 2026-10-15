# -*- coding: utf-8 -*-
import json

lines = []
d = json.load(open('.temp/public_short_mem.json', encoding='utf-8'))
lines.append("短期记忆总条数 = %d" % len(d))
lines.append("-" * 60)
for x in d[-6:]:
    lines.append("%s | %s | %s" % (x.get('role'), x.get('type'), str(x.get('content'))[:100]))

try:
    from func.pipeline.ltmem import MeowLLMLtMemBridge
    b = MeowLLMLtMemBridge()
    lines.append("=" * 60)
    lines.append("ltmem 桥接 = %r" % b)
    for attr in dir(b):
        if 'path' in attr.lower() or 'file' in attr.lower():
            lines.append("  %s = %r" % (attr, getattr(b, attr)))
except Exception as e:
    lines.append("ltmem 探测失败: %r" % e)

with open('tmp_mem_out.txt', 'w', encoding='utf-8') as f:
    f.write("\n".join(lines))
print("OK")
