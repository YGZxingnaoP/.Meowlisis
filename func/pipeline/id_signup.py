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

    def set_current(self, channel, ext_account, name=""):
        """平台层进来先登记当前说话人，供后面取身份与档案落盘"""
        self._current = {
            "channel": str(channel or "").strip(),
            "ext_account": str(ext_account or "").strip(),
            "name": str(name or "").strip(),
        }

    def current(self):
        """取当前登记的说话人"""
        return dict(self._current)

    # ==================== 身份标准入口（词表见 docs/meowid.md）====================
    # channel ∈ {qq, bili, msg}
    #   qq  / bili : 必须带外部账号（QQ号 / B站uid）→ 反查 meowid → 查不到就建档
    #   msg        : 必须直接带 meowid（来源 msg_from ∈ voice / api / phone），不反查
    CHANNEL_QQ = "qq"
    CHANNEL_BILI = "bili"
    CHANNEL_MSG = "msg"
    CHANNEL_LOCAL = "local"
    CHANNEL_VOICE = "voice"
    MSG_FROM_VOICE = "voice"
    MSG_FROM_API = "api"
    MSG_FROM_PHONE = "phone"

    def meowid_of_account(self, channel, ext_account="", ext_name="") -> str:
        """【qq / bili 通道唯一入口】外部账号 → meowid。

        - 必须带 `ext_account`（QQ号 / B站uid）；不带就是调用方的 bug，直接失败。
        - 先反查，查不到就建档（铁律一：说一句话就该有 meowid）。
        - nickname 沿用原逻辑：**首次建档时**用该通道的外部显示名（ext_name）填一次，
          之后由项目自己维护（set_nickname），不再被外部覆盖。
        """
        channel = str(channel or "").strip()
        ext_account = str(ext_account or "").strip()
        ext_name = str(ext_name or "").strip()
        if channel not in (self.CHANNEL_QQ, self.CHANNEL_BILI):
            self.log.error(f"[meowid] 非帐号通道不许反查：channel={channel!r}")
            return ""
        if not ext_account:
            self.log.error(f"[meowid] {channel} 通道必须提供外部账号 ext_account")
            return ""
        meowid = self.resolve(channel, ext_account)
        if meowid:
            return meowid
        return str(self._store().ensure_temp(channel, ext_account, nickname=ext_name) or "")

    def meowid_of_msg(self, ref="", msg_from="") -> str:
        """【msg 通道唯一入口（voice / api / phone）】把入参解析成 meowid，保证返回 meowid。

        解析顺序写死在这里（别处不许再猜）：
          ① 入参本身就是 meowid（000001 / temp-000012）且身份表里有 → 用它
          ② 身份表里唯一的昵称 → 用它（手机浏览器输昵称就靠这条）
          ③ 声纹 / 本机名字（离线账号 local:<名>、voice:<名>）→ 用它
          ④ 都没有 → 建档（铁律一：说一句话就该有 meowid），入参当昵称
        拿不到任何可用文本 → 明确失败。
        """
        ref = str(ref or "").strip()
        msg_from = str(msg_from or "").strip() or self.MSG_FROM_API
        if msg_from not in (self.MSG_FROM_VOICE, self.MSG_FROM_API, self.MSG_FROM_PHONE):
            self.log.error(f"[meowid] msg 来源不合法：msg_from={msg_from!r}")
            return ""
        if not ref:
            self.log.error(f"[meowid] msg({msg_from}) 没带身份：必须给 meowid 或昵称")
            return ""
        # ① meowid 直查
        if self.is_internal_uid(ref) and self.find(ref):
            return ref
        # ② 昵称（含临时身份昵称）
        meowid = self.uid_of_name(ref)
        if meowid:
            return meowid
        # ③ 声纹 / 本机名字
        for ch in (self.CHANNEL_LOCAL, self.CHANNEL_VOICE):
            meowid = str(self._store().resolve(ch, ref) or "")
            if meowid:
                return meowid
        # ④ 铁律一：建档
        return str(self._store().ensure_temp(self.CHANNEL_LOCAL, ref, nickname=ref) or "")


    @staticmethod
    def is_internal_uid(value) -> bool:
        """判断是不是内部编号（六位数字 000001 / 临时身份 temp-000010）。

        身份标准：内部编号是唯一的「身份键」，昵称、QQ 号、open_id 都不是。
        """
        text = str(value or "").strip()
        return bool(re.fullmatch(r"\d{6}", text) or re.fullmatch(r"temp-\d{6}", text))

    def id_by_name(self, name):
        """按昵称找编号（临时身份不算），找不到回空串"""
        name = str(name or "").strip()
        if not name:
            return ""
        hits = []
        for user in self.list_users():
            if self._store().is_temp(user.get("meowid")):
                continue
            if str(user.get("nickname") or "").strip() == name:
                hits.append(str(user.get("meowid") or ""))
        if len(hits) > 1:
            warned = getattr(self, "_ambiguous_warned", None)
            if warned is None or len(warned) > 64:
                warned = self._ambiguous_warned = set()
            if name not in warned:
                warned.add(name)
                self.log.warning(f"昵称「{name}」对应多个编号 {hits}，按名字取身份被拒绝，请改用编号或绑定平台账号")
            return ""
        return hits[0] if hits else ""

    def channel_options(self):
        """列出全部通道（含离线占位），供界面逐通道展示"""
        from func.catbrain.UserMemory.identity.store import KNOWN_CHANNELS
        return [{"key": p, "label": self._store().channel_label(p)} for p in KNOWN_CHANNELS]

    def user_detail(self, key):
        """查一个用户的详情，带上全部通道与该通道当前外部账号"""
        user = self.find(key)
        if not user:
            return {}
        meowid = str(user.get("meowid") or "")
        accounts = user.get("ext_accounts") or {}
        profile = self.profile_of(meowid)
        return {
            "meowid": meowid,
            "nickname": str(user.get("nickname") or ""),
            "affinity": profile.get("affinity", 0),
            "birthday": str(profile.get("birthday") or ""),
            "channels": [
                {"key": item["key"], "label": item["label"],
                 "ext_account": str(accounts.get(item["key"]) or "")}
                for item in self.channel_options()
            ],
        }

    def uid_of(self, name):
        """按名字取编号：当前账号优先，其次是名字本身为编号，最后按昵称且不撞真人（临时身份不算身份）"""
        text = str(name or "").strip()
        if self._store().is_temp(text):
            return ""
        current = self._current
        same = bool(current) and str(current.get("nickname") or "").strip() == text
        if same:
            meowid = self.current_id()
            if meowid and not self._store().is_temp(meowid):
                return meowid
        if len(text) == 6 and text.isdigit() and self.find(text):
            return text
        meowid = self.uid_from_text(text)
        if meowid:
            return meowid
        meowid = self.id_by_name(text)
        if not meowid:
            return ""
        if self._is_pure_placeholder(meowid):
            return meowid
        if same and self.current_id() == meowid:
            return meowid
        return ""

    def nickname_of(self, meowid):
        return str((self.find(meowid) or {}).get("nickname") or "").strip()

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

    def user_dir(self, meowid):
        root = getattr(self._store(), "dir", os.path.join("character", "userinfo"))
        return os.path.join(root, str(meowid))

    def profile_path(self, meowid):
        return os.path.join(self.user_dir(meowid), "profile.json")

    def record_path(self, meowid):
        root = getattr(self._store(), "record_root", ".temp")
        return os.path.join(root, f"{str(meowid)}_record.txt")

    def backlog_path(self, meowid):
        return os.path.join(self.user_dir(meowid), "backlog.json")

    def uid_of_name(self, name) -> str:
        """名字 → 内部编号。**纯查，绝不创建身份**。

        只接受「内部编号」或「身份表里唯一的昵称」；查不到返回 ""，调用方必须走失败分支。
        """
        text = str(name or "").strip()
        if not text:
            return ""
        meowid = self.resolve_name(text)
        if meowid:
            return meowid
        # 临时身份不参与 id_by_name 匹配，这里显式补一次「按昵称找临时身份」（仍是纯查）
        try:
            for key, user in (self._store()._load().get("users") or {}).items():
                if self._store().is_temp(key) and str((user or {}).get("nickname") or "").strip() == text:
                    return str(key)
        except Exception:
            self.log.exception("按昵称找临时身份失败")
        return ""

    def require_uid(self, name) -> str:
        """把入参解析成内部编号；查不到记 ERROR 并返回 ""（不创建身份、不用别的值顶替）。"""
        meowid = self.uid_of_name(name)
        if not meowid:
            self.log.error(f"[id_signup] 入参不是有效身份（禁止用昵称/QQ号/裸编号占位）: {name!r}")
        return meowid

    def resolve_name(self, name):
        text = str(name or "").strip()
        if not text:
            return ""
        if self._store().is_temp(text):
            return text
        if len(text) == 6 and text.isdigit() and self.find(text):
            return text
        meowid = self.uid_from_text(text)
        if meowid:
            return meowid
        return self.id_by_name(text)

    def profile_path_of(self, name):
        meowid = self.require_uid(name)
        return self.profile_path(meowid) if meowid else ""

    def profile_of(self, name):
        data = self.read_json_file(self.profile_path_of(name))
        return data if isinstance(data, dict) else {}

    def record_path_of(self, name):
        meowid = self.require_uid(name)
        return self.record_path(meowid) if meowid else ""


    def read_backlog(self, name):
        meowid = self.require_uid(name)
        if not meowid:
            return {}
        data = self.read_json_file(self.backlog_path(meowid))
        if isinstance(data, dict):
            data["meowid"] = meowid
            return data
        return {}

    def save_backlog(self, name, data):
        meowid = self.require_uid(name)
        if not meowid:
            return ""
        path = self.backlog_path(meowid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = dict(data or {})
        payload["meowid"] = meowid
        payload["nickname"] = display_name(meowid)     # 展示位：唯一规则，禁止写 meowid/传入值
        if not isinstance(payload.get("to_do_list"), list):
            payload["to_do_list"] = []
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def backlog_entries(self):
        entries = []
        root = os.path.join("character", "userinfo")
        if os.path.isdir(root):
            for meowid in sorted(os.listdir(root)):
                data = self.read_json_file(os.path.join(root, meowid, "backlog.json"))
                if not data:
                    continue
                data["meowid"] = meowid
                entries.append((display_name(meowid), data))
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

    def current_id(self):
        """按当前登记的说话人取编号；账号里带编号（昵称(编号)）或账号就是编号都能用"""
        current = self._current
        if not current:
            return ""
        ext_account = str(current.get("ext_account") or "").strip()
        meowid = self.uid_from_text(ext_account)
        if meowid:
            return meowid
        meowid = self.resolve(current.get("channel"), ext_account)
        return "" if self._store().is_temp(meowid) else meowid

    def uid_from_text(self, text):
        """从「昵称(编号)」「编号」这类写法里取出编号（临时身份不算）"""
        text = str(text or "").strip()
        match = re.search(r"(\d{6})", text)
        if match and self.find(match.group(1)):
            return match.group(1)
        return ""

    def _is_pure_placeholder(self, meowid):
        """判断编号是不是只有档案、还没挂任何平台账号（迁移出来的裸号）"""
        if self._store().is_temp(meowid):
            return False
        accounts = (self.find(meowid) or {}).get("ext_accounts") or {}
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

    def handle_command(self, text, channel, ext_account, name="", group=False):
        """执行绑定指令，返回 (是否命中, 回复文本)"""
        return self._commands().handle(text, channel, ext_account, name=name, group=group)

    def help_text(self, channel=""):
        """取帮助文案"""
        return self._commands().help_text(channel)

    def resolve(self, channel, ext_account):
        """平台加账号 → 编号，查不到回空串"""
        return self._store().resolve(channel, ext_account)

    def bind(self, meowid, channel, ext_account, nickname=""):
        """绑定平台账号"""
        return self._store().bind(meowid, channel, ext_account, nickname=nickname)

    def unbind(self, meowid, channel):
        """解绑平台账号"""
        return self._store().unbind(meowid, channel)

    def set_nickname(self, meowid, nickname):
        """改昵称"""
        return self._store().set_nickname(meowid, nickname)

    def summary(self, meowid):
        """取编号、昵称、已绑平台那一行"""
        return self._store().summary_line(meowid)

    def list_users(self, include_temp=False):
        """列出全部用户（默认不含临时身份）"""
        return self._store().list_users(include_temp=include_temp)

    def find(self, key):
        """按编号或昵称取用户"""
        return self._store().get_user(key)

    def lookup_bili(self, keyword):
        """按昵称反查 B站 meowid，返回 (meowid, 失败原因)"""
        from func.catbrain.UserMemory.identity.bili_lookup import BiliNicknameLookup
        return BiliNicknameLookup().lookup(keyword)

    def new_user(self, nickname=""):
        """按昵称开编号，已有同昵称的就返回原编号"""
        meowid = self.id_by_name(nickname)
        if meowid:
            return meowid
        return self._store().create_user(nickname)


def display_name(value) -> str:
    """【唯一展示规则】meowid / 名字 → 展示名（只读映射：不创建身份、不改数据、不猜测）。

    沿用原逻辑：能查到 nickname 就用 nickname；查不到**原样返回入参**。
    （正常情况下 nickname 已在建档时用 QQ名片 / B站昵称 填过，见 docs/meowid.md §5）
    """
    try:
        return IdSignupBridge().nickname_of(value) or str(value or "")
    except Exception:
        return str(value or "")
