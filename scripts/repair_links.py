# -*- coding: utf-8 -*-
"""重建打包时被排除的目录联接（junction）

分享包/完整包为了让模型只存一份，把 .vendor\\.ComfyNode\\ComfyUI\\models\\* 和
.vendor\\.gsvlite\\models\\* 这些联接目录排除在外，解压后需要重新建回来。

用法：
    python scripts\\repair_links.py             # 修复，幂等，可重复运行
    python scripts\\repair_links.py --dry-run   # 只看状态，不修改
    python scripts\\repair_links.py --quiet     # 正常时不输出，只报修复和错误
    python scripts\\repair_links.py --root D:\\path

规则：
    * 已经是活联接且指向正确，跳过
    * 真实目录里有文件，绝不删除（可能是旧包解压出来的实体副本），报告后跳过
    * 空目录或断掉的联接，删掉后重建
    * 目标落在 link 路径下面、或是链接本身，拒绝创建，避免自我引用
    * 每条建完都回读重解析点确认，不只信返回值
"""
import argparse
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_DIRECTORY = 0x10
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
GENERIC_WRITE = 0x40000000
FILE_SHARE_ALL = 0x7
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FSCTL_SET_REPARSE_POINT = 0x000900A4
FSCTL_GET_REPARSE_POINT = 0x000900A8
NEED_FIX = ("CREATE", "BROKEN", "REPLACE", "WRONG")

LINKS = [
    (r".vendor\.ComfyNode\ComfyUI\models\diffusion_models", r".vendor\.ComfyNode\models\diffusion_models"),
    (r".vendor\.ComfyNode\ComfyUI\models\text_encoders", r".vendor\.ComfyNode\models\text_encoders"),
    (r".vendor\.ComfyNode\ComfyUI\models\vae", r".vendor\.ComfyNode\models\vae"),
    (r".vendor\.ComfyNode\ComfyUI\models\loras", r".vendor\.ComfyNode\models\loras"),
    (r".vendor\.ComfyNode\ComfyUI\models\upscale_models", r".vendor\.ComfyNode\models\upscale_models"),
    (r".vendor\.ComfyNode\ComfyUI\models\ultralytics", r".vendor\.ComfyNode\models\ultralytics"),
    (r".vendor\.ComfyNode\ComfyUI\models\sams", r".vendor\.ComfyNode\models\sams"),
    (r".vendor\.ComfyNode\ComfyUI\output", r".vendor\.ComfyNode\output"),
    (r".vendor\.gsvlite\models\chinese-hubert-base", r".vendor\.Sovits\GPT_SoVITS\pretrained_models\chinese-hubert-base"),
    (r".vendor\.gsvlite\models\chinese-roberta-wwm-ext-large", r".vendor\.Sovits\GPT_SoVITS\pretrained_models\chinese-roberta-wwm-ext-large"),
    (r".vendor\.gsvlite\models\sv", r".vendor\.Sovits\GPT_SoVITS\pretrained_models\sv"),
]

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
_k32.GetFileAttributesW.restype = wintypes.DWORD
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_k32.DeviceIoControl.restype = wintypes.BOOL
_k32.RemoveDirectoryW.argtypes = [wintypes.LPCWSTR]
_k32.RemoveDirectoryW.restype = wintypes.BOOL
_k32.DeleteFileW.argtypes = [wintypes.LPCWSTR]
_k32.DeleteFileW.restype = wintypes.BOOL
_INVALID_HANDLE = wintypes.HANDLE(-1).value


def _norm(p):
    """规范化并转小写，用于比较"""
    return os.path.normcase(os.path.abspath(p))


def _attrs(path):
    """返回属性位，路径不存在返回 None"""
    a = _k32.GetFileAttributesW(path)
    if a == INVALID_FILE_ATTRIBUTES:
        return None
    return int(a)


def is_link(path):
    """是否为重解析点（联接或符号链接）"""
    a = _attrs(path)
    return a is not None and bool(a & FILE_ATTRIBUTE_REPARSE_POINT)


def is_dir(path):
    """是否为目录（不跟随联接）"""
    a = _attrs(path)
    return a is not None and bool(a & FILE_ATTRIBUTE_DIRECTORY)


def alive(path):
    """路径是否可访问，断掉的联接返回 False"""
    return _attrs(path) is not None


