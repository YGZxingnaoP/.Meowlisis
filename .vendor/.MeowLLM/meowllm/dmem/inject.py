# -*- coding: utf-8 -*-
"""把一个"带 δ-mem 的 attention 实现"插进 transformers 的派发表。

为什么要在 attention 接口层做
----------------------------
论文 §3.3：`q̃ = q0 + αΔq`，然后 `a = Attn(q̃, K, V)`，最后 `ỹ = a + αΔo`。
`q̃` 里的 `q0` 是 **q_norm 之后、RoPE 之前** 的 query，而这个位置在
`Qwen3Attention.forward` 内部，光靠 module hook 改不到。

但 RoPE 对 query 是线性的：`rope(q0 + αΔq) = rope(q0) + rope(αΔq)`。
attention 接口拿到的 query 已经是 `rope(q0)`，所以我们把 `rope(αΔq)` 加上去，
**等价于**在 pre-RoPE 处相加，而且完全不用改 transformers 或 MeowLLM 的引擎代码。
cos/sin 由 attention 模块的 forward_pre_hook 从 `position_embeddings` 参数里取。

Δo 加在 attention 输出上（`(B, L, H, D)`，正是 o_proj 之前），与论文一致。

为什么是"包一层"而不是替身
--------------------------
MeowLLM 双流引擎会把 `_attn_implementation` 设成 `meowllm_ar`（按块旋 query 的
实现）。这里读当前实现名、把它包起来、注册成 `meowllm_dmem_<原名>`，再切过去。
所以训练（sdpa/eager）与双流推理（meowllm_ar）走同一份 δ-mem 代码，行为一致。
"""

from __future__ import annotations

import torch

try:
    from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS
except Exception:  # pragma: no cover
    ALL_ATTENTION_FUNCTIONS = None

PREFIX = "meowllm_dmem_"
_installed: dict[str, object] = {}


# --------------------------------------------------------------------- 工具
def find_attention_modules(model) -> list:
    """认出 attention 模块。

    判据与 MeowLLM 引擎一致（`LayerCache/dualstream/attention.py` 的 attach）：
    有 `layer_idx` 和 `o_proj`。这样换模型家族也不会误伤 MLP。
    """
    out = []
    for module in model.modules():
        if hasattr(module, "layer_idx") and hasattr(module, "o_proj"):
            out.append(module)
    return out


def current_impl(model) -> str:
    cfg = getattr(model, "config", None)
    name = getattr(cfg, "_attn_implementation", None) if cfg is not None else None
    return str(name or "sdpa")


def _lookup(name: str):
    if ALL_ATTENTION_FUNCTIONS is None:
        raise RuntimeError("transformers 的 attention 派发表不可用")
    getter = getattr(ALL_ATTENTION_FUNCTIONS, "get", None)
    if callable(getter):
        fn = getter(name)
        if fn is not None:
            return fn
    return ALL_ATTENTION_FUNCTIONS[name]


def _register(name: str, fn) -> None:
    register = getattr(ALL_ATTENTION_FUNCTIONS, "register", None)
    if callable(register):
        try:
            register(name, fn)
            return
        except TypeError:
            try:
                register(name)(fn)
                return
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
    ALL_ATTENTION_FUNCTIONS[name] = fn


# --------------------------------------------------------------------- hook
def install_hooks(model, dmem, modules=None) -> list:
    """给每个 attention 装 pre-hook：记下本层输入隐状态与 RoPE 的 cos/sin。"""
    handles = []
    modules = modules if modules is not None else find_attention_modules(model)

    def make_hook(module):
        def hook(_module, args, kwargs):
            hidden = kwargs.get("hidden_states")
            pos = kwargs.get("position_embeddings")
            if hidden is None and args:
                hidden = args[0]
            if pos is None and len(args) > 1:
                pos = args[1]
            if hidden is None:
                return
            _module._dmem_hidden = hidden            # noqa: SLF001 - 我们自己的槽位
            if isinstance(pos, (tuple, list)) and len(pos) == 2:
                _module._dmem_rope = pos             # noqa: SLF001
            layer = getattr(_module, "_dmem_layer", None)
            if layer is not None and dmem.collecting:
                dmem._hidden[layer.layer_idx] = hidden  # noqa: SLF001
        return hook

    for module in modules:
        layer = dmem.layer_for(int(module.layer_idx))
        if layer is None:
            continue
        # ⚠ 必须用 object.__setattr__：nn.Module.__setattr__ 会把 nn.Module 类型的
        # 值注册成子模块，于是 backbone 的 state_dict / parameters() 里会冒出
        # 整个 δ-mem（实测 backbone.parameters() 多出 224 个张量，
        # save_pretrained 也会把 δ-mem 权重写进模型文件）。
        object.__setattr__(module, "_dmem_layer", layer)
        object.__setattr__(module, "_dmem", dmem)
        handles.append(module.register_forward_pre_hook(make_hook(module),
                                                        with_kwargs=True))
    return handles


