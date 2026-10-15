import json
import re
import os
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

CHANNEL_QQ = "qq"
CHANNEL_BILI = "bili"
CHANNEL_VOICE = "voice"
CHANNEL_LOCAL = "local"

CHANNEL_ALIAS = {
    "qq": CHANNEL_QQ,
    "bili": CHANNEL_BILI,
    "b站": CHANNEL_BILI,
    "voice": CHANNEL_VOICE,
    "声纹": CHANNEL_VOICE,
}

CHANNEL_LABEL = {
    CHANNEL_QQ: "QQ",
    CHANNEL_BILI: "B站",
    CHANNEL_VOICE: "声纹",
    CHANNEL_LOCAL: "离线",
}

KNOWN_CHANNELS = (CHANNEL_QQ, CHANNEL_BILI)

TEMP_PREFIX = "temp-"
# 铁律一：临时身份（离线账号）= "说过一句话的人"的 id，永久保留，不做任何按时间清理


@singleton
class IdentityStore:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.dir = os.path.join("character", "userinfo")
        self.users_path = os.path.join(self.dir, "users.json")
        self.index_path = os.path.join(self.dir, "index.json")
        self.lock_path = os.path.join(self.dir, ".identity.lock")
        self._lock = threading.RLock()
        self._ensure_dir()

    def _ensure_dir(self):
        """确保身份表目录存在"""
        os.makedirs(self.dir, exist_ok=True)

    @staticmethod
    def normalize_channel(value):
        """把平台别名统一成 qq / bili / voice"""
        key = str(value or "").strip().lower()
        return CHANNEL_ALIAS.get(key, key)

    @staticmethod
    def channel_label(channel):
        """取平台的中文名"""
        channel = IdentityStore.normalize_channel(channel)
        return CHANNEL_LABEL.get(channel, channel)

    def _read_json(self, path, default):
        """读一个 json 文件，失败回默认值"""
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else default
        except Exception:
            self.log.exception(f"读取身份文件失败: {path}")
        return default

    def _write_json(self, path, data):
        """先写临时文件再替换，避免写一半被读走"""
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _acquire(self, timeout=8.0):
        """跨进程互斥：靠独占创建锁文件，超时或陈旧锁自动放行"""
        deadline = time.time() + timeout
        while True:
            try:
                os.makedirs(os.path.dirname(self.lock_path) or ".", exist_ok=True)
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                os.close(fd)
                return True
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.lock_path) > 15:
                        os.remove(self.lock_path)
                        continue
                except Exception:
                    pass
                if time.time() >= deadline:
                    self.log.warning("身份表锁等待超时")
                    return False
                time.sleep(0.05)
            except Exception:
                self.log.exception("获取身份表锁失败")
                return False

    def _release(self):
        """释放锁文件"""
        try:
            if os.path.exists(self.lock_path):
                os.remove(self.lock_path)
        except Exception:
            self.log.exception("释放身份表锁失败")

    def _load(self):
        """读对应表与反查表，凑成一个可写的数据块"""
        data = self._read_json(self.users_path, {})
        users = data.get("users") if isinstance(data.get("users"), dict) else {}
        next_no = data.get("next")
        if not isinstance(next_no, int) or next_no < 1:
            next_no = 1
        history = data.get("history") if isinstance(data.get("history"), dict) else {}
        temp_no = data.get("temp_next")
        if not isinstance(temp_no, int) or temp_no < 1:
            temp_no = 1
        index = self._read_json(self.index_path, {})
        if not isinstance(index, dict) or not index:
            index = self._rebuild_index(users)
        return {"next": next_no, "temp_next": temp_no, "users": users, "index": index, "history": history}

    def _save(self, data):
        """写回对应表与反查表，并把每个人同步进自己的文件夹"""
        self._write_json(self.users_path, {
            "next": data["next"],
            "temp_next": int(data.get("temp_next") or 1),
            "history": data.get("history") or {},
            "users": data["users"],
        })
        self._write_json(self.index_path, data["index"])
        for meowid, user in data["users"].items():
            self._write_user_file(meowid, user)


    def _write_user_file(self, meowid, user):
        """把昵称与各平台账号写进用户自己的文件夹（临时身份不建文件夹）"""
        if self.is_temp(meowid):
            return
        folder = os.path.join(self.dir, str(meowid))
        os.makedirs(folder, exist_ok=True)
        self._write_json(os.path.join(folder, "identity.json"), {
            "meowid": str(meowid),
            "nickname": str(user.get("nickname") or ""),
            "ext_accounts": user.get("ext_accounts") or {},
            "created": user.get("created") or 0,
        })


    @staticmethod
    def _rebuild_index(users):
        """按对应表重建反查表"""
        index = {}
        for meowid, user in (users or {}).items():
            for channel, ext_account in (user.get("ext_accounts") or {}).items():
                if ext_account:
                    index[f"{channel}:{ext_account}"] = meowid
        return index

    @staticmethod
    def is_temp(meowid):
        """判断是不是临时身份（还没绑定过任何正式账号的人）"""
        return str(meowid or "").strip().startswith(TEMP_PREFIX)

    @staticmethod
    def _new_id(data):
        """顺序发下一个六位编号，不回收不复用"""
        no = int(data.get("next") or 1)
        while True:
            meowid = f"{no:06d}"
            no += 1
            if meowid not in data["users"]:
                break
        data["next"] = no
        return meowid

    @staticmethod
    def _new_temp_id(data):
        """顺序发下一个临时身份 id"""
        no = int(data.get("temp_next") or 1)
        while True:
            meowid = f"{TEMP_PREFIX}{no:06d}"
            no += 1
            if meowid not in data["users"]:
                break
        data["temp_next"] = no
        return meowid

    def _fill_nickname(self, data, user, nickname):
        """首次建档时用外部显示名填一次昵称。

        重名允许：昵称可以重复，区分人只看 meowid（反查遇到重名会拒绝并提示改用编号）。
        """
        if not str((user or {}).get("nickname") or "").strip() and str(nickname or "").strip():
            user["nickname"] = str(nickname).strip()

    @staticmethod
    def _clean_account(ext_account):
        """账号去掉首尾空白，非数字也能用（声纹名）"""
        return str(ext_account or "").strip()

    def resolve(self, channel, ext_account):
        """平台加账号 → 编号，查不到回空串"""
        channel = self.normalize_channel(channel)
        ext_account = self._clean_account(ext_account)
        if not channel or not ext_account:
            return ""
        with self._lock:
            if not self._acquire():
                return ""
            try:
                data = self._load()
                return str(data["index"].get(f"{channel}:{ext_account}", "") or "")
            finally:
                self._release()

    def get_user(self, key):
        """按编号或昵称取用户，没有回空 dict"""
        key = str(key or "").strip()
        if not key:
            return {}
        with self._lock:
            if not self._acquire():
                return {}
            try:
                data = self._load()
                users = data["users"]
                if key in users:
                    return dict(users[key])
                hits = [u for u in users.values() if str(u.get("nickname") or "").strip() == key]
                if len(hits) == 1:
                    return dict(hits[0])
                return {}
            finally:
                self._release()

    def display_name(self, channel, ext_account, fallback=""):
        """取展示名：身份表里的昵称；查不到身份返回空串（**不回退传入名**）"""
        meowid = self.resolve(channel, ext_account)
        if not meowid:
            return ""
        user = self.get_user(meowid)
        return str(user.get("nickname") or "").strip()

    def ensure(self, channel, ext_account, nickname=""):
        """拿编号，没有就自动开一个户"""
        channel = self.normalize_channel(channel)
        ext_account = self._clean_account(ext_account)
        if not channel or not ext_account:
            return ""
        with self._lock:
            if not self._acquire():
                return ""
            try:
                data = self._load()
                key = f"{channel}:{ext_account}"
                meowid = str(data["index"].get(key, "") or "")
                if meowid and meowid in data["users"]:
                    self._fill_nickname(data, data["users"][meowid], nickname)
                    return meowid
                meowid = str((data.get("history") or {}).get(key, "") or "")
                if not (meowid and meowid in data["users"]):
                    meowid = self._new_id(data)
                user = data["users"].get(meowid) or {
                    "meowid": meowid,
                    "nickname": "",
                    "created": int(time.time()),
                    "ext_accounts": {},
                }
                user.setdefault("ext_accounts", {})[channel] = ext_account
                self._fill_nickname(data, user, nickname)
                data["users"][meowid] = user
                data["index"][key] = meowid
                self._save(data)
                return meowid
            finally:
                self._release()

    def create_user(self, nickname="", meowid=""):
        """开一个新编号（只有档案、不挂任何账号），返回编号"""
        nickname = str(nickname or "").strip()
        meowid = str(meowid or "").strip()
        with self._lock:
            if not self._acquire():
                return ""
            try:
                data = self._load()
                if meowid and meowid in data["users"]:
                    return meowid
                if not meowid:
                    meowid = self._new_id(data)
                data["users"][meowid] = {
                    "meowid": meowid,
                    "nickname": "",
                    "created": int(time.time()),
                    "ext_accounts": {},
                }
                self._fill_nickname(data, data["users"][meowid], nickname)
                self._save(data)
                return meowid
            finally:
                self._release()

    def ensure_temp(self, channel, ext_account, nickname=""):
        """没绑定的人给一个临时身份（temp-00000x），已有正式编号就直接返回正式编号"""
        channel = self.normalize_channel(channel)
        ext_account = self._clean_account(ext_account)
        if not channel or not ext_account:
            return ""
        with self._lock:
            if not self._acquire():
                return ""
            try:
                data = self._load()
                key = f"{channel}:{ext_account}"
                meowid = str(data["index"].get(key, "") or "")
                if meowid and meowid in data["users"]:
                    user = data["users"][meowid]
                    if self.is_temp(meowid):
                        user["seen"] = int(time.time())
                        self._fill_nickname(data, user, nickname)
                        data["users"][meowid] = user
                        self._save(data)
                    return meowid
                # 铁律一：说一句话就该有 meowid —— 没有昵称也照样建档，绝不拒绝（也不清理老 temp）
                meowid = self._new_temp_id(data)
                now = int(time.time())
                data["users"][meowid] = {
                    "meowid": meowid,
                    "nickname": "",
                    "created": now,
                    "seen": now,
                    "ext_accounts": {channel: ext_account},
                }
                self._fill_nickname(data, data["users"][meowid], nickname)
                data["index"][key] = meowid
                self._save(data)
                return meowid
            finally:
                self._release()

    def promote(self, meowid):
        """临时身份转正：换成正式六位编号，账号与昵称都带过去"""
        meowid = str(meowid or "").strip()
        if not self.is_temp(meowid):
            return meowid
        with self._lock:
            if not self._acquire():
                return meowid
            try:
                data = self._load()
                user = data["users"].get(meowid)
                if not user:
                    return meowid
                new_uid = self._new_id(data)
                user["meowid"] = new_uid
                user.pop("seen", None)
                data["users"].pop(meowid, None)
                data["users"][new_uid] = user
                for key, value in list(data["index"].items()):
                    if str(value) == meowid:
                        data["index"][key] = new_uid
                for key, value in list((data.get("history") or {}).items()):
                    if str(value) == meowid:
                        data["history"][key] = new_uid
                self.log.info(f"[Identity] 临时身份 {meowid} 已转正为 {new_uid}")
                self._save(data)
                return new_uid
            finally:
                self._release()


    def bind(self, meowid, channel, ext_account, nickname=""):
        """把一个平台账号绑到编号上，返回 (成功, 提示, 该账号原属编号)"""
        channel = self.normalize_channel(channel)
        ext_account = self._clean_account(ext_account)
        meowid = str(meowid or "").strip()
        label = self.channel_label(channel)
        if not channel or not ext_account:
            return False, "参数缺失：请提供要绑定的账号", ""
        if not meowid:
            return False, "参数缺失：请先取得用户编号", ""
        with self._lock:
            if not self._acquire():
                return False, "身份表正忙，请稍后再试", ""
            try:
                data = self._load()
                user = data["users"].get(meowid)
                if not user:
                    return False, f"没找到编号 {meowid}", ""
                key = f"{channel}:{ext_account}"
                owner = str(data["index"].get(key, "") or "")
                if owner and owner != meowid:
                    other = data["users"].get(owner) or {}
                    other_name = str(other.get("nickname") or "").strip() or "未设昵称"
                    return False, f"这个{label}账号已经绑在 {owner}（{other_name}）名下，请先解绑或改用其它账号", owner
                old = str((user.get("ext_accounts") or {}).get(channel) or "")
                if old and old != ext_account:
                    data["index"].pop(f"{channel}:{old}", None)
                user.setdefault("ext_accounts", {})[channel] = ext_account
                self._fill_nickname(data, user, nickname)
                data["users"][meowid] = user
                data["index"][key] = meowid
                self._save(data)
                return True, "", meowid
            finally:
                self._release()

    def unbind(self, meowid, channel):
        """解绑编号下的某个平台账号，返回 (成功, 提示)"""
        channel = self.normalize_channel(channel)
        meowid = str(meowid or "").strip()
        label = self.channel_label(channel)
        if not channel:
            return False, "参数缺失：请提供要解绑的平台"
        if not meowid:
            return False, "还没绑定过，没有可解绑的账号"
        with self._lock:
            if not self._acquire():
                return False, "身份表正忙，请稍后再试"
            try:
                data = self._load()
                user = data["users"].get(meowid)
                if not user:
                    return False, f"没找到编号 {meowid}"
                ext_account = str((user.get("ext_accounts") or {}).pop(channel, "") or "")
                if not ext_account:
                    return False, f"你名下没有绑过{label}账号，无需解绑"
                data["index"].pop(f"{channel}:{ext_account}", None)
                data.setdefault("history", {})[f"{channel}:{ext_account}"] = meowid
                data["users"][meowid] = user
                self._save(data)
                return True, ""
            finally:
                self._release()

    def set_nickname(self, meowid, nickname):
        """改昵称，返回 (成功, 提示)"""
        meowid = str(meowid or "").strip()
        nickname = str(nickname or "").strip()
        if not meowid:
            return False, "参数缺失：请先取得用户编号"
        if not nickname:
            return False, "参数缺失：请提供新昵称"
        with self._lock:
            if not self._acquire():
                return False, "身份表正忙，请稍后再试"
            try:
                data = self._load()
                user = data["users"].get(meowid)
                if not user:
                    return False, f"没找到编号 {meowid}"
                # 重名允许：昵称可以重复，区分人只看 meowid
                user["nickname"] = nickname
                data["users"][meowid] = user
                self._save(data)
                return True, ""
            finally:
                self._release()

    def list_users(self, include_temp=False):
        """列出全部用户，按编号排序（默认不列临时身份）"""
        with self._lock:
            if not self._acquire():
                return []
            try:
                data = self._load()
                users = [dict(data["users"][k]) for k in sorted(data["users"].keys())]
                if not include_temp:
                    users = [u for u in users if not self.is_temp(u.get("meowid"))]
                return users
            finally:
                self._release()

    def merge_users(self, keep_uid, drop_uid):
        """把 drop 并入 keep，账号冲突时保留 keep 的，返回 (成功, 提示)"""
        keep_uid = str(keep_uid or "").strip()
        drop_uid = str(drop_uid or "").strip()
        if not keep_uid or not drop_uid or keep_uid == drop_uid:
            return False, "参数缺失或两边编号相同"
        with self._lock:
            if not self._acquire():
                return False, "身份表正忙，请稍后再试"
            try:
                data = self._load()
                keep = data["users"].get(keep_uid)
                drop = data["users"].get(drop_uid)
                if not keep or not drop:
                    return False, "没找到要合并的编号"
                for channel, ext_account in (drop.get("ext_accounts") or {}).items():
                    ext_account = str(ext_account or "").strip()
                    if not ext_account:
                        continue
                    key = f"{channel}:{ext_account}"
                    if str(keep.get("ext_accounts", {}).get(channel) or ""):
                        data["index"][key] = keep_uid
                        continue
                    keep.setdefault("ext_accounts", {})[channel] = ext_account
                    data["index"][key] = keep_uid
                drop["ext_accounts"] = {}
                data["users"][drop_uid] = drop
                data["users"][keep_uid] = keep
                index = {}
                for meowid, user in data["users"].items():
                    for channel, ext_account in (user.get("ext_accounts") or {}).items():
                        if ext_account:
                            index[f"{channel}:{ext_account}"] = meowid
                data["index"] = index
                self._save(data)
                return True, ""
            finally:
                self._release()

    def summary_line(self, meowid):
        """把编号、昵称、已绑平台拼成一行，供回复用"""
        user = self.get_user(meowid)
        if not user:
            return ""
        nickname = str(user.get("nickname") or "").strip() or "未设昵称"
        if self.is_temp(meowid):
            return f"临时身份 {meowid}，昵称 {nickname}，还没绑定平台（绑定后自动转正）"
        accounts = user.get("ext_accounts") or {}
        parts = []
        for channel in sorted(accounts.keys()):
            if accounts.get(channel):
                parts.append(f"{self.channel_label(channel)} {accounts.get(channel)}")
        bound = "、".join(parts) if parts else "无"
        return f"编号 {meowid}，昵称 {nickname}，已绑：{bound}"