def dir_exists(path):
    """目录是否存在：走 GetFileAttributesW，不用 os.stat

    os.stat 在低完整性/受限令牌下对 .vendor 这类目录会直接失败并谎报不存在，
    而 GetFileAttributesW 能正确返回属性位，所以这里统一走 Win32。
    """
    return is_dir(path)


def read_target(path):
    """读取联接指向的目标，失败返回 None"""
    h = _k32.CreateFileW(path, 0, FILE_SHARE_ALL, None, OPEN_EXISTING,
                         FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, None)
    if h == _INVALID_HANDLE:
        return None
    try:
        buf = ctypes.create_string_buffer(16 * 1024)
        got = wintypes.DWORD(0)
        if not _k32.DeviceIoControl(h, FSCTL_GET_REPARSE_POINT, None, 0,
                                    buf, len(buf), ctypes.byref(got), None):
            return None
        raw = buf.raw[:got.value]
        if len(raw) < 16:
            return None
        if int.from_bytes(raw[0:4], "little") != IO_REPARSE_TAG_MOUNT_POINT:
            return None
        sub = raw[16:].decode("utf-16-le", "ignore")
        if not sub.startswith("\\??\\"):
            return None
        return sub[4:].split("\x00", 1)[0]
    finally:
        _k32.CloseHandle(h)


def make_junction(link, target):
    """用 FSCTL_SET_REPARSE_POINT 创建目录联接，返回 (成功, 错误)"""
    target_abs = os.path.abspath(target)
    sub_b = ("\\??\\" + target_abs).encode("utf-16-le")
    name_b = target_abs.encode("utf-16-le")
    path_buf = sub_b + b"\x00\x00"
    name_buf = name_b + b"\x00\x00"
    pad = (-len(sub_b)) % 2
    body_len = 8 + len(path_buf) + pad + 8 + len(name_buf)
    buf = bytearray()
    buf += IO_REPARSE_TAG_MOUNT_POINT.to_bytes(4, "little")
    buf += body_len.to_bytes(2, "little")
    buf += b"\x00\x00"
    buf += (0).to_bytes(2, "little")
    buf += len(sub_b).to_bytes(2, "little")
    buf += len(path_buf).to_bytes(2, "little")
    buf += len(name_buf).to_bytes(2, "little")
    buf += path_buf
    buf += b"\x00" * pad
    buf += (0).to_bytes(4, "little")
    buf += len(name_buf).to_bytes(2, "little")
    buf += name_buf

    h = _k32.CreateFileW(link, GENERIC_WRITE, FILE_SHARE_ALL, None, OPEN_EXISTING,
                         FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, None)
    if h == _INVALID_HANDLE:
        return False, "CreateFile failed: %d" % ctypes.get_last_error()
    try:
        data = (ctypes.c_char * len(buf)).from_buffer(buf)
        got = wintypes.DWORD(0)
        if not _k32.DeviceIoControl(h, FSCTL_SET_REPARSE_POINT, data, len(buf),
                                    None, 0, ctypes.byref(got), None):
            return False, "DeviceIoControl failed: %d" % ctypes.get_last_error()
        return True, ""
    finally:
        _k32.CloseHandle(h)


def make_junction_cmd(link, target):
    """回退方案：mklink /J，返回 (成功, 错误)"""
    try:
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                           capture_output=True, text=True, timeout=20,
                           encoding="mbcs", errors="ignore")
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or r.stdout or "").strip()
    except Exception as e:
        return False, str(e)


def remove_entry(path):
    """删除链接或空目录，绝不递归，返回 (成功, 错误)"""
    if is_dir(path):
        if _k32.RemoveDirectoryW(path):
            return True, ""
        return False, "RemoveDirectory failed: %d" % ctypes.get_last_error()
    if _k32.DeleteFileW(path):
        return True, ""
    return False, "DeleteFile failed: %d" % ctypes.get_last_error()


def dir_entries(path):
    """列出目录条目，读不到返回 None（表示未知，绝不能当成空）"""
    try:
        return os.listdir(path)
    except OSError:
        return None


def same_target(link, target):
    """链接是否真的指向目标：用 realpath 比较，避开 \\??\\ 与 Global\\ 前缀差异"""
    try:
        if _norm(os.path.realpath(link)) == _norm(os.path.realpath(target)):
            return True
    except OSError:
        pass
    raw = read_target(link)
    if not raw:
        return False
    clean = raw
    if clean.startswith("Global\\"):
        clean = clean[len("Global\\"):]
    return _norm(clean) == _norm(os.path.abspath(target))


