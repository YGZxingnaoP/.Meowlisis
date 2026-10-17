# -*- coding: utf-8 -*-
"""登进 AutoDL 云实例，做一次只读体检，重点回答：**云端现在是不是量化模型**。

安全约定
--------
* 密码只从文件读取，**绝不打印**（长度也不打印，只报"已读到 N 字节"以外的信息）。
* 只跑只读命令：`nvidia-smi` / `df` / `free` / `find` / `pip list` / `python -c`。
  不下载、不安装、不改文件。

用法（在 .vendor/.MeowLLM 目录下）
---------------------------------
    ..\\..\\runtime\\311\\python.exe .scripts\\cloud_probe.py
    ..\\..\\runtime\\311\\python.exe .scripts\\cloud_probe.py --cmd "nvidia-smi -L"

判定规则（脚本末尾会打印结论）
------------------------------
* 找到 `.gguf`                -> GGUF 量化（Q4_K_M 之类写在文件名里）
* 找到 config.json 且含 quantization_config -> 权重是量化的（bnb / awq / gptq / fp8）
* 只有 .safetensors 且无 quant 配置        -> **未量化**（bf16/fp16 原版）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

MODULE_ROOT = Path(__file__).resolve().parents[1]
def _autodl_dir() -> Path:
    """凭据目录：优先 labs/autoDL，退回模块根的 autoDL。"""
    for cand in (MODULE_ROOT / "labs" / "autoDL", MODULE_ROOT / "autoDL"):
        if cand.is_dir():
            return cand
    return MODULE_ROOT / "autoDL"


AUTODL_DIR = _autodl_dir()

#: 密码文件名候选（不区分大小写由 _find 处理）
PASSWORD_NAMES = ("密码.txt", "password.txt", "passwd.txt", "密码", "password")

#: 关心的推理/量化库
LIBS = ("vllm", "transformers", "bitsandbytes", "autoawq", "awq", "gptqmodel",
        "gptq", "ctranslate2", "llama-cpp-python", "llama_cpp", "sglang",
        "xformers", "flash-attn", "accelerate", "peft", "torch", "triton",
        "optimum", "quanto", "hqq", "exllamav2", "mlx")

#: 模型搜索根目录
SEARCH_ROOTS = ("/root", "/autodl-tmp", "/root/autodl-tmp", "/root/.cache/huggingface",
                "/data", "/mnt")


def find_file(names: tuple[str, ...]) -> Path | None:
    """在 autoDL 目录里按候选名找文件（忽略大小写）。"""
    if not AUTODL_DIR.is_dir():
        return None
    lowered = {n.lower() for n in names}
    for item in AUTODL_DIR.iterdir():
        if item.is_file() and item.name.lower() in lowered:
            return item
    # 退一步：文件名里含"密码"或"pass"的都算
    for item in AUTODL_DIR.iterdir():
        if item.is_file() and ("密码" in item.name or "pass" in item.name.lower()):
            return item
    return None


def parse_login() -> tuple[str, int, str] | None:
    """从 登录指令.txt 解析出 (user, port, host)。"""
    path = AUTODL_DIR / "登录指令.txt"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    # 形如：ssh -p 43080 root@connect.weste.seetacloud.com
    port_match = re.search(r"-p\s+(\d+)", text)
    host_match = re.search(r"(?:^|\s)([\w.\-]+@[\w.\-]+)", text)
    if not port_match or not host_match:
        return None
    user, host = host_match.group(1).split("@", 1)
    return user, int(port_match.group(1)), host


def run(client, cmd: str, timeout: int = 120) -> tuple[int, str]:
    """执行一条远端命令，返回 (退出码, 合并后的输出)。"""
    try:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return code, (out + err).strip()
    except Exception as exc:  # noqa: BLE001
        return 1, f"<命令失败: {type(exc).__name__}: {exc}>"


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n== {title}\n{'=' * 72}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cmd", default=None, help="只跑这一条命令（调试用）")
    parser.add_argument("--cmd-file", default=None,
                        help="只跑这个本地文件里的内容（避免命令行引号被吃掉）")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    try:
        import paramiko
    except Exception as exc:  # noqa: BLE001
        print(f"缺少 paramiko：{exc}\n安装：..\\..\\runtime\\311\\python.exe -m pip install paramiko")
        return 2

    login = parse_login()
    if not login:
        print(f"无法从 {AUTODL_DIR / '登录指令.txt'} 解析出 host/port")
        return 2
    user, port, host = login

    pw_path = find_file(PASSWORD_NAMES)
    if not pw_path:
        print(f"找不到密码文件。请在 {AUTODL_DIR} 下放一个 密码.txt（只放密码一行）")
        return 2
    password = pw_path.read_text(encoding="utf-8", errors="replace").strip()
    if not password:
        print(f"密码文件是空的：{pw_path.name}")
        return 2
    print(f"目标   : {user}@{host}:{port}")
    print(f"密码   : 已从 {pw_path.name} 读取（{len(password)} 字符，不显示）")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("连接中…")
    try:
        client.connect(hostname=host, port=port, username=user, password=password,
                       timeout=25, auth_timeout=25, banner_timeout=25,
                       allow_agent=False, look_for_keys=False)
    except Exception as exc:  # noqa: BLE001
        print(f"连接失败：{type(exc).__name__}: {exc}")
        print("若是认证失败，检查密码；若是超时，确认实例已开机（不是无卡模式）")
        return 3
    print("已连接。")

    try:
        if args.cmd_file:
            args.cmd = Path(args.cmd_file).read_text(encoding="utf-8")
        if args.cmd:
            code, out = run(client, args.cmd, args.timeout or 180)
            print(out)
            return 0 if code == 0 else 1

        # ---------------------------------------------------------- 1 硬件
        section("1. GPU（无卡模式下这里会失败，是正常的）")
        code, out = run(client, "nvidia-smi --query-gpu=name,memory.total,driver_version,"
                                "compute_cap --format=csv,noheader 2>&1 || nvidia-smi 2>&1", 60)
        print(out or "<无输出>")
        section("1b. CUDA 运行时")
        code, out = run(client, "nvidia-smi -L 2>&1 | head -5", 30)
        print(out or "<无输出>")

        # ---------------------------------------------------------- 2 系统
        section("2. 系统与资源")
        code, out = run(client, "uname -sr; echo '---'; nproc; echo '---'; "
                                "free -g | head -2; echo '---'; df -h / /root /autodl-tmp 2>/dev/null | head -8", 60)
        print(out or "<无输出>")

        # ---------------------------------------------------------- 3 Python
        section("3. Python / PyTorch")
        code, out = run(client,
                        "python -V 2>&1; which python; echo '---'; "
                        "python - <<'PY' 2>&1\n"
                        "import torch\n"
                        "print('torch      =', torch.__version__)\n"
                        "print('cuda build =', torch.version.cuda)\n"
                        "print('available  =', torch.cuda.is_available())\n"
                        "if torch.cuda.is_available():\n"
                        "    print('device     =', torch.cuda.get_device_name(0))\n"
                        "    free, total = torch.cuda.mem_get_info()\n"
                        "    print('vram       = %.1f / %.1f GB' % (free/1e9, total/1e9))\n"
                        "    print('capability =', torch.cuda.get_device_capability(0))\n"
                        "PY", 180)
        print(out or "<无输出>")

        # ---------------------------------------------------------- 4 库
        section("4. 推理/量化相关的库")
        code, out = run(client, "pip list 2>/dev/null | head -400", 120)
        found = {}
        for line in (out or "").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0].lower()
                for lib in LIBS:
                    if name == lib.lower():
                        found[lib] = parts[1]
        if found:
            for lib in LIBS:
                if lib in found:
                    print(f"  {lib:<20} {found[lib]}")
        else:
            print("  <没有匹配到任何推理/量化库>")
        missing = [lib for lib in LIBS if lib not in found]
        if missing:
            print(f"  未安装：{', '.join(missing)}")

        # ---------------------------------------------------------- 5 模型文件
        section("5. 模型文件（关键：看有没有量化格式）")
        find_cmd = (
            "for d in /root /autodl-tmp /root/autodl-tmp /root/.cache/huggingface /data /mnt; do "
            "  [ -d \"$d\" ] || continue; "
            "  find \"$d\" -maxdepth 5 -type f \\( "
            "      -name '*.gguf' -o -name '*.safetensors' -o -name '*.bin' "
            "      -o -name '*.awq' -o -name '*.gptq' -o -name 'config.json' "
            "  \\) -size +50M -printf '%s\\t%p\\n' 2>/dev/null; "
            "done | sort -rn | head -40"
        )
        code, out = run(client, find_cmd, 180)
        files = []
        for line in (out or "").splitlines():
            if "\t" in line:
                size, path = line.split("\t", 1)
                try:
                    files.append((int(size), path))
                except ValueError:
                    pass
        if files:
            for size, path in files:
                print(f"  {size / 1e9:7.2f} GB  {path}")
        else:
            print("  <没找到 >50MB 的模型文件>")

        # ---------------------------------------------------------- 6 量化配置
        section("6. 量化配置（读 config.json 里的 quantization_config）")
        cfg_paths = [p for _, p in files if p.endswith("config.json")][:10]
        if not cfg_paths:
            print("  <没找到 config.json>")
        for path in cfg_paths:
            code, out = run(client, f"cat '{path}' 2>/dev/null", 30)
            try:
                cfg = json.loads(out)
            except Exception:  # noqa: BLE001
                print(f"  {path}: 读取失败")
                continue
            quant = cfg.get("quantization_config")
            dtype = cfg.get("torch_dtype") or cfg.get("dtype")
            model_type = cfg.get("model_type")
            arch = cfg.get("architectures")
            print(f"  {path}")
            print(f"    model_type={model_type}  dtype={dtype}  arch={arch}")
            print(f"    quantization_config={json.dumps(quant, ensure_ascii=False) if quant else 'None'}")
            if "quantization_config" in cfg and not quant:
                print("    （存在该键但为空 -> 未量化或按需量化）")

        # ---------------------------------------------------------- 7 结论
        section("7. 结论：云端到底是不是量化模型")
        gguf = [p for _, p in files if p.endswith(".gguf")]
        quant_cfg = []
        for path in cfg_paths:
            code, out = run(client, f"grep -o '\"quantization_config\"' '{path}' 2>/dev/null", 20)
            if out.strip():
                quant_cfg.append(path)
        st = [p for _, p in files if p.endswith(".safetensors")]
        bn = [p for _, p in files if p.endswith(".bin")]

        print(f"  .gguf 文件      : {len(gguf)}")
        print(f"  .safetensors    : {len(st)}")
        print(f"  .bin            : {len(bn)}")
        print(f"  含 quant 配置的 config.json : {len(quant_cfg)}")

        if gguf:
            print("  >>> 判定：**是量化模型**（GGUF 格式，量化等级通常写在文件名里，如 Q4_K_M）")
        elif quant_cfg:
            print("  >>> 判定：**是量化模型**（权重目录声明了 quantization_config）")
        elif st:
            print("  >>> 判定：**不是量化模型**（只有 .safetensors，按 config.json 的 dtype 是 bf16/fp16 原版）")
        else:
            print("  >>> 判定：**看不到模型**（可能还没下载/挂载）")

        print("\n提示：AutoDL 的镜像里常见的是 bf16 原版；量化通常要自己转或下 GPTQ/AWQ/GGUF。")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
