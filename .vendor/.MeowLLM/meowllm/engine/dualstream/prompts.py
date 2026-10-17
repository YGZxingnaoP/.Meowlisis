# -*- coding: utf-8 -*-
"""提示词，**逐字**取自官方实现 `async_reasoning/prompting.py`。

为什么不再自己写
----------------
上一版我按论文 Figure 2 的**示意图**写了两段角色 system 说明，还拆成两个 Prompt Block。
官方代码证明那是错的：

    # thinker 看见：{input_prompt}{thinker_output}
    # writer  看见：{input_prompt}{thinker_output}{writer_output}
    # 模式切换    ：{mode_switching_prompt}{thinker_output}{writer_output}

    input_prompt = "<|im_start|>user\\n{problem}\\n"

**没有 system prompt**。角色区分完全靠两个输出前缀的文本：
    思考流开头： "<|im_end|>\\n<|im_start|>assistant\\n<think>\\n"
    输出流开头： " ... [SYSTEM: thoughts will continue here]\\n</think>\\n"

后者就是论文说的"linker"——它是流的第一段文本，不是独立 KV 块。
"""

from __future__ import annotations

import json
import re

# ---------------------------------------------------------------- 官方原文
#: 输入模板（只有 user 一条消息，没有 system）
INPUT_PROMPT = "<|im_start|>user\n{problem}\n"

#: 思考流的开头文本（含 chat template 的 assistant 头）
THINKER_OUTPUT_PREFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n"

#: 输出流的开头文本 —— 这就是论文的 linker
WRITER_OUTPUT_PREFIX = " ... [SYSTEM: thoughts will continue here]\n</think>\n"

#: 模式切换用的独立 prompt（第三个 worker 视图）
MODE_SWITCHING_PROMPT = (
    "<|im_start|>user\n"
    "You are an AI assistant that can think and write responses concurrently, "
    "and you must decide whether or not you should pause writing and think more.\n"
    "Read the current partial thoughts and response below, then decide whether you can "
    "continue writing the response without pausing (yes/no):\n"
    ' - Answer "yes" if your thoughts have enough information to write the next response '
    "paragraph, even if the full task is not solved yet.\n"
    ' - Answer "no" if your thoughts aren\'t enough to write the next response paragraph, '
    "i.e. if your response ran out of of thoughts.\n"
)

#: 插在模式切换视图末尾的问句（官方逐字，注意原文就是 "my current thoughts"）
MODE_SWITCHING_QUESTION = (
    "...\n\nWait, are my current thoughts enough to write the next paragraph or formula? "
    "(yes/no): "
)

YES_TOKEN = "yes"
NO_TOKEN = "no"


def pick(language: str = "en") -> dict:
    """返回一份提示词表。

    官方只有英文；`language` 保留是为了将来做中文实验，
    但**默认必须用 EN**，否则就不是复刻了。
    """
    if language not in ("en", "zh"):
        language = "en"
    return {
        "language": "en",                    # 资产一律用官方英文
        "input_prompt": INPUT_PROMPT,
        "thinker_output_prefix": THINKER_OUTPUT_PREFIX,
        "writer_output_prefix": WRITER_OUTPUT_PREFIX,
        "mode_switching_prompt": MODE_SWITCHING_PROMPT,
        "mode_switching_question": MODE_SWITCHING_QUESTION,
        "yes_token": YES_TOKEN,
        "no_token": NO_TOKEN,
    }


def render_input(problem: str) -> str:
    """把用户问题填进官方 input_prompt 模板。"""
    return INPUT_PROMPT.format(problem=problem)


def render_chat(messages: list[dict]) -> str:
    """把**多轮历史**渲染成 Qwen chat 格式。

    官方的 input_prompt 只处理单轮；多轮时接起历史：

        <|im_start|>user
        第一轮问题
        <|im_end|>
        <|im_start|>assistant
        第一轮回答
        <|im_end|>
        <|im_start|>user
        本轮问题

    末尾**不补** `<|im_end|>`：两条流各自的前缀负责 assistant 头
    （thinker 前缀里就带着 `<|im_end|>\\n<|im_start|>assistant\\n<think>\\n`）。
    """
    parts: list[str] = []
    for msg in messages:
        role = (msg.get("role") or "user").strip()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            parts.append(f"<|im_start|>assistant\n{content}\n<|im_end|>\n")
        elif role == "system":
            parts.append(f"<|im_start|>system\n{content}\n<|im_end|>\n")
        else:
            parts.append(f"<|im_start|>user\n{content}\n<|im_end|>\n")
    text = "".join(parts)
    if text.endswith("<|im_end|>\n"):
        text = text[: -len("<|im_end|>\n")] + "\n"
    return text


# ---------------------------------------------------------------- 工具调用
TOOL_CALL_OPEN = "<tool_call>"
TOOL_CALL_CLOSE = "</tool_call>"


def render_tools(tools: list[dict]) -> str:
    """把 OpenAI tools 定义渲染成提示词，并约定机器可解析的输出格式。

    本地模型没有原生 function calling，所以只能：
      1. 在 prompt 里把工具的 JSON Schema 讲清楚
      2. 约定一种标记格式，生成后自己解析
    """
    specs = []
    for item in tools or []:
        fn = item.get("function") if isinstance(item, dict) else None
        specs.append(fn or item)
    spec_text = json.dumps(specs, ensure_ascii=False, indent=2)
    return (
        "你可以在需要时调用工具。可用工具定义如下：\n"
        f"{spec_text}\n\n"
        "调用规则：\n"
        "1. 需要调用时，**只**输出一行：\n"
        f'   {TOOL_CALL_OPEN}{{"name": "工具名", "arguments": {{"参数": "值"}}}}{TOOL_CALL_CLOSE}\n'
        "2. 不要解释、不要附加其它文字。\n"
        "3. 无需调用工具时，正常回答问题即可。"
    )


def parse_tool_calls(text: str) -> list[dict]:
    """从模型输出里抽出 tool call，返回 [{"name":.., "arguments": json字符串}]。"""
    out: list[dict] = []
    if not text:
        return out
    pattern = re.compile(
        re.escape(TOOL_CALL_OPEN) + r"\s*(\{.*?\})\s*" + re.escape(TOOL_CALL_CLOSE),
        re.S)
    for match in pattern.finditer(text):
        try:
            obj = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        name = obj.get("name")
        if not name:
            continue
        args = obj.get("arguments", {})
        if not isinstance(args, str):
            args = json.dumps(args, ensure_ascii=False)
        out.append({"name": str(name), "arguments": args})
    return out
