# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/identity/dmem_bridge.py
"""δ-mem 记忆写入桥：**把每一轮对话写进用户自己的记忆矩阵**。

它解决什么
----------
生成时引擎只负责"读"（`memory_owner` → 加载 `character/userinfo/<uid>/mem/`）；
矩阵里要有内容，必须有人"写"。本模块就是那个"写"的人。

一轮对话的完整闭环（就是论文的在线更新）
----------------------------------------
    ① 用户说话
    ② 引擎按 uid 加载记忆矩阵          （func/meowllm/memory.py 负责传 uid）
    ③ 矩阵参与 attention → 生成回复
    ④ 回复结束 → 本模块把这一轮 append 进矩阵     ← 这里
    ⑤ 引擎落盘 character/userinfo/<uid>/mem/     （原子写 + 自动快照）

为什么是 append 而不是 replace
------------------------------
引擎在生成期间冻结状态（decode 每步不依赖递推，双流引擎才能跑 CUDA Graph），
所以做不到"边生成边改"。回复结束后追加一段，等价于把这一轮"记下来"。
`replace` 只用于首次建立或明显跑偏后重建。

用法（在发送回复之后调用，不阻塞）
----------------------------------
    from func.catbrain.UserMemory.identity.dmem_bridge import DmemBridge

    DmemBridge().remember(uid, user_text, reply_text)     # 非阻塞
    DmemBridge().rebuild(uid)                             # 用 abmem+档案重建
    DmemBridge().forget(uid)                              # 删除该用户记忆

设计约束
--------
* 只处理正式用户（`^\\d{6}$`），temp-* 一律跳过 —— 与引擎侧同规则；
* 写失败只记日志，绝不影响对话主链路；
* 单飞 + **合并**：同一 uid 一次只跑一趟写入，期间到达的轮次并进待写队列，
  由这一趟顺手带出去（老版本是"3 秒内直接丢掉"，会静默丢一半对话）；
* 端点从 `meowllm_config.base_url()` 推出来，不额外加配置项。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

try:
    from func.meowllm.memory import is_formal
except Exception: 
    import re

    def is_formal(uid) -> bool:
        text = str(uid or "").strip()
        return bool(re.match(r"^\d{6}$", text)) and not text.lower().startswith("temp")


MAX_CHARS = 1200
#: 同一用户积压的待写文本上限（字符）。超了就只留最近的，防止长时间阻塞时无限涨。
MAX_PENDING = 4000


@singleton
class DmemBridge:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._busy: set[str] = set()
        self._pending: dict[str, str] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _base() -> str:
        """从 meowllm 的 OpenAI 兼容地址推出控制面地址。

        meowllm_config.base_url() = http://host:port/meowllm/v1
        控制面在        http://host:port/meowllm/control/...
        """
        try:
            from func.meowllm import config as meowllm_config

            url = str(meowllm_config.base_url() or "").rstrip("/")
            root = url[:-3] if url.endswith("/v1") else url
            return root + "/control/dmem"
        except Exception:
            return "http://127.0.0.1:18100/meowllm/control/dmem"

    def _post(self, path: str, payload: dict, timeout: float = 20.0) -> dict:
        url = f"{self._base()}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}

    def _claim(self, uid: str, text: str) -> tuple[bool, int]:
        """决定这一轮是"现在就写"还是"攒着"。

        返回 (是否抢到写入权, 积压字符数)。**绝不能直接丢弃** ——
        老实现用 3 秒去抖 + 单飞，同一个人连着说两句就会静默丢一句，
        而调用方还以为是"写成功了"（连续对话实测丢一半以上）。
        现在改成"抢不到就合并到待写队列，由正在写的那一趟顺手带出去"。
        """
        with self._lock:
            if uid in self._busy:
                merged = (self._pending.get(uid, "") + "\n" + text).strip()
                self._pending[uid] = merged[-MAX_PENDING:]
                return False, len(self._pending[uid])
            self._busy.add(uid)
            return True, 0

    def _next_text(self, uid: str) -> str:
        """取出下一段待写文本；没有了就释放写入权（与 _claim 用同一把锁，不会丢）。"""
        with self._lock:
            text = self._pending.pop(uid, "")
            if not text:
                self._busy.discard(uid)
            return text

    def _write_once(self, uid: str, text: str) -> None:
        try:
            result = self._post("/write", {"owner": uid, "text": text,
                                           "mode": "append"})
            if result.get("ok"):
                self.log.info(
                    f"δ-mem 追加成功 uid={uid} tokens={result.get('tokens')} "
                    f"chunks={result.get('chunks')} {result.get('seconds')}s")
            else:
                self.log.warning(f"δ-mem 追加被拒 uid={uid}: {result}")
        except (urllib.error.URLError, OSError) as exc:
            self.log.warning(f"δ-mem 追加失败（引擎未开启或不可达）uid={uid}: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.log.exception(f"δ-mem 追加异常 uid={uid}: {exc}")

    def _drain(self, uid: str, text: str) -> None:
        """把这一段 + 期间攒下的都写完，然后释放写入权。"""
        current = text
        while current:
            self._write_once(uid, current)
            current = self._next_text(uid)

    def remember(self, uid: str, user_text: str, reply_text: str,
                 extra: str = "", async_write: bool = True) -> bool:
        """把一轮对话追加进该用户的记忆。返回是否真的**开始**写入。

        返回 False 有两种含义，日志里能区分：
          * 非正式号 / 空文本 —— 设计上就不写；
          * 上一趟还没写完 —— 已合并进待写队列，稍后会一起写出去（不会丢）。
        """
        if not is_formal(uid):
            return False
        text = self._compose(user_text, reply_text, extra)
        if not text:
            return False
        claimed, pending_len = self._claim(str(uid), text)
        if not claimed:
            self.log.info(f"δ-mem uid={uid} 上一趟还在写，本轮已并入待写队列"
                          f"（当前积压 {pending_len} 字）")
            return False

        if async_write:
            threading.Thread(target=self._drain, args=(uid, text),
                             name=f"dmem-{uid}", daemon=True).start()
            return True
        self._drain(uid, text)
        return True

    def rebuild(self, uid: str, text: str | None = None) -> dict:
        """整体重建某用户的记忆（首次建立 / 跑偏后重置）。"""
        if not is_formal(uid):
            return {"ok": False, "error": "非正式用户"}
        body = text if text is not None else self._compose_memory_source(uid)
        if not body:
            return {"ok": False, "error": "没有可写入的记忆文本"}
        try:
            return self._post("/write", {"owner": uid, "text": body,
                                         "mode": "replace"}, timeout=120.0)
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"δ-mem 重建失败 uid={uid}: {exc}")
            return {"ok": False, "error": str(exc)}

    def forget(self, uid: str) -> dict:
        if not is_formal(uid):
            return {"ok": False, "error": "非正式用户"}
        try:
            return self._post("/forget", {"owner": uid})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def status(self) -> dict:
        try:
            with urllib.request.urlopen(f"{self._base()}/status", timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            return {"enabled": False, "error": str(exc)}

    @staticmethod
    def _compose(user_text: str, reply_text: str, extra: str = "") -> str:
        """这一轮的"记忆流水"。带时间戳，方便将来做时间衰减。"""
        stamp = time.strftime("%Y-%m-%d %H:%M")
        rows = [f"[{stamp}]"]
        if extra:
            rows.append(str(extra).strip())
        user_text = str(user_text or "").strip()
        reply_text = str(reply_text or "").strip()
        if user_text:
            rows.append(f"用户：{user_text}")
        if reply_text:
            rows.append(f"我：{reply_text}")
        text = "\n".join(rows).strip()
        return text[:MAX_CHARS]

    def _compose_memory_source(self, uid: str) -> str:
        """重建时用什么当素材：长期记忆摘要 + 用户档案（都是框架现成的）。"""
        parts: list[str] = []

        def _try(fn, label):
            try:
                text = fn()
                if text and str(text).strip():
                    parts.append(f"【{label}】\n{str(text).strip()}")
            except Exception:  # noqa: BLE001
                pass

        try:
            from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory

            _try(lambda: MeowLoadAbstractMemory().build(uid), "长期记忆")
        except Exception:  # noqa: BLE001
            pass
        try:
            from func.catbrain.UserMemory.load_usrmem import MeowLoadUserMemory

            _try(lambda: MeowLoadUserMemory().build(uid), "用户档案")
        except Exception:  # noqa: BLE001
            pass
        return "\n\n".join(parts)
