import json
import os
import re

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class IdSignupBridge:
    """用户身份桥接（单例）：平台账号 ↔ 六位编号 ↔ 昵称，全系统唯一数据通道"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._current = {}

    def set_current(self, platform, account, name=""):
        """平台层进来先登记当前说话人，供后面取身份与档案落盘"""
        self._current = {
            "platform": str(platform or "").strip(),
            "account": str(account or "").strip(),
            "name": str(name or "").strip(),
        }

    def current(self):
        """取当前登记的说话人"""
        return dict(self._current)

    def resolve_identity(self, platform, account):
        platform = str(platform or "").strip()
        account = str(account or "").strip()
        if not account:
            return {"uid": "", "nickname": "", "platform": platform, "account": ""}
        uid = ""
        try:
            uid = self.resolve(platform, account) or self.resolve_name(account)
            if not uid:
                uid = str(self._store().ensure_temp(platform, account) or "")
        except Exception:
            self.log.exception("解析身份失败")
        return {"uid": str(uid or ""), "nickname": self.nickname_of(uid) if uid else "",
                "platform": platform, "account": account}

    def id_by_name(self, name):
        """按昵称找编号（临时身份不算），找不到回空串"""
        name = str(name or "").strip()
        if not name:
            return ""
        hits = []
        for user in self.list_users():
            if self._store().is_temp(user.get("id")):
                continue
            if str(user.get("nickname") or "").strip() == name:
                hits.append(str(user.get("id") or ""))
        if len(hits) > 1:
            warned = getattr(self, "_ambiguous_warned", None)
            if warned is None or len(warned) > 64:
                warned = self._ambiguous_warned = set()
            if name not in warned:
                warned.add(name)
                self.log.warning(f"昵称「{name}」对应多个编号 {hits}，按名字取身份被拒绝，请改用编号或绑定平台账号")
            return ""
        return hits[0] if hits else ""

    def platform_options(self):
        """列出全部平台（含离线占位），供界面逐平台展示"""
        from func.catbrain.UserMemory.identity.store import KNOWN_PLATFORMS
        return [{"key": p, "label": self._store().platform_label(p)} for p in KNOWN_PLATFORMS]

    def user_detail(self, key):
        """查一个用户的详情，带上全部平台与该平台当前账号"""
        user = self.find(key)
        if not user:
            return {}
        uid = str(user.get("id") or "")
        accounts = user.get("accounts") or {}
        profile = self.profile_of(self.nickname_of(uid) or uid)
        return {
            "id": uid,
            "nickname": str(user.get("nickname") or ""),
            "affinity": profile.get("affinity", 0),
            "birthday": str(profile.get("birthday") or ""),
            "platforms": [
                {"key": item["key"], "label": item["label"],
                 "account": str(accounts.get(item["key"]) or "")}
                for item in self.platform_options()
            ],
        }

    def uid_of(self, name):
        """按名字取编号：当前账号优先，其次是名字本身为编号，最后按昵称且不撞真人（临时身份不算身份）"""
        text = str(name or "").strip()
        if self._store().is_temp(text):
            return ""
        current = self._current
        same = bool(current) and str(current.get("name") or "").strip() == text
        if same:
            uid = self.current_id()
            if uid and not self._store().is_temp(uid):
                return uid
        if len(text) == 6 and text.isdigit() and self.find(text):
            return text
        uid = self.uid_from_text(text)
        if uid:
            return uid
        uid = self.id_by_name(text)
        if not uid:
            return ""
        if self._is_pure_placeholder(uid):
            return uid
        if same and self.current_id() == uid:
            return uid
        return ""

    def nickname_of(self, uid):
        return str((self.find(uid) or {}).get("nickname") or "").strip()

    @staticmethod
    def read_json_file(path):
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
        return {}

    def user_dir(self, uid):
        root = getattr(self._store(), "dir", os.path.join("character", "userinfo"))
        return os.path.join(root, str(uid))

    def profile_path(self, uid):
        return os.path.join(self.user_dir(uid), "profile.json")

    def record_path(self, uid):
        root = getattr(self._store(), "record_root", ".temp")
        return os.path.join(root, f"{str(uid)}_record.txt")

    def backlog_path(self, uid):
        return os.path.join(self.user_dir(uid), "backlog.json")

    def uid_or_temp(self, name):
        text = str(name or "").strip()
        uid = self.resolve_name(text)
        if uid:
            return uid
        if not text:
            return ""
        try:
            for key, user in (self._store()._load().get("users") or {}).items():
                if self._store().is_temp(key) and str((user or {}).get("nickname") or "").strip() == text:
                    return str(key)
        except Exception:
            self.log.exception("按昵称找临时身份失败")
        return str(self._store().ensure_temp("local", text, nickname=text) or "")

    def resolve_name(self, name):
        text = str(name or "").strip()
        if not text:
            return ""
        if self._store().is_temp(text):
            return text
        if len(text) == 6 and text.isdigit() and self.find(text):
            return text
        uid = self.uid_from_text(text)
        if uid:
            return uid
        return self.id_by_name(text)

    def profile_path_of(self, name):
        return self.profile_path(self.uid_or_temp(name))

    def profile_of(self, name):
        data = self.read_json_file(self.profile_path_of(name))
        return data if isinstance(data, dict) else {}

    def record_path_of(self, name):
        return self.record_path(self.uid_or_temp(name))


    def read_backlog(self, name):
        uid = self.uid_or_temp(name)
        data = self.read_json_file(self.backlog_path(uid))
        if isinstance(data, dict):
            data["uid"] = uid
            return data
        return {}

    def save_backlog(self, name, data):
        uid = self.uid_or_temp(name)
        path = self.backlog_path(uid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = dict(data or {})
        payload["uid"] = uid
        payload["username"] = payload.get("username") or name
        if not isinstance(payload.get("to_do_list"), list):
            payload["to_do_list"] = []
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def backlog_entries(self):
        entries = []
        root = os.path.join("character", "userinfo")
        if os.path.isdir(root):
            for uid in sorted(os.listdir(root)):
                data = self.read_json_file(os.path.join(root, uid, "backlog.json"))
                if not data:
                    continue
                data["uid"] = uid
                entries.append((self.nickname_of(uid) or uid, data))
        return entries

    @staticmethod
    def safe_name(name):
        text = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(name or "").strip())
        return text or "空格"

    @staticmethod
    def _safe(name):
        text = str(name or "").strip()
        for ch in '\\/:*?"<>|\r\n\t':
            text = text.replace(ch, "_")
        return text or "unnamed"

    def display_name(self, platform, account, fallback=""):
        """取展示名：身份表昵称优先，没有回退原名字"""
        return self._store().display_name(platform, account, fallback)


    def current_id(self):
        """按当前登记的说话人取编号；账号里带编号（昵称(编号)）或账号就是编号都能用"""
        current = self._current
        if not current:
            return ""
        account = str(current.get("account") or "").strip()
        uid = self.uid_from_text(account)
        if uid:
            return uid
        uid = self.resolve(current.get("platform"), account)
        return "" if self._store().is_temp(uid) else uid

    def uid_from_text(self, text):
        """从「昵称(编号)」「编号」这类写法里取出编号（临时身份不算）"""
        text = str(text or "").strip()
        match = re.search(r"(\d{6})", text)
        if match and self.find(match.group(1)):
            return match.group(1)
        return ""

    def _is_pure_placeholder(self, uid):
        """判断编号是不是只有档案、还没挂任何平台账号（迁移出来的裸号）"""
        if self._store().is_temp(uid):
            return False
        accounts = (self.find(uid) or {}).get("accounts") or {}
        return not [p for p in accounts if accounts.get(p)]

    def migrate_user(self, name):
        """把一个老档案名字整体搬进编号目录"""
        return self._merge().migrate(name)

    def merge_plan(self, keys):
        """打出合并方案"""
        return self._merge().plan(keys)

    def merge_apply(self, keys, keep="", dry_run=True):
        """执行或预演合并"""
        return self._merge().apply(keys, keep=keep, dry_run=dry_run)

    def affinity(self, name):
        """取好感度，读不到算 0"""
        value = self.profile_of(name).get("affinity", 0)
        try:
            return int(value)
        except Exception:
            return 0

    def _store(self):
        """取身份表"""
        from func.catbrain.UserMemory.identity.store import IdentityStore
        return IdentityStore()

    def _commands(self):
        """取指令执行器"""
        from func.catbrain.UserMemory.identity.commands import IdentityCommands
        return IdentityCommands()

    def _merge(self):
        """取合并器"""
        from func.catbrain.UserMemory.identity.merge import UserMerge
        return UserMerge()

    def prefix(self):
        """取绑定词前缀"""
        return self._commands().prefix()

    def is_command(self, text):
        """判断一条消息是不是绑定指令"""
        return self._commands().match(text) is not None

    def handle_command(self, text, platform, account, name="", group=False):
        """执行绑定指令，返回 (是否命中, 回复文本)"""
        return self._commands().handle(text, platform, account, name=name, group=group)

    def help_text(self, platform=""):
        """取帮助文案"""
        return self._commands().help_text(platform)

    def resolve(self, platform, account):
        """平台加账号 → 编号，查不到回空串"""
        return self._store().resolve(platform, account)

    def normalize(self, platform, account, name=""):
        """统一取身份入口：有绑定回昵称，没绑定原样返回"""
        account = str(account or "").strip()
        if not account:
            return str(name or "")
        return self._store().display_name(platform, account, name)

    def ensure(self, platform, account, nickname=""):
        """拿编号，没有就开户"""
        return self._store().ensure(platform, account, nickname=nickname)

    def bind(self, uid, platform, account, nickname=""):
        """绑定平台账号"""
        return self._store().bind(uid, platform, account, nickname=nickname)

    def unbind(self, uid, platform):
        """解绑平台账号"""
        return self._store().unbind(uid, platform)

    def set_nickname(self, uid, nickname):
        """改昵称"""
        return self._store().set_nickname(uid, nickname)

    def summary(self, uid):
        """取编号、昵称、已绑平台那一行"""
        return self._store().summary_line(uid)

    def list_users(self, include_temp=False):
        """列出全部用户（默认不含临时身份）"""
        return self._store().list_users(include_temp=include_temp)

    def find(self, key):
        """按编号或昵称取用户"""
        return self._store().get_user(key)

    def lookup_bili(self, keyword):
        """按昵称反查 B站 uid，返回 (uid, 失败原因)"""
        from func.catbrain.UserMemory.identity.bili_lookup import BiliNicknameLookup
        return BiliNicknameLookup().lookup(keyword)

    def new_user(self, nickname=""):
        """按昵称开编号，已有同昵称的就返回原编号"""
        uid = self.id_by_name(nickname)
        if uid:
            return uid
        return self._store().create_user(nickname)


def display_name(value) -> str:
    """编号/名字 -> 显示名：只做只读映射，认不出原样返回，不创建身份"""
    try:
        return IdSignupBridge().nickname_of(value) or str(value or "")
    except Exception:
        return str(value or "")
