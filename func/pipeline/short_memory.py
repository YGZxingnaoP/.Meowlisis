# -*- coding: utf-8 -*-
# func/pipeline/short_memory.py
# 短期记忆桥接：统一收发 .temp/public_short_mem.json
#
# 记录结构：[{"role", "content", "type", "seq", "scope", "turn"}]
#   role/content 交给模型；type/seq/scope/turn 只给本地裁剪用，不进任何 API。
#
# 【规则一 · 以真实回复时间为准】
#   短期记忆和真实时间强相关，及交互真实生效，短期记忆记录时序和用户感知到输出的时间完全吻合
#   记忆在"被写下来那一刻"归到当时的当前轮：不提前捕获轮号、不做轮次匹配。
#   异步产出（画图）也等真正产出、用户看到时才写，写到哪一轮就是哪一轮。
#
# 【规则二 · 挂靠】
#   一轮 = 同一通道里一条开轮 user 记录（OPENERS）开启的对话，轮内记录共享 turn；
#   轮被裁掉时轮内记录一起消失，模型不会看到"没有问题的答案"。
#   通道：main（主链）/ qq_private:<QQ号> / qq_group:<群号> / danmaku / sys。
#
# 用法：save({"role", "content", "type"})；主链 user 未归档时先 begin_turn() 占号，
#   通道用 scope 参数或 set_current_scope()；load() -> [{"role", "content"}]。

import os
import json
import time
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


#: 线程级当前通道；QQ 回复线程设置后，同线程同步调用的工具自动归到该 QQ 轮。不跨线程。
_SCOPE_CTX = threading.local()


def set_current_scope(scope: str) -> None:
    """在处理某条消息的线程入口调用一次，声明这条线程之后的记忆归属哪个通道"""
    _SCOPE_CTX.scope = str(scope or "")


def clear_current_scope() -> None:
    """处理完一条消息后清掉，避免线程复用把上一条消息的通道带过来"""
    _SCOPE_CTX.scope = ""


def current_scope() -> str:
    """取本线程当前通道（没设过 = main）"""
    return getattr(_SCOPE_CTX, "scope", "") or "main"


