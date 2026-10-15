import json
import re
import os
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

PLATFORM_QQ = "qq"
PLATFORM_BILI = "bili"
PLATFORM_VOICE = "voice"
PLATFORM_LOCAL = "local"

PLATFORM_ALIAS = {
    "qq": PLATFORM_QQ,
    "bili": PLATFORM_BILI,
    "b站": PLATFORM_BILI,
    "voice": PLATFORM_VOICE,
    "声纹": PLATFORM_VOICE,
}

PLATFORM_LABEL = {
    PLATFORM_QQ: "QQ",
    PLATFORM_BILI: "B站",
    PLATFORM_VOICE: "声纹",
    PLATFORM_LOCAL: "离线",
}

KNOWN_PLATFORMS = (PLATFORM_QQ, PLATFORM_BILI)

TEMP_PREFIX = "temp-"
TEMP_KEEP_DAYS = 30


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
    def normalize_platform(value):
        """把平台别名统一成 qq / bili / voice"""
        key = str(value or "").strip().lower()
        return PLATFORM_ALIAS.get(key, key)

    @staticmethod
    def platform_label(platform):
        """取平台的中文名"""
        platform = IdentityStore.normalize_platform(platform)
        return PLATFORM_LABEL.get(platform, platform)

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
        for uid, user in data["users"].items():
            self._write_user_file(uid, user)


    def _write_user_file(self, uid, user):
        """把昵称与各平台账号写进用户自己的文件夹（临时身份不建文件夹）"""
        if self.is_temp(uid):
            return
        folder = os.path.join(self.dir, str(uid))
        os.makedirs(folder, exist_ok=True)
        self._write_json(os.path.join(folder, "identity.json"), {
            "id": str(uid),
            "nickname": str(user.get("nickname") or ""),
            "accounts": user.get("accounts") or {},
            "created": user.get("created") or 0,
        })


    @staticmethod
    def _rebuild_index(users):
        """按对应表重建反查表"""
        index = {}
        for uid, user in (users or {}).items():
            for platform, account in (user.get("accounts") or {}).items():
                if account:
                    index[f"{platform}:{account}"] = uid
        return index

    @staticmethod
    def is_temp(uid):
        """判断是不是临时身份（还没绑定过任何正式账号的人）"""
        return str(uid or "").strip().startswith(TEMP_PREFIX)

    @staticmethod
    def _new_id(data):
        """顺序发下一个六位编号，不回收不复用"""
        no = int(data.get("next") or 1)
        while True:
            uid = f"{no:06d}"
            no += 1
            if uid not in data["users"]:
                break
        data["next"] = no
        return uid

    @staticmethod
    def _new_temp_id(data):
        """顺序发下一个临时身份 id"""
        no = int(data.get("temp_next") or 1)
        while True:
            uid = f"{TEMP_PREFIX}{no:06d}"
            no += 1
            if uid not in data["users"]:
                break
        data["temp_next"] = no
        return uid

    def _prune_temps(self, data):
        """清掉太久没露面的临时身份，避免陌生人无限堆积"""
        deadline = time.time() - TEMP_KEEP_DAYS * 86400
        for uid, user in list((data.get("users") or {}).items()):
            if not self.is_temp(uid):
                continue
            last = float((user or {}).get("seen") or (user or {}).get("created") or 0)
            if last and last < deadline:
                data["users"].pop(uid, None)
                for key, value in list((data.get("index") or {}).items()):
                    if str(value) == uid:
                        data["index"].pop(key, None)

    def _fill_nickname(self, data, user, nickname):
        if not str((user or {}).get("nickname") or "").strip() and str(nickname or "").strip():
            name = str(nickname).strip()
            uid = str((user or {}).get("id") or "")
            if self.nickname_owner(data, name, exclude_uid=uid):
                name = f"{name}({uid})" if uid else name
            user["nickname"] = name

    @staticmethod
    def _clean_account(account):
        """账号去掉首尾空白，非数字也能用（声纹名）"""
        return str(account or "").strip()

    @staticmethod
    def normalize_nickname(nickname):
        """昵称归一化：全角转半角、空白折叠、大小写不敏感（只用于查重，不改显示）"""
        text = str(nickname or "").strip()
        out = []
        for ch in text:
            code = ord(ch)
            if code == 0x3000:
                out.append(" ")
            elif 0xFF01 <= code <= 0xFF5E:
                out.append(chr(code - 0xFEE0))
            else:
                out.append(ch)
        return re.sub(r"\s+", " ", "".join(out)).strip().casefold()

    def nickname_owner(self, data, nickname, exclude_uid=""):
        """昵称占用者编号；没人用返回空串（正式身份与临时身份一起查）"""
        want = self.normalize_nickname(nickname)
        if not want:
            return ""
        exclude = str(exclude_uid or "").strip()
        for uid, user in (data.get("users") or {}).items():
            if str(uid) == exclude:
                continue
            if self.normalize_nickname((user or {}).get("nickname")) == want:
                return str(uid)
        return ""

    def resolve(self, platform, account):
        """平台加账号 → 编号，查不到回空串"""
        platform = self.normalize_platform(platform)
        account = self._clean_account(account)
        if not platform or not account:
            return ""
        with self._lock:
            if not self._acquire():
                return ""
            try:
                data = self._load()
                return str(data["index"].get(f"{platform}:{account}", "") or "")
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

    def display_name(self, platform, account, fallback=""):
        """取展示名：身份表里的昵称优先，没有就回退原来的用户名"""
        uid = self.resolve(platform, account)
        if not uid:
            return str(fallback or "")
        user = self.get_user(uid)
        return str(user.get("nickname") or "").strip() or str(fallback or "")

    def ensure(self, platform, account, nickname=""):
        """拿编号，没有就自动开一个户"""
        platform = self.normalize_platform(platform)
        account = self._clean_account(account)
        if not platform or not account:
            return ""
        with self._lock:
            if not self._acquire():
                return ""
            try:
                data = self._load()
                key = f"{platform}:{account}"
                uid = str(data["index"].get(key, "") or "")
                if uid and uid in data["users"]:
                    self._fill_nickname(data, data["users"][uid], nickname)
                    return uid
                uid = str((data.get("history") or {}).get(key, "") or "")
                if not (uid and uid in data["users"]):
                    uid = self._new_id(data)
                user = data["users"].get(uid) or {
                    "id": uid,
                    "nickname": "",
                    "created": int(time.time()),
                    "accounts": {},
                }
                user.setdefault("accounts", {})[platform] = account
                self._fill_nickname(data, user, nickname)
                data["users"][uid] = user
                data["index"][key] = uid
                self._save(data)
                return uid
            finally:
                self._release()

    def create_user(self, nickname="", uid=""):
        """开一个新编号（只有档案、不挂任何账号），返回编号"""
        nickname = str(nickname or "").strip()
        uid = str(uid or "").strip()
        with self._lock:
            if not self._acquire():
                return ""
            try:
                data = self._load()
                if uid and uid in data["users"]:
                    return uid
                if not uid:
                    uid = self._new_id(data)
                data["users"][uid] = {
                    "id": uid,
                    "nickname": "",
                    "created": int(time.time()),
                    "accounts": {},
                }
                self._fill_nickname(data, data["users"][uid], nickname)
                self._save(data)
                return uid
            finally:
                self._release()

    def ensure_temp(self, platform, account, nickname=""):
        """没绑定的人给一个临时身份（temp-00000x），已有正式编号就直接返回正式编号"""
        platform = self.normalize_platform(platform)
        account = self._clean_account(account)
        if not platform or not account:
            return ""
        with self._lock:
            if not self._acquire():
                return ""
            try:
                data = self._load()
                key = f"{platform}:{account}"
                uid = str(data["index"].get(key, "") or "")
                if uid and uid in data["users"]:
                    user = data["users"][uid]
                    if self.is_temp(uid):
                        user["seen"] = int(time.time())
                        self._fill_nickname(data, user, nickname)
                        data["users"][uid] = user
                        self._save(data)
                    return uid
                self._prune_temps(data)
                uid = self._new_temp_id(data)
                self._prune_temps(data)
                now = int(time.time())
                data["users"][uid] = {
                    "id": uid,
                    "nickname": "",
                    "created": now,
                    "seen": now,
                    "accounts": {platform: account},
                }
                self._fill_nickname(data, data["users"][uid], nickname)
                data["index"][key] = uid
                self._save(data)
                return uid
            finally:
                self._release()

    def promote(self, uid):
        """临时身份转正：换成正式六位编号，账号与昵称都带过去"""
        uid = str(uid or "").strip()
        if not self.is_temp(uid):
            return uid
        with self._lock:
            if not self._acquire():
                return uid
            try:
                data = self._load()
                user = data["users"].get(uid)
                if not user:
                    return uid
                new_uid = self._new_id(data)
                user["id"] = new_uid
                user.pop("seen", None)
                data["users"].pop(uid, None)
                data["users"][new_uid] = user
                for key, value in list(data["index"].items()):
                    if str(value) == uid:
                        data["index"][key] = new_uid
                for key, value in list((data.get("history") or {}).items()):
                    if str(value) == uid:
                        data["history"][key] = new_uid
                self.log.info(f"[Identity] 临时身份 {uid} 已转正为 {new_uid}")
                self._save(data)
                return new_uid
            finally:
                self._release()


    def bind(self, uid, platform, account, nickname=""):
        """把一个平台账号绑到编号上，返回 (成功, 提示, 该账号原属编号)"""
        platform = self.normalize_platform(platform)
        account = self._clean_account(account)
        uid = str(uid or "").strip()
        label = self.platform_label(platform)
        if not platform or not account:
            return False, "参数缺失：请提供要绑定的账号", ""
        if not uid:
            return False, "参数缺失：请先取得用户编号", ""
        with self._lock:
            if not self._acquire():
                return False, "身份表正忙，请稍后再试", ""
            try:
                data = self._load()
                user = data["users"].get(uid)
                if not user:
                    return False, f"没找到编号 {uid}", ""
                key = f"{platform}:{account}"
                owner = str(data["index"].get(key, "") or "")
                if owner and owner != uid:
                    other = data["users"].get(owner) or {}
                    other_name = str(other.get("nickname") or "").strip() or "未设昵称"
                    return False, f"这个{label}账号已经绑在 {owner}（{other_name}）名下，请先解绑或改用其它账号", owner
                old = str((user.get("accounts") or {}).get(platform) or "")
                if old and old != account:
                    data["index"].pop(f"{platform}:{old}", None)
                user.setdefault("accounts", {})[platform] = account
                self._fill_nickname(data, user, nickname)
                data["users"][uid] = user
                data["index"][key] = uid
                self._save(data)
                return True, "", uid
            finally:
                self._release()

    def unbind(self, uid, platform):
        """解绑编号下的某个平台账号，返回 (成功, 提示)"""
        platform = self.normalize_platform(platform)
        uid = str(uid or "").strip()
        label = self.platform_label(platform)
        if not platform:
            return False, "参数缺失：请提供要解绑的平台"
        if not uid:
            return False, "还没绑定过，没有可解绑的账号"
        with self._lock:
            if not self._acquire():
                return False, "身份表正忙，请稍后再试"
            try:
                data = self._load()
                user = data["users"].get(uid)
                if not user:
                    return False, f"没找到编号 {uid}"
                account = str((user.get("accounts") or {}).pop(platform, "") or "")
                if not account:
                    return False, f"你名下没有绑过{label}账号，无需解绑"
                data["index"].pop(f"{platform}:{account}", None)
                data.setdefault("history", {})[f"{platform}:{account}"] = uid
                data["users"][uid] = user
                self._save(data)
                return True, ""
            finally:
                self._release()

    def set_nickname(self, uid, nickname):
        """改昵称，返回 (成功, 提示)"""
        uid = str(uid or "").strip()
        nickname = str(nickname or "").strip()
        if not uid:
            return False, "参数缺失：请先取得用户编号"
        if not nickname:
            return False, "参数缺失：请提供新昵称"
        with self._lock:
            if not self._acquire():
                return False, "身份表正忙，请稍后再试"
            try:
                data = self._load()
                user = data["users"].get(uid)
                if not user:
                    return False, f"没找到编号 {uid}"
                owner = self.nickname_owner(data, nickname, exclude_uid=uid)
                if owner:
                    owner_name = str((data["users"].get(owner) or {}).get("nickname") or owner)
                    return False, f"昵称「{nickname}」已被编号 {owner}（{owner_name}）占用，请换一个"
                user["nickname"] = nickname
                data["users"][uid] = user
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
                    users = [u for u in users if not self.is_temp(u.get("id"))]
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
                for platform, account in (drop.get("accounts") or {}).items():
                    account = str(account or "").strip()
                    if not account:
                        continue
                    key = f"{platform}:{account}"
                    if str(keep.get("accounts", {}).get(platform) or ""):
                        data["index"][key] = keep_uid
                        continue
                    keep.setdefault("accounts", {})[platform] = account
                    data["index"][key] = keep_uid
                drop["accounts"] = {}
                data["users"][drop_uid] = drop
                data["users"][keep_uid] = keep
                index = {}
                for uid, user in data["users"].items():
                    for platform, account in (user.get("accounts") or {}).items():
                        if account:
                            index[f"{platform}:{account}"] = uid
                data["index"] = index
                self._save(data)
                return True, ""
            finally:
                self._release()

    def summary_line(self, uid):
        """把编号、昵称、已绑平台拼成一行，供回复用"""
        user = self.get_user(uid)
        if not user:
            return ""
        nickname = str(user.get("nickname") or "").strip() or "未设昵称"
        if self.is_temp(uid):
            return f"临时身份 {uid}，昵称 {nickname}，还没绑定平台（绑定后自动转正）"
        accounts = user.get("accounts") or {}
        parts = []
        for platform in sorted(accounts.keys()):
            if accounts.get(platform):
                parts.append(f"{self.platform_label(platform)} {accounts.get(platform)}")
        bound = "、".join(parts) if parts else "无"
        return f"编号 {uid}，昵称 {nickname}，已绑：{bound}"
