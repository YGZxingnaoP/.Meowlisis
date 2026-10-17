# -*- coding: utf-8 -*-
"""给主项目**所有** port 家族批量生成 MeowLLM 本地 port（跳过 embedding）。

为什么用生成器
--------------
主项目有 12+ 个功能域，每个域都有 `port/{aliyun,deepseek,gemini}.py`，
形状几乎一致（只是 config 属性前缀不同）。手工抄 12 遍既慢又容易抄错，
所以这里自动探测前缀、自动生成。

做三件事（默认 dry-run，只报告不写）
--------------------------------
1. 扫描 `func/**/port/`，探测每个域的 config 属性前缀
2. 生成 `port/meowllm.py`（内容按该域的真实属性名定制）
3. 在该域的 `config.py` 里补 `local_*` 字段

**不做**：工厂注册（每个域的工厂写法不同，脚本只列出文件与建议代码，由人确认）

用法
----
    ..\\..\\runtime\\311\\python.exe .scripts\\gen_meowllm_ports.py --dry-run
    ..\\..\\runtime\\311\\python.exe .scripts\\gen_meowllm_ports.py
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PROJECT = Path(r"D:\.Meowlisis")
FUNC = PROJECT / "func"

#: 明确跳过（embedding / 非 chat）
SKIP_KEYWORDS = ("store", "embedding", "bge")

#: 这些域即使生成 port 也无法真正工作（缺能力），只提示不阻断
KNOWN_LIMITS = {
    "toolbox": "需要 function calling，本引擎不支持",
    "meowvision": "需要视觉塔，本地模型没有",
    "vision": "需要多模态输入，本地模型没有",
}

PORT_TEMPLATE = '''# -*- coding: utf-8 -*-
# {rel}/meowllm.py
# 本地 MeowLLM 双流推理（OpenAI 兼容子集）。由 gen_meowllm_ports.py 生成。

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from {config_module} import {config_class}


class {class_name}:
    """本地 MeowLLM 客户端。接口与 {sibling} 一致。

    - api_key 是占位，本地服务不校验
    - 不支持 tools：调用方传了就丢弃并记 warn
    - 思考流在 delta.reasoning_content，旁路累积到 last_reasoning
    """

    def __init__(self, config: Optional[{config_class}] = None):
        self.log = DefaultLog().getLogger()
        self.config = config if config is not None else {config_class}()
        self.api_key = getattr(self.config, "local_api_key", None) or "meowllm"
        self.base_url = getattr(self.config, "local_base_url",
                               "http://127.0.0.1:18100/meowllm/v1")
        self.model = getattr(self.config, "local_model", "meowllm-local")
        self.temperature = getattr(self.config, "local_temperature", 0.7)
        self.max_tokens = getattr(self.config, "local_max_tokens", 1024)
        self.top_p = getattr(self.config, "local_top_p", 0.9)
        self.enable_thinking = {default_thinking}

        self.last_reasoning = ""

        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.log.info(f"MeowLLM 客户端初始化成功，端点: {{self.base_url}}")
        except Exception as e:
            self.log.error(f"初始化 MeowLLM 客户端失败: {{e}}")
            self.client = None

    def _build_params(self, messages, tools=None, options=None,
                      tool_choice=None, enable_thinking=None) -> Dict:
        if tools:
            self.log.warning("MeowLLM 不支持 tools，已丢弃本次工具定义")
        opts = options or {{}}
        params = {{
            "model": opts.get("model", self.model),
            "messages": messages,
            "stream": True,
            "temperature": opts.get("temperature", self.temperature),
            "max_tokens": opts.get("max_tokens", self.max_tokens),
            "top_p": opts.get("top_p", self.top_p),
        }}
        use_thinking = self.enable_thinking if enable_thinking is None else enable_thinking
        if not use_thinking:
            params["extra_body"] = {{"thinking": {{"type": "disabled"}}}}
        return params

    def chat_stream(self, messages, tools=None, options=None,
                    tool_choice=None, enable_thinking=None):
        if not self.client:
            self.log.error("MeowLLM 客户端不可用")
            return iter([])
        self.last_reasoning = ""
        params = self._build_params(messages, tools, options, tool_choice, enable_thinking)
        try:
            stream = self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"MeowLLM 流式调用异常: {{e}}")
            return iter([])
        return self._tap(stream)

    def _tap(self, stream):
        try:
            for chunk in stream:
                try:
                    piece = getattr(chunk.choices[0].delta, "reasoning_content", None)
                    if piece:
                        self.last_reasoning += piece
                except (IndexError, AttributeError):
                    pass
                yield chunk
        except Exception as e:
            self.log.error(f"MeowLLM 流读取异常: {{e}}")
            return
'''

CONFIG_BLOCK = '''
        # ========== MeowLLM 本地模型（生成器追加）==========
        local_cfg = cfg.get('local', {})
        self.local_api_key = local_cfg.get('api_key', 'meowllm')
        self.local_base_url = local_cfg.get(
            'base_url', 'http://127.0.0.1:18100/meowllm/v1')
        self.local_model = local_cfg.get('model', 'meowllm-local')
        self.local_temperature = local_cfg.get('temperature', 0.7)
        self.local_max_tokens = local_cfg.get('max_tokens', 1024)
        self.local_top_p = local_cfg.get('top_p', 0.9)
        self.local_enable_thinking = local_cfg.get('enable_thinking', True)
'''


def detect_prefix(port_dir: Path) -> tuple[str, str] | None:
    """从同目录任一 port 里探测 config 属性前缀与 config 类名。"""
    for f in sorted(port_dir.glob("*.py")):
        if f.name in ("__init__.py", "meowllm.py"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        m = re.search(r"self\.config\.(\w+?)_base_url", text)
        if not m:
            m = re.search(r"cfg\.(\w+?)_base_url", text)
        c = re.search(r"from\s+([\w.]+)\s+import\s+(\w*Config)", text)
        if m:
            return m.group(1), (c.group(2) if c else "Config")
    return None


def config_file_for(port_dir: Path) -> Path | None:
    """port 的上一级目录里找 config.py。"""
    cand = port_dir.parent / "config.py"
    return cand if cand.is_file() else None


def class_name_for(port_dir: Path) -> str:
    """由路径推出类名，如 func/toolbox/meowvision/port -> MeowVisionMeowLLM。"""
    parts = [p for p in port_dir.parts if p not in ("port", "func")]
    raw = "_".join(parts)
    return "".join(w.capitalize() for w in raw.split("_")) + "MeowLLM"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    port_dirs = sorted({p.parent for p in FUNC.rglob("port/*.py")})
    print(f"发现 {len(port_dirs)} 个 port 目录\n")

    done, skipped, need_manual = 0, 0, []

    for port_dir in port_dirs:
        rel = port_dir.relative_to(PROJECT)
        if any(k in str(rel).lower() for k in SKIP_KEYWORDS):
            print(f"  跳过 {rel}（embedding）")
            skipped += 1
            continue

        info = detect_prefix(port_dir)
        if not info:
            print(f"  ✗ {rel}：探测不到 config 前缀，需手工")
            need_manual.append(rel)
            continue
        prefix, config_class = info

        cfg_py = config_file_for(port_dir)
        if cfg_py is None:
            print(f"  ✗ {rel}：找不到同级 config.py")
            need_manual.append(rel)
            continue

        cls = class_name_for(port_dir)
        target = port_dir / "meowllm.py"
        sibling = f"{prefix}_*.py"
        note = ""
        for key, why in KNOWN_LIMITS.items():
            if key in str(rel).lower():
                note = f"   ⚠ {why}（port 可用但功能不完整）"

        print(f"  ✓ {rel}")
        print(f"      config 前缀 = {prefix}_   config 类 = {config_class}")
        print(f"      生成 {target.name}（类 {cls}）{note}")

        if not args.dry_run:
            target.write_text(
                PORT_TEMPLATE.format(rel=rel.as_posix(), config_module=cfg_py.stem
                                     if False else f"func.{'.'.join(cfg_py.relative_to(FUNC).with_suffix('').parts)}",
                                     config_class=config_class, class_name=cls,
                                     sibling=sibling, default_thinking="True"),
                encoding="utf-8")

            text = cfg_py.read_text(encoding="utf-8")
            if "local_base_url" not in text:
                # 插到文件末尾最后一个 self.xxx = ... 之后
                lines = text.splitlines(keepends=True)
                idx = max((i for i, ln in enumerate(lines)
                           if re.match(r"\s+self\.\w+\s*=", ln)), default=len(lines) - 1)
                lines.insert(idx + 1, CONFIG_BLOCK)
                cfg_py.write_text("".join(lines), encoding="utf-8")
                print(f"      已向 {cfg_py.relative_to(PROJECT)} 追加 local_* 字段")
        done += 1

    print(f"\n合计：生成 {done} 个，跳过 {skipped} 个，需手工 {len(need_manual)} 个")
    if need_manual:
        print("需手工处理：")
        for r in need_manual:
            print(f"  - {r}")

    print("""
下一步（脚本不做，必须人工确认）：
  1) 每个域的 port 工厂加分支：
         elif llm_type == "meowllm":
             from func.<域>.port.meowllm import <Cls>
             return <Cls>(config)
  2) config.yml 里给每个域加：
         llm_type: meowllm      # 或该域自己的字段名
         local:
           base_url: http://127.0.0.1:18100/meowllm/v1
           model: meowllm-local
     （但 config.py 读的是 cfg.get('local')，需要放在该域的节点下）
""")
    if args.dry_run:
        print("--dry-run：没有写任何文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
