# -*- coding: utf-8 -*-
"""δ-mem 的状态存储：**一套参数，每用户一个独立目录，彼此零交叉**。

目录（layout="userinfo"，默认）
------------------------------
    character/userinfo/<uid>/mem/
    ├── delta_mem.pt          状态本体（bf16，r=64/28 层 ≈ 224KB）
    ├── delta_mem.meta.json   指纹 + 衰减时间 + 写入日志
    ├── sources/<ts>.md       喂进去的原文快照（默认留 3 份，可追溯/可重建）
    └── .lock                 写入锁（多进程互斥）

    character/userinfo/<uid>/ 下**只属于这一个用户**：删目录即彻底删除该用户的记忆。
    任何 owner 的读写只会落在它自己的 mem/ 里，跨用户串门在物理上不可能发生
    （路径由 `_owner_dir()` 拼，且带越界断言）。

layout="flat"（旧格式，只为兼容与迁移）
--------------------------------------
    <flat_dir>/<uid>.pt

安全约定
--------
1. **指纹**：meta 里存 `cfg_fingerprint`（rank/N/chunk/layers）与 `weights_sha1`。
   换权重或改结构后旧状态**拒绝加载**（否则不报错，只静默输出垃圾）。
2. **原子写**：先写 `.tmp` 再 `os.replace`，避免断电/被杀留下半个文件。
3. **正式用户**：默认只认 `^\\d{6}$`（000001…），`temp-*` 一律不落盘、不加载。
4. **并发**：`write()` 拿 `.lock`；拿不到就跳过本次（下一轮再写），不阻塞生成。

与 mem0 的对应
--------------
    mem0.user_id            -> owner
    mem0.add(text)          -> write(owner, ids)
    mem0 的向量库文件        -> <uid>/mem/delta_mem.pt
    mem0.delete_all(user)   -> forget(owner)（连 mem/ 目录一起删）
    mem0.search(query)      -> 不需要：生成时状态自动参与 attention
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from collections import OrderedDict

import torch

from meowllm.errors import MeowLLMContractError

log = logging.getLogger("meowllm.dmem.registry")

FORMAL_PATTERN = r"^\d{6}$"
MAX_SOURCE_SNAPSHOTS = 3


def _safe_name(owner: str) -> str:
    """uid -> 安全目录名（不含分隔符/冒号/点）。"""
    text = str(owner or "").strip()
    keep = [ch if (ch.isalnum() or ch in "-_") else "_" for ch in text]
    return ("".join(keep)[:64]) or "_anonymous"


class DmemRegistry:
    def __init__(self, dmem, *, layout: str = "userinfo", userinfo_dir: str = "",
                 flat_dir: str = "", formal_pattern: str = FORMAL_PATTERN,
                 strict_formal: bool = True, max_cached: int = 8,
                 persist: bool = True, weights_sha1: str = "",
                 backup_keep: int = 5) -> None:
        self.dmem = dmem
        self.layout = "flat" if str(layout).lower() == "flat" else "userinfo"
        self.userinfo_dir = userinfo_dir
        self.flat_dir = flat_dir
        self.formal_re = re.compile(str(formal_pattern or FORMAL_PATTERN))
        self.strict_formal = bool(strict_formal)
        self.max_cached = max(1, int(max_cached))
        self.persist = bool(persist)
        self.weights_sha1 = str(weights_sha1 or "")
        self.backup_keep = max(0, int(backup_keep))
        self._cache: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.RLock()
        self._current: str | None = None
        self._stale: set[str] = set()
        self._stats = {"writes": 0, "hits": 0, "misses": 0, "evictions": 0,
                       "write_seconds": 0.0, "tokens": 0, "rejected": 0,
                       "stale": 0}
        if self.persist:
            try:
                os.makedirs(self._root(), exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                log.warning("δ-mem 状态目录不可写（%s），退化为纯内存：%s",
                            self._root(), exc)
                self.persist = False

    # ------------------------------------------------------------ 用户判定
    def is_formal(self, owner: str) -> bool:
        """是不是"该长期记忆的人"。

        规则（集中这一处，别散落到调用方）：
            * 空 -> False
            * temp 开头 -> False（临时会话不留记忆）
            * 匹配 formal_pattern -> True
            * 其余：strict_formal 时 False，否则放行（测试/调试用）
        """
        text = str(owner or "").strip()
        if not text:
            return False
        if text.lower().startswith("temp"):
            return False
        if self.formal_re.match(text):
            return True
        return not self.strict_formal

    # ------------------------------------------------------------ 路径
    def _root(self) -> str:
        return self.flat_dir if self.layout == "flat" else self.userinfo_dir

    def _owner_dir(self, owner: str) -> str:
        """某用户的状态目录。**唯一的路径拼装点**，带越界断言。"""
        root = os.path.abspath(self._root() or ".")
        if self.layout == "flat":
            path = os.path.join(root, _safe_name(owner))
            return path
        # <userinfo>/<uid>/mem
        path = os.path.join(root, _safe_name(owner), "mem")
        if not os.path.abspath(path).startswith(root + os.sep):
            raise ValueError(f"owner={owner!r} 解析出的路径越界：{path}")
        return path

    def path_of(self, owner: str) -> str:
        if self.layout == "flat":
            return os.path.join(self.flat_dir, f"{_safe_name(owner)}.pt")
        return os.path.join(self._owner_dir(owner), "delta_mem.pt")

    def meta_path_of(self, owner: str) -> str:
        if self.layout == "flat":
            return os.path.join(self.flat_dir, f"{_safe_name(owner)}.meta.json")
        return os.path.join(self._owner_dir(owner), "delta_mem.meta.json")

    def sources_dir(self, owner: str) -> str:
        if self.layout == "flat":
            return os.path.join(self.flat_dir, f"{_safe_name(owner)}.sources")
        return os.path.join(self._owner_dir(owner), "sources")

    def exists(self, owner: str) -> bool:
        return owner in self._cache or (self.persist and os.path.isfile(self.path_of(owner)))

    # ------------------------------------------------------------ 指纹
    def _fingerprint(self) -> dict:
        return {
            "schema": 1,
            "cfg_fingerprint": (f"r{self.dmem.cfg.rank}-n{self.dmem.cfg.n_states}"
                                f"-c{self.dmem.cfg.chunk}"
                                f"-L{'-'.join(str(x) for x in self.dmem.module_names[:1])}"
                                f"{'all' if len(self.dmem.module_names) else 'none'}"),
            "weights_sha1": self.weights_sha1,
            "layers": len(self.dmem.module_names),
        }

    def _check_fingerprint(self, meta: dict) -> tuple[bool, str]:
        """状态与当前权重/结构是否匹配。不匹配就拒绝加载（不要静默用错）。"""
        want = self._fingerprint()
        got = {k: meta.get(k) for k in ("cfg_fingerprint", "weights_sha1")}
        if not got.get("cfg_fingerprint"):
            return False, "meta 缺 cfg_fingerprint"
        if got["cfg_fingerprint"] != want["cfg_fingerprint"]:
            return False, (f"结构变了：{got['cfg_fingerprint']} != "
                           f"{want['cfg_fingerprint']}")
        if want["weights_sha1"] and got.get("weights_sha1") \
                and got["weights_sha1"] != want["weights_sha1"]:
            return False, "权重变了（sha1 不一致）"
        return True, ""

    # ------------------------------------------------------------ 切换
    def use(self, owner: str | None) -> bool:
        """切到某 owner 的状态；返回 True 表示这次生成真的挂上了记忆。"""
        with self._lock:
            if not owner or not self.is_formal(owner):
                if owner:
                    self._stats["rejected"] += 1
                    log.info("δ-mem 跳过非正式用户：%r（不加载、不落盘）", owner)
                self.dmem.clear_state()
                self._current = None
                self.dmem.enabled = False
                return False
            states = self._cache.get(owner)
            if states is None:
                states = self._load(owner)
                if states is None:
                    self._stats["misses"] += 1
                    # 这里必须留痕：否则"第一次聊天没记忆"和"状态文件坏了被拒加载"
                    # 在外部看起来完全一样（都是 enabled:false 且没有日志）。
                    log.info("δ-mem 该用户还没有可用状态（owner=%s，路径 %s）——"
                             "首次对话属正常，如果之前写过就要看 meta 指纹/损坏日志",
                             owner, self.path_of(owner))
                    self.dmem.clear_state()
                    self._current = owner
                    self.dmem.enabled = False
                    return False
                self._cache[owner] = states
            self._cache.move_to_end(owner)
            self._evict()
            self.dmem.states = dict(states)
            self.dmem.enabled = True
            self._current = owner
            self._stats["hits"] += 1
            return True

    # ------------------------------------------------------------ 写入
    def write(self, owner: str, ids: list[int], model, device=None,
              mode: str = "replace", keep_graph: bool = False,
              source_text: str = "", source_tag: str = "") -> dict:
        if not self.is_formal(owner):
            self._stats["rejected"] += 1
            # 用契约异常（400）而不是裸 ValueError：routes_control 只 catch
            # MeowLLMError，裸 ValueError 会一路冒成 500，把"参数不对"报成"服务坏了"。
            raise MeowLLMContractError(
                f"拒绝为非正式用户写记忆：{owner!r}（要匹配 formal_pattern"
                f" {self.formal_re.pattern!r}；temp-* 一律不落盘）")
        with self._lock:
            base = None
            if mode == "append":
                base = self._cache.get(owner) or self._load(owner)
                if base is not None:
                    self.dmem.states = dict(base)
            self.dmem.enabled = False          # 写的时候不叠加 steering
            started = time.perf_counter()
            stat = self.dmem.write_state(model, ids, device=device,
                                         keep_graph=keep_graph)
            elapsed = time.perf_counter() - started
            states = dict(self.dmem.states)
            self._cache[owner] = states
            self._cache.move_to_end(owner)
            self._evict()
            self._current = owner
            self._stats["writes"] += 1
            self._stats["tokens"] += int(stat.get("tokens") or 0)
            self._stats["write_seconds"] += elapsed
            if self.persist:
                self._save(owner, states, mode=mode, tokens=int(stat.get("tokens") or 0),
                           source_text=source_text, source_tag=source_tag)
            return {**stat, "owner": owner, "mode": mode,
                    "seconds": round(elapsed, 3), "dir": self._owner_dir(owner)}

    # ------------------------------------------------------------ 删除
    def forget(self, owner: str, remove_dir: bool = True) -> bool:
        """删除某用户的记忆（连 mem/ 目录一起），其余用户不受影响。"""
        with self._lock:
            existed = owner in self._cache
            self._cache.pop(owner, None)
            removed_files = 0
            if self.persist:
                target = self._owner_dir(owner) if remove_dir else None
                if target and os.path.isdir(target):
                    for name in os.listdir(target):
                        path = os.path.join(target, name)
                        try:
                            if os.path.isfile(path):
                                os.remove(path)
                                removed_files += 1
                            elif os.path.isdir(path):
                                for sub in os.listdir(path):
                                    os.remove(os.path.join(path, sub))
                                    removed_files += 1
                                os.rmdir(path)
                        except OSError:
                            pass
                    try:
                        os.rmdir(target)
                    except OSError:
                        pass
                    existed = True
                else:
                    flat = self.path_of(owner)
                    if os.path.isfile(flat):
                        try:
                            os.remove(flat)
                            removed_files += 1
                            existed = True
                        except OSError:
                            pass
            if self._current == owner:
                self.dmem.clear_state()
                self.dmem.enabled = False
                self._current = None
            self._stale.discard(owner)
            return existed or removed_files > 0

    # ------------------------------------------------------------ 落盘
    def _save(self, owner: str, states: dict, *, mode: str = "replace",
              tokens: int = 0, source_text: str = "", source_tag: str = "") -> None:
        folder = os.path.dirname(self.path_of(owner))
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            log.warning("δ-mem 目录建不了（%s）：%s", folder, exc)
            self.persist = False
            return
        lock = self._acquire_lock(folder)
        if lock is None:
            log.info("δ-mem 写入跳过（%s 被别的进程占着）", owner)
            return
        try:
            payload = {f"layer{k}": v.detach().to(torch.bfloat16).cpu()
                       for k, v in states.items()}
            target = self.path_of(owner)
            tmp = target + ".tmp"
            torch.save({"states": payload, "cfg": self.dmem.cfg.to_dict(),
                        "saved_at": time.time()}, tmp)
            os.replace(tmp, target)                    # 原子替换
            self._write_meta(owner, tokens=tokens, mode=mode,
                             source_text=source_text, source_tag=source_tag)
        except Exception as exc:  # noqa: BLE001
            log.warning("δ-mem 保存失败（%s）：%s", owner, exc)
        finally:
            self._release_lock(lock)

    def _write_meta(self, owner: str, *, tokens: int, mode: str,
                    source_text: str = "", source_tag: str = "") -> None:
        path = self.meta_path_of(owner)
        meta = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh) or {}
            except Exception:  # noqa: BLE001
                meta = {}
        fp = self._fingerprint()
        meta.update({"schema": fp["schema"],
                     "cfg_fingerprint": fp["cfg_fingerprint"],
                     "weights_sha1": fp["weights_sha1"],
                     "layers": fp["layers"],
                     "owner": owner,
                     "written_tokens": int(meta.get("written_tokens") or 0) + int(tokens),
                     "written_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        meta.setdefault("last_decay_at", meta["written_at"][:10])   # 衰减用（未实现）
        writes = list(meta.get("writes") or [])
        writes.append({"at": meta["written_at"], "tokens": int(tokens),
                       "mode": mode, "src": source_tag or "unknown"})
        meta["writes"] = writes[-20:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        self._backup(owner)
        if source_text:
            self._write_source(owner, source_text, source_tag or "unknown")

    def _backup(self, owner: str) -> None:
        """每用户本地快照：<uid>/mem/backup/<时间>/，只留最近 N 份。

        为什么按用户而做全局备份：整份归档会随用户数线性膨胀，而回滚几乎总是
        针对"某一个人"。全局归档另有 `labs/dmem/backup_states.py`。
        """
        keep = max(0, int(getattr(self, "backup_keep", 5) or 0))
        if not keep:
            return
        folder = os.path.join(self._owner_dir(owner), "backup")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = os.path.join(folder, stamp)
        try:
            os.makedirs(target, exist_ok=True)
            src = self.path_of(owner)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(target, "delta_mem.pt"))
            meta = self.meta_path_of(owner)
            if os.path.isfile(meta):
                shutil.copy2(meta, os.path.join(target, "delta_mem.meta.json"))
            snaps = sorted(d for d in os.listdir(folder)
                           if os.path.isdir(os.path.join(folder, d)))
            for old in snaps[:-keep]:
                shutil.rmtree(os.path.join(folder, old), ignore_errors=True)
        except OSError as exc:
            log.debug("δ-mem 快照失败（%s）：%s", owner, exc)

    def _write_source(self, owner: str, text: str, tag: str) -> None:
        """留原文快照：状态是可压缩的隐表示，"它到底看了什么"只能靠这个追溯。"""
        folder = self.sources_dir(owner)
        try:
            os.makedirs(folder, exist_ok=True)
            name = time.strftime("%Y-%m-%dT%H-%M-%S") + f"_{_safe_name(tag)[:16]}.md"
            with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                fh.write(text)
            snaps = sorted(os.listdir(folder))
            for old in snaps[:-MAX_SOURCE_SNAPSHOTS]:
                try:
                    os.remove(os.path.join(folder, old))
                except OSError:
                    pass
        except OSError:
            pass

    def _load(self, owner: str) -> dict | None:
        if not self.persist:
            return None
        path = self.path_of(owner)
        if not os.path.isfile(path):
            return None
        meta = self._read_meta(owner)
        ok, why = self._check_fingerprint(meta)
        if not ok:
            self._stats["stale"] += 1
            self._stale.add(owner)
            log.warning("δ-mem 状态与当前模型不匹配，拒绝加载（owner=%s）：%s", owner, why)
            return None
        try:
            blob = torch.load(path, map_location="cpu", weights_only=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("δ-mem 状态读取失败（%s）：%s", owner, exc)
            return None
        states = {}
        for key, value in (blob.get("states") or {}).items():
            states[int(str(key).replace("layer", ""))] = value.to(torch.float32)
        return states or None

    def _read_meta(self, owner: str) -> dict:
        path = self.meta_path_of(owner)
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh) or {}
        except Exception:  # noqa: BLE001
            return {}

    # ------------------------------------------------------------ 锁
    def _acquire_lock(self, folder: str):
        path = os.path.join(folder, ".lock")
        try:
            handle = open(path, "a+b")
        except OSError:
            return None
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return None
        return handle

    @staticmethod
    def _release_lock(handle) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()

    # ------------------------------------------------------------ 迁移
    def _evict(self) -> None:
        while len(self._cache) > self.max_cached:
            self._cache.popitem(last=False)
            self._stats["evictions"] += 1

    # ------------------------------------------------------------ 观测
    def stats(self) -> dict:
        with self._lock:
            # state_kb_per_owner：以前用 `self.dmem.states` 算，但那个字典只在
            # "正在服务某个 owner" 的瞬间才有内容，两次请求之间是空的 → 面板上永远
            # 显示 null。改成按**配置**推算，任何时刻都能给数。
            cfg = self.dmem.cfg
            n_layers = len(self.dmem.module_names) or len(self.dmem.layers)
            per_owner_bytes = (max(0, n_layers) * max(1, int(cfg.n_states))
                               * max(1, int(cfg.rank)) ** 2 * 2)
            return {
                "layout": self.layout,
                "root": self._root(),
                "current": self._current,
                "persist": self.persist,
                "strict_formal": self.strict_formal,
                "max_cached": self.max_cached,
                "owners_cached": list(self._cache.keys()),
                "stale_owners": sorted(self._stale),
                "state_kb_per_owner": round(per_owner_bytes / 1024, 1),
                **self._stats,
                "write_ms_avg": round(1000 * self._stats["write_seconds"]
                                      / max(1, self._stats["writes"]), 1),
            }
