from func.catbrain.UserMemory.identity.store import IdentityStore
from func.catbrain.UserMemory.identity.bili_lookup import BiliNicknameLookup
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class IdentityCommands:
    DEFAULT_PREFIX = "Meowlisis账号绑定"

    HELP_LINES = [
        "Meowlisis账号绑定 用法：",
        "· 帮助  看这条说明",
        "· qq <QQ号>  在 B站这边发，把填的 QQ 绑到你身上",
        "· bili <uid或昵称>  在 QQ 这边发，把填的 B站账号绑到你身上",
        "· 解绑 <qq|bili>  解绑你名下该平台的账号",
        "· 查看（或 id）  看你的编号、昵称、已绑平台",
        "· 昵称 <新昵称>  改所有平台统一的称呼",
    ]

    GROUP_ALLOWED = {"帮助", "help", "查看", "id", "qq", "bili"}

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.store = IdentityStore()

    def prefix(self):
        """取绑定词前缀，配置里没写就用默认"""
        try:
            from func.pipeline.config_reader import ConfigReader
            cfg = ConfigReader().get("identity", {}) or {}
            return str(cfg.get("bind_prefix") or "").strip() or self.DEFAULT_PREFIX
        except Exception:
            return self.DEFAULT_PREFIX

    def match(self, text):
        """认前缀，命中返回前缀后面的内容，没命中回 None"""
        prefix = self.prefix()
        raw = str(text or "").strip()
        if not raw or not prefix or not raw.startswith(prefix):
            return None
        return raw[len(prefix):].strip()

    def help_text(self, platform=""):
        """拼帮助文案，按平台去掉用不上的那条"""
        platform = self.store.normalize_platform(platform)
        lines = []
        for line in self.HELP_LINES:
            if platform == "qq" and line.startswith("· qq "):
                continue
            if platform == "bili" and line.startswith("· bili "):
                continue
            lines.append(line)
        return "\n".join(lines)

    def handle(self, text, platform, account, name="", group=False):
        """执行一条绑定指令，返回 (是否命中, 回复文本)"""
        rest = self.match(text)
        if rest is None:
            return False, ""
        platform = self.store.normalize_platform(platform)
        account = str(account or "").strip()
        args = [a for a in rest.replace("　", " ").split(" ") if a.strip()]
        if not args:
            return True, self.help_text(platform)
        sub = args[0].strip()
        key = sub.lower()
        if key in ("帮助", "help", "?", "？"):
            return True, self.help_text(platform)
        if group and key not in self.GROUP_ALLOWED:
            return True, "群里只能用「查看」和绑定类指令，其它请私聊"
        if key in ("qq", "bili"):
            return True, self._bind(platform, account, name, key, args)
        if key in ("解绑", "unbind"):
            return True, self._unbind(platform, account, args)
        if key in ("查看", "id", "我的id", "我的"):
            return True, self._view(platform, account, name)
        if key in ("昵称", "nickname", "改名"):
            return True, self._nickname(platform, account, name, args)
        return True, f"不认识的指令「{sub}」\n{self.help_text(platform)}"

    def _bind(self, platform, account, name, key, args):
        """处理 qq / bili 两种绑定：绑定即转正，并把发指令这一侧的账号一起挂上"""
        target = self.store.normalize_platform(key)
        label = self.store.platform_label(target)
        if target == platform:
            other = "bili" if platform == "qq" else "qq"
            return f"你已经在{label}这边了，要绑{label}请到{self.store.platform_label(other)}那边发这条指令"
        if not account:
            return "拿不到你的账号标识，暂时没法绑定，请换个入口再试"
        if len(args) < 2 or not args[1].strip():
            return f"参数缺失：请写成「{self.prefix()} {key} <要绑的账号>」"
        raw = args[1].strip()
        if target == "qq":
            if not raw.isdigit() or not (5 <= len(raw) <= 12):
                return "QQ 号格式不对：请填纯数字的 QQ 号"
            target_account = raw
        else:
            target_account, err = BiliNicknameLookup().lookup(raw)
            if err:
                return err

        mine = self.store.resolve(platform, account)
        uid = self.store.resolve(target, target_account)
        if uid and uid != mine:
            if not self.store.is_temp(uid):
                return f"这个{label}账号已经绑在 {uid} 名下了，请先解绑或改用其它账号"
            uid = self.store.promote(uid)
        if not uid:
            uid = mine or self.store.ensure_temp(platform, account, nickname=name)
        if self.store.is_temp(uid):
            uid = self.store.promote(uid)
        if not uid:
            return "身份表正忙，请稍后再试"
        ok, msg, _owner = self.store.bind(uid, target, target_account, nickname=name)
        if not ok:
            return msg
        self.store.bind(uid, platform, account, nickname=name)
        return f"{label}绑定成功：{self.store.summary_line(uid)}"

    def _unbind(self, platform, account, args):
        """处理解绑"""
        if len(args) < 2 or not args[1].strip():
            return f"参数缺失：请写成「{self.prefix()} 解绑 <qq|bili>」"
        target = self.store.normalize_platform(args[1].strip())
        if target not in ("qq", "bili"):
            return "平台不对：只能填 qq 或 bili"
        label = self.store.platform_label(target)
        uid = self.store.resolve(platform, account)
        if not uid:
            return "还没绑定过，没有可解绑的账号"
        ok, msg = self.store.unbind(uid, target)
        if not ok:
            return msg
        return f"{label}已解绑：{self.store.summary_line(uid)}"

    def _view(self, platform, account, name):
        """处理查看自己的编号：还没绑定的给临时身份"""
        if not account:
            return "拿不到你的账号标识，暂时没法查编号"
        uid = self.store.resolve(platform, account) or self.store.ensure_temp(platform, account, nickname=name)
        if not uid:
            return "身份表正忙，请稍后再试"
        return self.store.summary_line(uid)

    def _nickname(self, platform, account, name, args):
        """处理改昵称"""
        if len(args) < 2 or not args[1].strip():
            return f"参数缺失：请写成「{self.prefix()} 昵称 <新昵称>」"
        if not account:
            return "拿不到你的账号标识，暂时没法改昵称"
        uid = self.store.resolve(platform, account) or self.store.ensure_temp(platform, account, nickname=name)
        if not uid:
            return "身份表正忙，请稍后再试"
        ok, msg = self.store.set_nickname(uid, args[1].strip())
        if not ok:
            return msg
        return f"昵称已更新：{self.store.summary_line(uid)}"
