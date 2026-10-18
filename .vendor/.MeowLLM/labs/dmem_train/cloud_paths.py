# -*- coding: utf-8 -*-
"""云端 / 本地路径的**唯一出处**。

这一条是硬约定，别的文件不要再写死任何远端路径：

    本地 = 权威。`.vendor/.MeowLLM/` 这一棵树里的配置文件（config.yml）一律用
    **相对模块根的路径**：
        models/Qwen3-0.6B
        models/dmem-261018/dmem.safetensors
        labs/dmem_train/data/sft.jsonl
        labs/dmem_train/out/<run>/

    云端 = 同一棵树，只换根：
        <REMOTE_ROOT>/models/Qwen3-0.6B
        <REMOTE_ROOT>/models/dmem-261018/dmem.safetensors
        <REMOTE_ROOT>/labs/dmem_train/data/sft.jsonl
        <REMOTE_ROOT>/labs/dmem_train/out/<run>/

于是**同一份 config.yml 在两边都能直接用**，上云时不需要改任何路径 ——
"转义"只发生在这一层：本地路径 -> 远端路径由 `remote()` 做，
远端命令里出现的目录一律从这里取。

随机器变化的只有两样，也都在这里：
    * 远端根       MEOWLLM_REMOTE_ROOT（默认 /root/autodl-tmp/MeowLLM）
    * 远端 python  MEOWLLM_REMOTE_PYTHON（默认 /root/miniconda3/bin/python3）
"""

from __future__ import annotations

import os
import posixpath

# ------------------------------------------------------------------ 本地树
HERE = os.path.dirname(os.path.abspath(__file__))          # .../labs/dmem_train
LABS = os.path.dirname(HERE)                               # .../labs
MODULE_ROOT = os.path.dirname(LABS)                        # .../.vendor/.MeowLLM
PROJECT_ROOT = os.path.dirname(os.path.dirname(MODULE_ROOT))

# ------------------------------------------------------------------ 相对路径
#: 权重目录（本地与云端同名同结构）
REL_MODELS = "models"
#: 训练代码目录
REL_TRAIN = "labs/dmem_train"
#: 训练数据（跟代码同级，这样上云时随 labs/dmem_train 一起走）
REL_DATA = "labs/dmem_train/data"
#: 训练产物（run 目录的父目录）
REL_OUT = "labs/dmem_train/out"
#: 本地 backbone（小模型，用来在本机验管道）
LOCAL_MODEL_REL = "models/Qwen3-0.6B"
#: 云端训练用 backbone（相对模块根 —— 与本地同一套相对路径）
DEFAULT_TRAIN_MODEL_REL = "models/Qwen3-8B"
#: 默认 run 名字（训练脚本与面板都认这个）
DEFAULT_RUN = "out/r64-ctx768-a2"

# ------------------------------------------------------------------ 实验台沙箱
#: 实验台（labs/launch.py）启动 MeowLLM 时用的独立目录。
#: 为什么需要：labs 起的是**同一个** meowllm.server.app、读的是**同一份** config.yml，
#: 如果不改这些目录，实验产生的 δ-mem 状态会直接写进主项目的
#: `character/userinfo/<uid>/mem/` —— 等于拿真人记忆做实验。
LAB_SANDBOX = "labs/.lab"
REL_LAB_STATE = LAB_SANDBOX + "/state"
REL_LAB_LOGS = LAB_SANDBOX + "/logs"
REL_LAB_USERINFO = LAB_SANDBOX + "/userinfo"


def lab_env(shared: bool = False) -> dict:
    """给实验台用的环境变量：把状态/日志/记忆全部挪进 labs/.lab/。

    `shared=True` 时返回空字典 —— 那是"我就是要用主项目的真实数据"，
    必须显式要求（launch.py --shared），不做默认。
    """
    if shared:
        return {}
    return {
        "MEOWLLM_STATE_DIR": REL_LAB_STATE,
        "MEOWLLM_LOG_DIR": REL_LAB_LOGS,
        "MEOWLLM__MEMORY__DELTA_MEM__USERINFO_DIR": REL_LAB_USERINFO,
    }

# ------------------------------------------------------------------ 远端
DEFAULT_REMOTE_ROOT = "/root/autodl-tmp/MeowLLM"
DEFAULT_REMOTE_PYTHON = "/root/miniconda3/bin/python3"
#: 云端 backbone 的落地根。**backbone 是机器自带的**，不在模块树里，
#: 所以 `models/Qwen3-8B` 到云端要翻译成 `<这个根>/Qwen3-8B`。
DEFAULT_REMOTE_MODELS = "/root/autodl-tmp/models"


