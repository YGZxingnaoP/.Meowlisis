from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class BiliNicknameLookup:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.sessdata, self.bili_jct = self._load_credential()

    @staticmethod
    def _load_credential():
        """读取 B站登录态：只认身份模块自己的 identity.sessdata / identity.bili_jct。

        身份模块不读别的模块的配置（尤其不读 llm_active / danmaku）：
        用哪个模块的 B站 能力，就在那个模块自己的配置里配登录态。
        """
        from func.pipeline.config_reader import ConfigReader
        cfg = ConfigReader().get("identity", {}) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        return (str(cfg.get("sessdata", "") or "").strip(),
                str(cfg.get("bili_jct", "") or "").strip())

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
        # 多个结果时取「完全同名」的那个（B站搜索把同名排最前，第 2 个起是模糊匹配的人）；
        # 没有完全同名就取第 1 个 —— 宁可认第 1 个，也不因为"结果有多个"把这条消息丢掉。
        exact = [u for u in users if u["uname"] == keyword]
        hit = (exact or users)[0]
        if len(users) > 1:
            names = "、".join([f"{u['uname']}({u['mid']})" for u in users[:5]])
            self.log.info(f"[BiliLookup] 昵称「{keyword}」命中 {len(users)} 个，"
                          f"采用 {hit['uname']}({hit['mid']})；候选：{names}")
        return str(hit["mid"]), ""