# ------------------------------------------------------------------ wrapper
def _wrap(prev_fn, dmem):
    def forward(module, query, key, value, attention_mask=None, **kwargs):
        layer = getattr(module, "_dmem_layer", None)
        dq = do = None
        if layer is not None and dmem.enabled and dmem.states:
            dq, do = dmem.deltas(module, layer, query)
            if dq is not None:
                if dmem.debug:
                    object.__setattr__(module, "_dmem_last_q", query.detach())
                query = query + dq.to(query.dtype)
        out, weights = prev_fn(module, query, key, value, attention_mask, **kwargs)
        if do is not None:
            if dmem.debug:
                object.__setattr__(module, "_dmem_last_out", out.detach())
            out = out + do.to(out.dtype)
        return out, weights

    return forward


def ensure_wrapped(model, dmem, base_name: str | None = None) -> str:
    """确保 `base_name` 这个实现有一个"带 δ-mem"的包装版，返回包装名。

    懒包装（按需注册）而不是启动时固定一个名字，是因为 **MeowLLM 双流引擎会在
    `DualStreamLoop.__init__` 里把实现换成 `meowllm_ar`**（每个请求都会新建一个
    loop，所以每请求都换一次）。如果启动时只包装了当时的 `sdpa`，引擎一切换就
    把 δ-mem 绕过去了 —— 更糟的是被 guard 强行拉回 `sdpa` 会让引擎丢掉按块旋转，
    输出直接错。所以这里按"当前是谁就包装谁"来做。
    """
    base = base_name or current_impl(model)
    if base.startswith(PREFIX):
        return base
    cache = getattr(dmem, "wrapped", None)
    if cache is None:
        cache = {}
        object.__setattr__(dmem, "wrapped", cache)
    name = PREFIX + base
    if cache.get(base) == name and name in _installed:
        return name
    fn = _lookup(base)
    _register(name, _wrap(fn, dmem))
    _installed[name] = dmem
    cache[base] = name
    return name


def install_attention(model, dmem) -> str:
    """把当前 attention 实现包成带 δ-mem 的版本并切过去；返回原实现名。"""
    prev = current_impl(model)
    _set_impl(model, ensure_wrapped(model, dmem, prev))
    return prev


def plain_impl(steered: bool = False) -> str:
    """写记忆/定标要用的实现名：`steered=False` 走原始 sdpa，`True` 走带 δ-mem 的。"""
    return (PREFIX + "sdpa") if steered else "sdpa"


def install_guard(model, dmem) -> object:
    """模型前向时把 `_attn_implementation` 补成"带 δ-mem 的包装名"。

    为什么必须有这个：MeowLLM 的 `DualStreamLoop.__init__` 每个请求都会调
    `set_attn_impl(model)` 把 `_attn_implementation` 写回 `"meowllm_ar"`，
    把我们装的包装名直接冲掉 —— 实测现象是"写完记忆后 steering 完全没反应，
    logits 差 0"。挂一个模型最外层的前向 pre-hook，把"当前实现"就地包一层即可，
    不依赖引擎内部实现。

    `dmem.bypass_impl=True` 时不干预（写记忆那趟要走普通 attention）。
    """
    def guard(module, _args, _kwargs):
        if dmem.bypass_impl:
            return
        current = current_impl(module)
        if current.startswith(PREFIX):
            return
        try:
            _set_impl(module, ensure_wrapped(module, dmem, current))
        except Exception:  # noqa: BLE001 - 不认识的名字就保持原样，绝不炸推理
            pass

    return model.register_forward_pre_hook(guard, with_kwargs=True)


def restore_attention(model, prev: str) -> None:
    _set_impl(model, prev or "sdpa")


def _set_impl(model, name: str) -> None:
    cfg = getattr(model, "config", None)
    targets = [cfg]
    text_cfg = getattr(cfg, "text_config", None) if cfg is not None else None
    if text_cfg is not None:
        targets.append(text_cfg)
    for item in targets:
        if item is not None and hasattr(item, "_attn_implementation"):
            item._attn_implementation = name


#: 语义更清楚的别名：临时切实现用（写记忆 / 定标）
set_plain = _set_impl
