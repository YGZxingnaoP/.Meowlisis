# -*- coding: utf-8 -*-
# 临时探针：加"禁止编造"红线后，测「北京的天气怎么样」的调用率 + 是否还会编天气
# 本轮不发起 execute，避免再写记忆
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from func.pipeline.llm_toolbox import LLMToolboxBridge, ToolCallAccumulator
from func.llm.llm_core import LLmCore
from func.llm.config import LLMConfig
from func.llm.prompt_get import PromptGet
from func.llm.message_builder import MessageBuilder

UID = "主人"
ATTEMPTS = 5
Q1 = "小猫晚上好啊，跟我讲讲今天的天气吧"
Q2 = "北京的天气怎么样"

tb = LLMToolboxBridge()
tools = tb.get_schemas()
core = LLmCore()
out = []


def gen(messages):
    acc = ToolCallAccumulator()
    buf = []
    for chunk in core.llm.chat_stream(messages, tools=tools, tool_choice="auto", enable_thinking=False):
        if not chunk.choices:
            continue
        d = chunk.choices[0].delta
        c = getattr(d, "content", None)
        if c:
            buf.append(c)
        tcs = getattr(d, "tool_calls", None)
        if tcs:
            acc.add(tcs)
    return "".join(buf), acc.payload()


def build(q):
    sp = tb.attach_tool_hint(PromptGet().get_system_prompt(UID, q))
    return MessageBuilder(LLMConfig().short_term_rounds).build_messages(UID, sp, q)


hits = 0
for i in range(1, ATTEMPTS + 1):
    c1, k1 = gen(build(Q1))
    m2 = build(Q2)
    m2 = m2[:-1] + [{"role": "assistant", "content": c1}, {"role": "user", "content": Q2}]
    c2, k2 = gen(m2)
    if k2:
        hits += 1
    out.append("--- 第%d轮尝试 ---" % i)
    out.append("[第1轮 调工具=%s] %s" % (bool(k1), c1))
    out.append("[第2轮 调工具=%s] %s" % (bool(k2), c2))
    if k2:
        out.append("[第2轮 TOOLCALLS] %s" % json.dumps(k2, ensure_ascii=False))

out.append("=" * 60)
out.append("第2轮「北京的天气怎么样」调用率 = %d/%d" % (hits, ATTEMPTS))
out.append("（本轮不发起 execute）")

with open("tmp_probe_out.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("WROTE tmp_probe_out.txt")
