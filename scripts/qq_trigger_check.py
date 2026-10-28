# -*- coding: utf-8 -*-
# scripts/qq_trigger_check.py
# 父级工具触发验证（只读）：带完整系统提示词 + 真实短期记忆，检查主链路模型
# 面对「QQ 发消息」需求时会不会触发 napcat_send / napcat_ask_bot。
#
# 只读保证：
#   * 短期记忆直接从 .temp/public_short_mem.json 读，不经 ShortMemory（其构造会写会话分割）；
#   * 不写长期记忆 / 用户档案，不启动心理生成线程（只读现有 latest_psyche.json）；
#   * 不执行任何 tool_call：只打印模型返回的调用，不交给 analysis；
#   * 不调用发送接口，不产生任何 QQ 消息；
#   * 知识库块默认跳过（读取一次性搜索摘要会清缓存），需要时加 --with-knowledge。
#
# 用法：
#   runtime\311\python.exe scripts\qq_trigger_check.py --text "在测试群 @小明 说今晚八点开会"
#   runtime\311\python.exe scripts\qq_trigger_check.py --uid 000001 --text "..." --show-prompt

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)


def load_short_memory(path=".temp/public_short_mem.json"):
    """只读加载真实短期记忆（不实例化 ShortMemory，避免写会话分割）"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    out = []
    for m in data if isinstance(data, list) else []:
        if m.get("role") in ("user", "assistant", "system") and m.get("content"):
            out.append({"role": m["role"], "content": str(m["content"])})
    return out


def build_system_prompt(uid, text, with_knowledge=False, with_psyche=True):
    """复刻 llm_core 的系统提示词：前置词 + 心理 + 手机 + body + 后置词 + 工具决策前置词"""
    from func.catbrain.prompt_builder import MeowPromptBuilder
    from func.pipeline.system_prompt import SystemPromptBridge
    from func.pipeline.id_signup import display_name

    if not with_knowledge:
        # 知识库块会读走一次性搜索摘要（读后即清），只读验证时跳过
        MeowPromptBuilder._build_knowledge = staticmethod(
            lambda uid="", current_message="": "")

    sp = SystemPromptBridge()
    if getattr(sp, "_builder", None) is None:
        sp.register_builder(MeowPromptBuilder())

    name = display_name(uid)
    front = sp.get_front_prompt()
    if front:
        front = front.replace("{display_name(uid)}", name)
    body = sp._builder.build(uid, text, mark_first=False)   # 不占「当天首次说话」
    post = sp.get_post_prompt()
    if post:
        post = f"{post}\n你现在在和{name}说话"
    psyche = sp._psyche_block() if with_psyche else ""    # 只读现有心理文件，不启动生成线程
    phone = sp._phone_block()
    prompt = "\n\n".join([p for p in (front, psyche, phone, body, post) if p])

    from func.pipeline.llm_toolbox import LLMToolboxBridge
    from func.toolbox.plugins.manager import PluginManager
    try:
        plugin_hint = PluginManager().prompt_hint()
    except Exception:
        plugin_hint = ""
    hint = SystemPromptBridge().get_tool_hint_prompt(plugin_hint)
    if hint:
        prompt = f"{prompt}\n\n{hint}"
    return prompt, LLMToolboxBridge()


def build_llm():
    """按 func/llm 配置创建主链路 LLM 客户端（不创建 LLmCore，避免 MessageBuilder 写短期记忆）"""
    from func.llm.config import LLMConfig
    cfg = LLMConfig()
    kind = cfg.local_llm_type
    if kind == "meowllm":
        from func.llm.port.meowllm import MeowLLMLLM
        return MeowLLMLLM(cfg), kind
    if kind == "gemini":
        from func.llm.port.gemini import GeminiLLM
        return GeminiLLM(cfg), kind
    if kind == "aliyun":
        from func.llm.port.aliyun import AliyunLLM
        return AliyunLLM(cfg), kind
    from func.llm.port.deepseek import DeepSeekLLM
    return DeepSeekLLM(cfg), kind


def main():
    parser = argparse.ArgumentParser(description="父级工具触发验证（只读）")
    parser.add_argument("--uid", default="000001", help="内部编号（默认 000001）")
    parser.add_argument("--text", required=True, help="要验证的用户消息")
    parser.add_argument("--show-prompt", action="store_true", help="打印完整系统提示词")
    parser.add_argument("--with-knowledge", action="store_true",
                        help="包含知识库块（会读取并清空一次性搜索摘要）")
    parser.add_argument("--no-psyche", action="store_true",
                        help="不注入心理块（排查心理状态对工具触发的影响）")
    parser.add_argument("--no-memory", action="store_true",
                        help="不带短期记忆（排查历史对话对工具触发的影响）")
    args = parser.parse_args()

    system_prompt, tb = build_system_prompt(args.uid, args.text, args.with_knowledge,
                                           with_psyche=not args.no_psyche)
    memory = [] if args.no_memory else load_short_memory()
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(memory)
    messages.append({"role": "user", "content": args.text})

    tools = tb.get_schemas()
    names = [t.get("function", {}).get("name") for t in tools if isinstance(t, dict)]
    qq_tools = [n for n in names if n and ("napcat" in n or n.startswith(("get_", "send_")))]

    print("=" * 72)
    print("系统提示词长度:", len(system_prompt))
    print("短期记忆条数:", len(memory))
    print("父级工具(%d): %s" % (len(names), names))
    print("QQ 相关父级工具:", qq_tools)
    if args.show_prompt:
        print("-" * 72)
        print(system_prompt)
        print("-" * 72)

    llm, kind = build_llm()
    if not getattr(llm, "client", None):
        print("[失败] LLM 客户端不可用（配置类型 %s）" % kind)
        return 1

    from func.pipeline.llm_toolbox import ToolCallAccumulator
    acc = ToolCallAccumulator()
    chunks = []
    stream = llm.chat_stream(messages, tools=tools, tool_choice="auto", enable_thinking=False)
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)
        if content:
            chunks.append(content)
        if getattr(delta, "tool_calls", None):
            acc.add(delta.tool_calls)

    text = "".join(chunks).strip()
    calls = acc.payload()
    print("[模型正文]", text if text else "(无正文)")
    print("[工具调用]", json.dumps(calls, ensure_ascii=False, indent=2) if calls else "(无)")

    triggered = [c["function"]["name"] for c in calls]
    hit = [n for n in triggered if n in ("napcat_send", "napcat_ask_bot")]
    print("=" * 72)
    print("结论:", ("会触发 QQ 链路：" + "、".join(hit)) if hit
          else "未触发 QQ 发消息入口")
    print("（只读验证：未执行任何工具、未写入记忆、未发送任何 QQ 消息）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
