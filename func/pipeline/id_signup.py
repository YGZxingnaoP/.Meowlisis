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

    def begin(self, platform, account, name=""):
        """平台层进来先登记说话人，并返回统一昵称（没绑定原样返回）

        登记进上下文的必须是统一昵称，否则下游按名字取编号时对不上。
        """
        raw = str(name or "").strip()
        self.set_current(platform, account, raw)
        nickname = ""
        uid = self.current_id()
        if uid:
            nickname = self.nickname_of(uid)
        if not nickname:
            nickname = self.normalize_name(raw)
        self.set_current(platform, account, nickname or raw)
        return nickname or raw

    def id_by_name(self, name):
        """按昵称找编号（临时身份不算），找不到回空串"""
        name = str(name or "").strip()
        if not name:
            return ""
        for user in self.list_users():
            if self._store().is_temp(user.get("id")):
                continue
            if str(user.get("nickname") or "").strip() == name:
                return str(user.get("id") or "")
        return ""

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

    def voice_label(self, uid):
        """声纹文件名该写成什么样：昵称(编号)"""
        user = self.find(uid) or {}
        nickname = str(user.get("nickname") or "").strip() or str(uid)
        return f"{nickname}({uid})"

    def uid_from_text(self, text):
        """从「昵称(编号)」「编号」这类写法里取出编号（临时身份不算）"""
        text = str(text or "").strip()
        match = re.search(r"(\d{6})", text)
        if match and self.find(match.group(1)):
            return match.group(1)
        return ""

    @staticmethod
    def nickname_part(text, uid):
        """从「昵称(编号)」里取出昵称那一段，取不到回空"""
        text = str(text or "").strip()
        if not text:
            return ""
        part = re.sub(r"[（(]\s*" + re.escape(str(uid)) + r"\s*[)）]", "", text)
        if part == text:
            return ""
        return part.strip(" -_·、,，")

    def voice_begin(self, speaker):
        """声纹侧登记：文件名写成「昵称(编号)」就能认出这个人

        称呼按项目统一规则：身份表设了昵称就用昵称，没设置就用文件名里的昵称，再退到原名。
        """
        raw = str(speaker or "").strip()
        uid = self.uid_from_text(raw)
        if not uid:
            self.set_current("voice", raw, raw)
            return raw
        nickname = self.nickname_of(uid) or self.nickname_part(raw, uid) or raw
        self.set_current("voice", raw, nickname)
        return nickname

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

    def _is_pure_placeholder(self, uid):
        """判断编号是不是只有档案、还没挂任何平台账号（迁移出来的裸号）"""
        if self._store().is_temp(uid):
            return False
        accounts = (self.find(uid) or {}).get("accounts") or {}
        return not [p for p in accounts if accounts.get(p)]

    def ensure_for(self, name):
        """取编号并把当前平台账号挂到已有编号上；没绑定的只登记临时身份，仍然走原逻辑"""
        text = str(name or "").strip()
        current = self._current
        same = bool(current) and str(current.get("name") or "").strip() == text
        platform = str(current.get("platform") or "").strip() if current else ""
        account = str(current.get("account") or "").strip() if current else ""
        if same and platform and account:
            bound = self.resolve(platform, account)
            if bound and not self._store().is_temp(bound):
                return bound
            if not self.uid_of(text):
                # 没绑定：发一个临时身份占位，档案照旧写老目录（临时号不能当身份用）
                self._store().ensure_temp(platform, account, nickname=text)
                return ""
        uid = self.uid_of(text)
        if not uid or not (same and platform and account):
            return uid
        ok, _msg, owner = self.bind(uid, platform, account)
        return uid if ok else (owner or uid)

    def normalize_name(self, name):
        """把名字换成统一昵称，没绑定就原样返回"""
        uid = self.uid_of(name)
        if not uid:
            return str(name or "")
        user = self.find(uid)
        return str(user.get("nickname") or "").strip() or str(name or "")

    def user_dir(self, uid):
        """取编号目录：跟着身份表的根目录走，测试切根就整块切走"""
        root = getattr(self._store(), "dir", os.path.join("character", "userinfo"))
        return os.path.join(root, str(uid))

    def profile_path(self, uid):
        """取编号对应的档案路径"""
        return os.path.join(self.user_dir(uid), "profile.json")

    def backlog_path(self, uid):
        """取编号对应的待办路径"""
        return os.path.join(self.user_dir(uid), "backlog.json")

    def record_path(self, uid):
        """取编号对应的短期记录路径"""
        root = getattr(self._store(), "record_root", ".temp")
        return os.path.join(root, f"{str(uid)}_record.txt")

    @staticmethod
    def safe_name(name):
        """把名字清洗成能当文件名的形式"""
        text = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(name or "").strip())
        return text or "空格"

    def legacy_record_path(self, name):
        """取老位置里按名字命名的记录路径"""
        root = getattr(self._store(), "record_root", ".temp")
        return os.path.join(root, f"{self.safe_name(name)}_record.txt")

    def record_path_of(self, name):
        """取短期记录路径：有编号就用编号命名，没绑定照旧用名字"""
        uid = self.uid_of(str(name or "").strip())
        if uid:
            return self.record_path(uid)
        return self.legacy_record_path(name)

    def legacy_profile_path(self, name):
        """取老目录里按名字命名的档案路径"""
        safe = str(name or "").strip()
        for ch in '\\/:*?"<>|\r\n\t':
            safe = safe.replace(ch, "_")
        return os.path.join("character", "info", "users_info", f"{safe}_latest.json")

    def nickname_of(self, uid):
        """取编号的昵称"""
        return str((self.find(uid) or {}).get("nickname") or "").strip()

    @staticmethod
    def _safe(name):
        """把名字清洗成能当文件名的形式"""
        text = str(name or "").strip()
        for ch in '\\/:*?"<>|\r\n\t':
            text = text.replace(ch, "_")
        return text or "unnamed"

    def legacy_backlog_path(self, name):
        """取老目录里按名字命名的待办路径"""
        return os.path.join("character", "backlog", f"{self._safe(name)}.json")

    def backlog_path_of(self, name):
        """取待办落盘路径：有编号进编号目录，没有照旧"""
        uid = self.uid_of(name)
        if uid:
            return self.backlog_path(uid)
        return self.legacy_backlog_path(name)

    def read_json_file(self, path):
        """读一个 json 文件，读不到回空 dict"""
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception(f"读取文件失败: {path}")
        return {}

    def read_backlog(self, name):
        """取待办：先编号目录，再老目录"""
        for path in (self.backlog_path_of(name), self.legacy_backlog_path(name)):
            data = self.read_json_file(path)
            if data:
                return data
        return {}

    def save_backlog(self, name, data):
        """把待办写到该用户该在的位置，返回路径"""
        path = self.backlog_path_of(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = dict(data or {})
        payload["username"] = payload.get("username") or name
        if not isinstance(payload.get("to_do_list"), list):
            payload["to_do_list"] = []
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def backlog_entries(self):
        """列出全部待办，返回 [(名字, 数据)]，编号目录优先、老目录去重"""
        entries = []
        names = set()
        root = os.path.join("character", "userinfo")
        if os.path.isdir(root):
            for uid in sorted(os.listdir(root)):
                data = self.read_json_file(os.path.join(root, uid, "backlog.json"))
                if not data:
                    continue
                name = self.nickname_of(uid) or str(data.get("username") or uid)
                entries.append((name, data))
                names.add(str(data.get("username") or "").strip())
                names.add(name)
        legacy = os.path.join("character", "backlog")
        if os.path.isdir(legacy):
            for fname in sorted(os.listdir(legacy)):
                if not fname.endswith(".json"):
                    continue
                data = self.read_json_file(os.path.join(legacy, fname))
                if not data:
                    continue
                name = str(data.get("username") or "").strip() or fname[:-5]
                if name in names:
                    continue
                entries.append((name, data))
        return entries

    def resolve_name(self, name):
        """按名字取编号（读侧宽松版）：编号、昵称都能认，不要求是当前说话人"""
        text = str(name or "").strip()
        if not text or self._store().is_temp(text):
            return ""
        if len(text) == 6 and text.isdigit() and self.find(text):
            return text
        uid = self.uid_from_text(text)
        if uid:
            return uid
        return self.id_by_name(text)

    def profile_path_of(self, name):
        """按名字定档案路径：认得出编号就用编号目录，认不出才照旧老目录"""
        uid = self.resolve_name(name)
        if uid:
            return self.profile_path(uid)
        return self.legacy_profile_path(name)

    def profile_of(self, name):
        """按名字读档案，新老位置都找"""
        for path in (self.profile_path_of(name), self.legacy_profile_path(name)):
            try:
                if path and os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict) and data:
                        return data
            except Exception:
                self.log.exception(f"读取用户档案失败: {path}")
        return {}

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

    def display_name(self, platform, account, fallback=""):
        """取展示名：身份表昵称优先，没有回退原名字"""
        return self._store().display_name(platform, account, fallback)

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

    def migrate_user(self, name):
        """把一个老档案名字整体搬进编号目录"""
        return self._merge().migrate(name)

    def merge_plan(self, keys):
        """打出合并方案"""
        return self._merge().plan(keys)

    def merge_apply(self, keys, keep="", dry_run=True):
        """执行或预演合并"""
        return self._merge().apply(keys, keep=keep, dry_run=dry_run)