def unsafe_target(link, target):
    """目标会自我引用时返回原因，安全返回空串"""
    lt = _norm(link)
    tt = _norm(target)
    if tt == lt:
        return "target equals the link itself"
    if tt.startswith(lt + os.sep):
        return "target lives inside the link"
    if is_link(target):
        return "target is itself a junction"
    return ""


def plan(root):
    """逐个检查链接，返回 (状态, link, target, 说明)"""
    out = []
    for link_rel, target_rel in LINKS:
        link = os.path.join(root, link_rel)
        target = os.path.join(root, target_rel)
        target_exists = dir_exists(target)
        link_exists = _attrs(link) is not None

        if not target_exists:
            out.append(("SKIP", link_rel, target_rel, "target missing"))
        elif not link_exists:
            out.append(("CREATE", link_rel, target_rel, "missing"))
        elif is_link(link) and alive(link):
            if same_target(link, target):
                out.append(("OK", link_rel, target_rel, ""))
            else:
                out.append(("WRONG", link_rel, target_rel, "points at " + str(read_target(link))))
        elif is_link(link):
            out.append(("BROKEN", link_rel, target_rel, "link target unreachable"))
        elif is_dir(link):
            items = dir_entries(link)
            if items is None:
                out.append(("KEEP", link_rel, target_rel, "real directory, cannot enumerate"))
            elif items:
                out.append(("KEEP", link_rel, target_rel, "real directory, %d entries" % len(items)))
            else:
                out.append(("REPLACE", link_rel, target_rel, "empty real directory"))
        else:
            out.append(("BLOCKED", link_rel, target_rel, "a file sits at the link path"))
    return out


def fix_one(root, link_rel, target_rel):
    """修复单条链接并回读验证，返回 (成功, 消息)"""
    link = os.path.join(root, link_rel)
    target = os.path.join(root, target_rel)
    why = unsafe_target(link, target)
    if why:
        return False, why
    try:
        os.makedirs(os.path.dirname(link), exist_ok=True)
    except OSError as e:
        return False, "cannot create parent dir: %s" % e
    entries = dir_entries(link)
    if is_link(link) or (is_dir(link) and entries == []):
        ok, err = remove_entry(link)
        if not ok:
            return False, err
    elif _attrs(link) is not None:
        if is_dir(link) and entries is None:
            return False, "real directory but cannot enumerate, left untouched"
        return False, "path occupied and not removable"
    ok, err = make_junction(link, target)
    if not ok:
        ok, err2 = make_junction_cmd(link, target)
        if not ok:
            return False, "%s / %s" % (err, err2)
    if not same_target(link, target):
        return False, "created but points at %s" % str(read_target(link))
    if not alive(link):
        return False, "linked but not reachable"
    return True, ""


def main(argv=None):
    """命令行入口"""
    ap = argparse.ArgumentParser(description="重建打包时排除的目录联接")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if os.name != "nt":
        print("[repair_links] Windows only")
        return 1
    root = os.path.abspath(args.root)
    if not os.path.isfile(os.path.join(root, "api.py")):
        print("[repair_links] project root not found (no api.py): %s" % root)
        return 1

    items = plan(root)
    todo = [i for i in items if i[0] in NEED_FIX]

    if args.dry_run:
        print("[repair_links] %s" % root)
        for st, link, target, note in items:
            print("  %-8s %s%s" % (st, link, ("  (" + note + ")") if note else ""))
        print("  %d need repair" % len(todo))
        return 0

    fixed = 0
    failed = 0
    for st, link, target, note in todo:
        ok, msg = fix_one(root, link, target)
        if ok:
            fixed += 1
            print("  rebuilt %s" % link)
        else:
            failed += 1
            print("  [FAIL] %s - %s" % (link, msg))
    for st, link, target, note in items:
        if st in ("KEEP", "BLOCKED"):
            print("  [WARN] %s - %s" % (link, note))
        elif st == "SKIP" and not args.quiet:
            print("  [skip] %s - %s" % (link, note))

    remain = [i for i in plan(root) if i[0] in NEED_FIX]
    if failed or remain:
        print("  [WARN] %d link(s) not ready, the engine may not find its models" % max(failed, len(remain)))
        return 1
    if not args.quiet and not fixed:
        print("  %d link(s) fine, nothing to do" % len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
