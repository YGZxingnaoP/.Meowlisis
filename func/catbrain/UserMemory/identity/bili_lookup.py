from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class BiliNicknameLookup:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.sessdata, self.bili_jct = self._load_credential()

    @staticmethod
    def _load_credential():
        """复用项目自己的 B站登录态，先读 llm_active，再回退 danmaku"""
        from func.pipeline.config_reader import ConfigReader
        cfg = ConfigReader().get("llm_active", {}) or {}
        web_browse = cfg.get("web_browse", {}) if isinstance(cfg, dict) else {}
        sessdata = str(web_browse.get("sessdata", "") or "").strip()
        bili_jct = str(web_browse.get("bili_jct", "") or "").strip()
        if not sessdata or not bili_jct:
            danmaku = ConfigReader().get("danmaku", {}) or {}
            blivedm = danmaku.get("blivedm", {}) if isinstance(danmaku, dict) else {}
            sessdata = sessdata or str(blivedm.get("sessdata", "") or "").strip()
            bili_jct = bili_jct or str(blivedm.get("bili_jct", "") or "").strip()
        return sessdata, bili_jct

    def _credential(self):
        """构造 bilibili_api 的登录态对象"""
        from bilibili_api import Credential
        return Credential(sessdata=self.sessdata, bili_jct=self.bili_jct)

    def search_users(self, keyword):
        """按昵称搜 B站用户，返回 [{mid, uname}]"""
        from bilibili_api import search, sync
        try:
            from bilibili_api import request_settings
            request_settings.set_enable_bili_ticket(True)
        except Exception:
            pass
        try:
            from bilibili_api.search import SearchObjectType
            search_type = SearchObjectType.USER
        except Exception:
            search_type = 2
        res = sync(search.search_by_type(str(keyword or "").strip(), search_type=search_type))
        items = (res or {}).get("result") or []
        users = []
        for item in items:
            mid = str(item.get("mid") or "").strip()
            if mid:
                users.append({"mid": mid, "uname": str(item.get("uname") or "").strip()})
        return users

    def lookup(self, keyword):
        """拿 uid 或昵称换 uid，返回 (uid, 失败原因)"""
        keyword = str(keyword or "").strip()
        if not keyword:
            return "", "参数缺失：请提供 B站 uid 或昵称"
        if keyword.isdigit():
            return keyword, ""
        try:
            users = self.search_users(keyword)
        except Exception:
            self.log.exception("B站昵称反查失败")
            return "", "B站昵称反查失败，请稍后再试，或直接填 uid"
        if not users:
            return "", f"没查到昵称「{keyword}」的 B站账号，请直接填 uid"
        if len(users) > 1:
            names = "、".join([f"{u['uname']}({u['mid']})" for u in users[:5]])
            return "", f"昵称「{keyword}」匹配到多个账号：{names}，请直接填 uid"
        return str(users[0]["mid"]), ""