def remote_root() -> str:
    """云端模块根（`.vendor/.MeowLLM` 的镜像）。可用环境变量覆盖。"""
    value = str(os.environ.get("MEOWLLM_REMOTE_ROOT") or "").strip()
    return (value or DEFAULT_REMOTE_ROOT).rstrip("/")


def remote_python() -> str:
    value = str(os.environ.get("MEOWLLM_REMOTE_PYTHON") or "").strip()
    return value or DEFAULT_REMOTE_PYTHON


def remote_bin_dir() -> str:
    """远端 python 所在目录（拼 PATH 用）。"""
    py = remote_python()
    return posixpath.dirname(py) or "/usr/local/bin"


def remote_models_root() -> str:
    value = str(os.environ.get("MEOWLLM_REMOTE_MODELS") or "").strip()
    return (value or DEFAULT_REMOTE_MODELS).rstrip("/")


def remote_model(rel: str = DEFAULT_TRAIN_MODEL_REL) -> str:
    """本地相对 `models/<name>` -> 云端**实际**的 backbone 位置。

    这是"云端自行转义"的那一步：模块自己的产物（dmem 权重、数据、out）跟着
    模块树走（`<REMOTE_ROOT>/models/<run>/`），而 backbone 是云机器本来就有的，
    在 `/root/autodl-tmp/models/` 下 —— 所以要换个根。
    """
    name = _posix(rel).lstrip("/")
    if name.startswith("models/"):
        name = name[len("models/"):]
    elif name.startswith(remote_models_root().lstrip("/") + "/"):
        return "/" + name
    return posixpath.join(remote_models_root(), name)


# ------------------------------------------------------------------ 转换
def _posix(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip()


def local(rel: str) -> str:
    """相对模块根 -> 本地绝对路径。"""
    text = _posix(rel)
    if not text:
        return MODULE_ROOT
    if os.path.isabs(text):
        return os.path.normpath(text)
    return os.path.normpath(os.path.join(MODULE_ROOT, text))


def remote(rel: str) -> str:
    """相对模块根 -> 远端绝对路径（posix）。"""
    text = _posix(rel).lstrip("/")
    if not text:
        return remote_root()
    # 已经带了正确前缀就不要再套一层
    root = remote_root()
    if text.startswith(root.lstrip("/") + "/"):
        return "/" + text
    return posixpath.join(root, text)


def model_rel(value: str | None = None) -> str:
    """把 CLI/配置里给的模型目录规整成"相对模块根"的写法。

    * 空 -> DEFAULT_TRAIN_MODEL_REL
    * 本地绝对路径且在模块根下 -> 剥成相对
    * 远端绝对路径（/root/...）-> 保留（用户显式指定的，尊重）
    * 其他 -> 原样（当相对路径用）
    """
    text = _posix(value)
    if not text:
        return DEFAULT_TRAIN_MODEL_REL
    for base in (MODULE_ROOT, LABS, PROJECT_ROOT):
        b = _posix(base).rstrip("/")
        if text.lower().startswith(b.lower() + "/"):
            return text[len(b) + 1:]
    return text


def out_rel(value: str | None = None) -> str:
    """把面板/CLI 给的 run 目录规整成"相对 labs/dmem_train"的写法。

    **这里是修过 bug 的地方**：以前 `webui.py` 把本地绝对路径
    (`D:\\.Meowlisis\\...\\out`) 直接交给 `remote.py` 的 `posixpath.join`，
    远端路径就变成 `/root/.../D:\\.Meowlisis\\...\\out` —— 面板明明有配置项，
    却永远读不到训练目录。规则改成：

        空 / "." / "out"            -> "out"
        本地绝对路径且在代码树里     -> 剥成相对 labs/dmem_train 的路径
        其他绝对路径（远端得不到）   -> 退回 "out"
        裸名字（r64-ctx768-a2）      -> "out/r64-ctx768-a2"
    """
    text = _posix(value)
    if text:
        for base in (HERE, LABS, MODULE_ROOT):
            b = _posix(base).rstrip("/")
            if text.lower().startswith(b.lower() + "/"):
                text = text[len(b) + 1:]
                break
        else:
            if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
                text = ""          # 远端没有这个目录，别把它拼进去
    text = text.strip("/")
    if not text or text == ".":
        return "out"
    if text == "out" or text.startswith("out/"):
        return text
    return "out/" + text


def python_hint() -> str:
    """本地 python 的推荐位置（`.Meowlisis/runtime/311`）。"""
    for name in ("311", "312"):
        cand = os.path.join(PROJECT_ROOT, "runtime", name, "python.exe")
        if os.path.isfile(cand):
            return cand
    return os.path.join(PROJECT_ROOT, "runtime", "311", "python.exe")