@singleton
class ShortMemory:
    """短期记忆桥接：负责 .temp/public_short_mem.json 的读取、保存与裁剪"""

    # 插播类：只在没有轮（老数据/待定）时按条兜底
    ACTIVE_TYPES = ("llm_active_response", "vision_response", "hum_song", "other_talks",
                    "toolbox_excuse", "toolbox_result", "singer_thought")

    # 各插播的兜底条数（0 = 不兜底，只依赖挂靠淘汰）
    ACTIVE_LIMITS = {"toolbox_excuse": 8, "toolbox_result": 8, "singer_thought": 0}

    SESSION_MARKER = "session_marker"

    MARKER_KEEP = 5

    # 开轮类型：这些类型的 user 记录会开新的一轮
    OPENERS = ("llm_fast_response", "qq_response", "qq_groupchat", "danmaku_response")

    SCOPE_MAIN = "main"
    SCOPE_SYS = "sys"

    # 类型即通道；手机没有自己的往返，固定挂主链（不受线程当前通道影响）
    SCOPE_OF_TYPE = {"danmaku_response": "danmaku",
                     "phone_control_user": "main",
                     "phone_control_response": "main"}

    # -1 待定（等下一次开轮补锚）；-2 无轮（会话标记/老数据，不参与整轮淘汰）
    TURN_PENDING = -1
    TURN_NONE = -2

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.path = os.path.join(".temp", "public_short_mem.json")
        self._lock = threading.Lock()
        # 最近一次读到的内容：读写不共用锁，撞上写入时用它兜底，避免整段历史变空
        self._cache = []
        # 进程内当前轮：begin_turn() 先占轮号，让"本轮内写入的插播/工具结果"能挂对轮
        # （此时 user 消息可能还在 MessageBuilder 的内存里，json 里看不到）
        self._current_turn = {}
        # 已经落盘的开轮轮号：用来区分"还没归档的在飞轮"和"已经被裁掉的死轮"
        self._opener_seen = set()
        self._turn_alloc = 0
        self._mark_session()
        self._ensure_anchor_fields()

    # ==================== 通道 / 定锚 / 整轮淘汰 ====================
    @classmethod
    def scope_of_qq_context(cls, qq_context) -> str:
        """QQ 上下文 → 通道号"""
        ctx = qq_context or {}
        if str(ctx.get("message_type", "")) == "group":
            gid = ctx.get("target_id") or ctx.get("group_id") or ""
            return f"qq_group:{gid}" if gid else "qq_group"
        uid = ctx.get("user_id") or ctx.get("target_id") or ""
        return f"qq_private:{uid}" if uid else "qq_private"

    @staticmethod
    def scope_of_channel(channel) -> str:
        """画板 channel（qq_group_123 / qq_private_45 / live）→ 通道号"""
        text = str(channel or "")
        if text.startswith("qq_group_"):
            return "qq_group:" + text[len("qq_group_"):]
        if text.startswith("qq_private_"):
            return "qq_private:" + text[len("qq_private_"):]
        return "main"

    @classmethod
    def _scope_of(cls, mem_type, scope=None) -> str:
        """显式 scope > 类型固定通道 > 本线程当前通道"""
        if scope:
            return str(scope)
        if not mem_type or mem_type == cls.SESSION_MARKER:
            return cls.SCOPE_SYS
        return cls.SCOPE_OF_TYPE.get(mem_type) or current_scope()

    def _read(self) -> list:
        """读取全部记录；撞上写入时重读，仍失败就用最近一次读到的快照，绝不返回空。"""
        for attempt in range(3):
            if not os.path.exists(self.path):
                return []
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data = data if isinstance(data, list) else []
                self._cache = data
                return data
            except Exception:
                if attempt < 2:
                    time.sleep(0.02)
                    continue
                self.log.exception("读取短期记忆失败")
        return list(getattr(self, "_cache", []) or [])

    def _write(self, data: list):
        """一次写完；不用 json.dump 逐块挤，也不改名（Windows 上文件被占用会失败）。"""
        try:
            self._cache = data
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            body = json.dumps(data, ensure_ascii=False, indent=2)
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(body)
        except Exception:
            self.log.exception("写入短期记忆失败")

    def _mark_session(self):
        """启动时插一条会话分割提示。"""
        with self._lock:
            data = self._read()
            if not data:
                return
            now = time.strftime("%Y-%m-%d %H:%M")
            text = f"【会话分割】以上内容发生在 {now} 之前；此后的属于本次会话"
            if data[-1].get("type") == self.SESSION_MARKER:
                data[-1]["role"] = "system"
                data[-1]["content"] = text
                self._write(data)
                return
            data.append({
                "role": "system",
                "content": text,
                "type": self.SESSION_MARKER,
            })
            self._write(self._cleanup_markers(data))

    def _cleanup_markers(self, data: list) -> list:
        """分割标记清理：没内容的丢弃、连续只留最后一条、最多 MARKER_KEEP 条。"""
        out = []
        has_content = False
        for m in data:
            if m.get("type") == self.SESSION_MARKER:
                if not has_content:
                    continue
                if out and out[-1].get("type") == self.SESSION_MARKER:
                    out[-1] = m
                    continue
                out.append(m)
            else:
                has_content = True
                out.append(m)
        idx = [i for i, m in enumerate(out) if m.get("type") == self.SESSION_MARKER]
        if len(idx) > self.MARKER_KEEP:
            for i in reversed(idx[:-self.MARKER_KEEP]):
                out.pop(i)
        return out

    # ==================== 挂靠：定锚 / 查轮 / 整轮淘汰 ====================
    @staticmethod
    def _next_seq(data: list) -> int:
        """下一条记录的写入序号（文件内自增）"""
        seqs = [m.get("seq") for m in data if isinstance(m.get("seq"), int)]
        return (max(seqs) + 1) if seqs else 1

    def _alloc_turn(self, data: list) -> int:
        """分配一个新轮号（只占号，不落盘）"""
        turns = [m.get("turn") for m in data
                 if isinstance(m.get("turn"), int) and m.get("turn") >= 0]
        turns += [t for t in self._current_turn.values() if isinstance(t, int) and t >= 0]
        self._turn_alloc = max([self._turn_alloc] + turns) + 1
        return self._turn_alloc

    def begin_turn(self, scope: str = SCOPE_MAIN) -> int:
        """主链开轮：user 还没归档时先占号，否则本轮的工具结果会挂到上一轮。"""
        with self._lock:
            data = self._read()
            turn = self._alloc_turn(data)
            self._current_turn[scope] = turn
            return turn

    def current_turn(self, scope: str = SCOPE_MAIN):
        """取该通道的当前轮号（没有则 None）"""
        return self._current_turn.get(scope)

    def _alive_turns(self, data: list) -> set:
        """数据里仍然活着的轮：开轮记录还在的轮号"""
        alive = set()
        for m in data:
            turn = m.get("turn")
            if not isinstance(turn, int) or turn < 0:
                continue
            if m.get("role") == "user" and m.get("type") in self.OPENERS:
                alive.add(turn)
        return alive

    def _last_open_turn(self, data: list, scope: str):
        """该通道里最后一条开轮记录所属的轮号（没有返回 None）"""
        for m in reversed(data):
            if m.get("scope") != scope:
                continue
            if m.get("role") == "user" and m.get("type") in self.OPENERS:
                turn = m.get("turn")
                return turn if isinstance(turn, int) and turn >= 0 else None
        return None

    def _stamp(self, data: list, message: dict, scope=None, turn=None) -> dict:
        """写入前定锚：seq + scope + turn（见文件头）。"""
        mem_type = message.get("type")
        scope = self._scope_of(mem_type, scope)
        message["seq"] = self._next_seq(data)
        message["scope"] = scope

        if scope == self.SCOPE_SYS:
            message["turn"] = self.TURN_NONE
            return message

        is_opener = (message.get("role") == "user" and mem_type in self.OPENERS)
        if turn is None:
            if is_opener:
                turn = self._alloc_turn(data)
            else:
                # 插播优先挂进程内当前轮（本轮刚开、user 可能还没归档，不能当成死轮）；
                # 只有"这一轮开过、又被裁掉了"才退回上一个开轮；都没有就标 pending。
                alive = self._alive_turns(data)
                cur = self._current_turn.get(scope)
                if isinstance(cur, int) and cur >= 0 and cur in self._opener_seen and cur not in alive:
                    cur = None
                if cur is None:
                    cur = self._last_open_turn(data, scope)
                turn = cur
        message["turn"] = turn if isinstance(turn, int) and turn >= 0 else self.TURN_PENDING

        if is_opener and message["turn"] >= 0:
            self._opener_seen.add(message["turn"])
            # 只往前推进"当前轮"：归档的是更早的轮时不能把指针退回去，
            # 否则本轮内后续写入会挂到那个旧轮上。
            prev = self._current_turn.get(scope)
            if not isinstance(prev, int) or message["turn"] >= prev:
                self._current_turn[scope] = message["turn"]
            # 本轮回合之前写入、还没定锚的插播，补锚到这一轮（它们本来就属于这一轮）
            for m in data:
                if m.get("scope") == scope and m.get("turn") == self.TURN_PENDING:
                    m["turn"] = message["turn"]
        return message

    def _drop_dead_turns(self, data: list) -> list:
        """整轮淘汰：开轮记录没了的轮，成员一起删；无轮与在飞轮不动。"""
        alive = self._alive_turns(data)
        inflight = {t for t in self._current_turn.values()
                    if isinstance(t, int) and t >= 0 and t not in self._opener_seen}
        out = []
        for m in data:
            turn = m.get("turn")
            if not isinstance(turn, int) or turn < 0 or turn in alive or turn in inflight:
                out.append(m)
        return out

    def _ensure_anchor_fields(self):
        """给老数据补 seq/scope/turn：只加字段，不改顺序与内容。"""
        with self._lock:
            data = self._read()
            if not data:
                return
            if all(isinstance(m.get("seq"), int) for m in data):
                return
            next_seq = self._next_seq(data)
            # 已有轮号从现有数据续上，避免给新记录（如启动时写的会话分割）发出撞号的轮
            turn = max([m.get("turn") for m in data
                        if isinstance(m.get("turn"), int) and m.get("turn") >= 0] or [0])
            last_turn = {}
            for m in data:
                if isinstance(m.get("turn"), int) and m.get("turn") >= 0 \
                        and m.get("role") == "user" and m.get("type") in self.OPENERS:
                    last_turn[m.get("scope") or self._scope_of(m.get("type"))] = m["turn"]
            for m in data:
                if not isinstance(m.get("seq"), int):
                    m["seq"] = next_seq
                    next_seq += 1
                scope = m.get("scope") or self._scope_of(m.get("type"))
                m["scope"] = scope
                if scope == self.SCOPE_SYS:
                    m["turn"] = self.TURN_NONE
                    continue
                if not isinstance(m.get("turn"), int):
                    if m.get("role") == "user" and m.get("type") in self.OPENERS:
                        turn += 1
                        m["turn"] = turn
                        last_turn[scope] = turn
                    else:
                        m["turn"] = last_turn.get(scope, self.TURN_NONE)
            alive = self._alive_turns(data)
            for m in data:
                t = m.get("turn")
                if isinstance(t, int) and t >= 0 and t not in alive:
                    m["turn"] = self.TURN_NONE
            self._write(data)

    def save(self, message: dict, max_rounds: int, trim_mode: str = "rounds",
             scope: str = None, turn: int = None):
        """保存一条短期记忆并按上限裁剪。

        max_rounds 只对开轮类型生效，其它类型跟着轮走；scope 不传按线程当前通道；
        turn 一般不传——以写入时刻为准，只有主链归档时带上内存里记下的轮号。
        """
        with self._lock:
            data = self._read()
            message = self._stamp(data, message, scope, turn)
            data.append(message)
            # 只有开轮类型保留条数/轮数上限（它就是"轮"的边界）；
            # 其余类型跟着轮走，这里只裁没有轮的老记录，避免"轮还在、插播先被砍"。
            anchored = message.get("type") in self.OPENERS
            data = self._trim_by_type(data, message.get("type"), max_rounds, trim_mode,
                                      only_unanchored=not anchored)
            data = self._trim_active_orphans(data)
            data = self._drop_dead_turns(data)
            data = self._cleanup_markers(data)
            self._write(data)

    def _trim_by_type(self, data: list, mem_type, max_rounds: int, trim_mode: str = "rounds",
                      only_unanchored: bool = False) -> list:
        """按 type 裁剪：items 按条、rounds 按轮；only_unanchored 时只处理没有轮的记录。"""
        if not mem_type or max_rounds <= 0:
            return data
        type_indices = [i for i, m in enumerate(data)
                        if m.get("type") == mem_type
                        and not (only_unanchored
                                 and isinstance(m.get("turn"), int) and m.get("turn") >= 0)]

        if trim_mode == "items":
            remove_n = max(0, len(type_indices) - max_rounds)
            if remove_n > 0:
                for idx in sorted(type_indices[:remove_n], reverse=True):
                    data.pop(idx)
            return data

        # ===== rounds 模式 =====
        paired_rounds = []
        orphans = []
        i = 0
        n = len(type_indices)
        while i < n:
            if i + 1 < n:
                idx1, idx2 = type_indices[i], type_indices[i + 1]
                if data[idx1].get("role") == "user" and data[idx2].get("role") == "assistant":
                    paired_rounds.append((idx1, idx2))
                    i += 2
                    continue
            orphans.append(type_indices[i])
            i += 1

        remove_rounds = max(0, len(paired_rounds) - max_rounds)
        remove_orphans = max(0, len(orphans) - max_rounds)

        remove_set = set()
        for idx1, idx2 in paired_rounds[:remove_rounds]:
            remove_set.add(idx1)
            remove_set.add(idx2)
        for idx in orphans[:remove_orphans]:
            remove_set.add(idx)

        if remove_set:
            for idx in sorted(remove_set, reverse=True):
                data.pop(idx)
        return data

    def _trim_active_orphans(self, data: list) -> list:
        """插播兜底：只对没有轮的记录生效，有轮的寿命由轮决定。"""
        default_limit = self._active_mem_limit()
        for active_type in self.ACTIVE_TYPES:
            limit = self.ACTIVE_LIMITS.get(active_type)
            if limit is None:
                limit = default_limit
            if limit <= 0:
                continue
            indices = [i for i, m in enumerate(data)
                       if m.get("type") == active_type
                       and not (isinstance(m.get("turn"), int) and m.get("turn") >= 0)]
            remove_n = max(0, len(indices) - limit)
            if remove_n > 0:
                for idx in sorted(indices[:remove_n], reverse=True):
                    data.pop(idx)
        return data

    def _active_mem_limit(self) -> int:
        """读取主动回复插播兜底上限（默认 50）"""
        try:
            from func.llm_active.config import AutoActiveConfig
            return int(AutoActiveConfig().active_mem_limit)
        except Exception:
            return 50

    def load(self) -> list:
        """加载全部记录，只返回 role/content。"""
        result = []
        for m in self._read():
            if "role" in m and "content" in m:
                result.append({"role": m["role"], "content": m["content"]})
        return result

    def load_by_type(self, mem_types) -> list:
        """按 type 加载（保留 type，只取非空 user/assistant）。"""
        types = tuple(mem_types) if isinstance(mem_types, (list, tuple, set)) else (mem_types,)
        result = []
        for m in self._read():
            if m.get("type") not in types:
                continue
            if m.get("role") not in ("user", "assistant"):
                continue
            content = str(m.get("content") or "")
            if not content.strip():
                continue
            result.append({"role": m["role"], "content": content, "type": m.get("type")})
        return result
