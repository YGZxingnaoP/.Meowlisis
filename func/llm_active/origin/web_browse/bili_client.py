# -*- coding: utf-8 -*-
# func/llm_active/origin/web_browse/bili_client.py
# B站客户端：读 llm_active.web_browse 自己的登录态（SESSDATA/bili_jct）封装 bilibili_api 的同步调用

import asyncio
import random
from typing import Dict, Optional

from func.log.default_log import DefaultLog
from func.llm_active.origin.web_browse.config import AutoWebBrowseConfig

# 修过 cookie 的 Credential 子类（延迟构造，只建一次）
_CREDENTIAL_CLS = None


def _get_credential_cls():
    """返回修过 get_cookies 的 Credential 子类。

    bilibili_api 的 Credential.get_cookies() 末尾会把 self.__dict__ 里所有字段
    也塞进 cookies，而 dataclass 字段名是小写（sessdata / dedeuserid），于是请求
    同时带上 SESSDATA 和小写 sessdata 两枚同名不同大小写的 cookie。B站网关判定
    请求异常，所有需要鉴权的接口直接返回 -101「账号未登录」—— 表现就是登录态被
    静默降级成匿名（首页推荐退回全站热门池，AI 总结/字幕全部拿不到，且不报错）。

    这里只重写 get_cookies，输出规范键（大写）。注意 buvid3 / buvid4 /
    ac_time_value 即使为空也必须保留键，bilibili_api 内部会直接读这几个键。
    """
    global _CREDENTIAL_CLS
    if _CREDENTIAL_CLS is not None:
        return _CREDENTIAL_CLS

    from bilibili_api import Credential

    class FixedCredential(Credential):
        """只输出规范键 cookie，去掉小写重复项"""

        def get_cookies(self):
            cookies = {
                "SESSDATA": self.sessdata if self.sessdata else "",
                "buvid3": self.buvid3 if self.buvid3 else "",
                "buvid4": self.buvid4 if self.buvid4 else "",
                "bili_jct": self.bili_jct if self.bili_jct else "",
                "ac_time_value": self.ac_time_value if self.ac_time_value else "",
            }
            if self.dedeuserid:
                cookies["DedeUserID"] = self.dedeuserid
            return cookies

    _CREDENTIAL_CLS = FixedCredential
    return FixedCredential


# bili_ticket 兜底是否已安装
_TICKET_PATCHED = False


def _patch_bili_ticket():
    """让 bili_ticket 生成失败时降级，而不是抛异常把整条链路打死。

    bilibili_api 的 _get_bili_ticket() 结尾直接 resp.json()["data"]["ticket"]，
    没有任何兜底；而该接口在当前环境下（带登录态）恒返回 -111，因为它的 csrf
    参数被写死成空串。一旦开启了 request_settings.set_enable_bili_ticket(True)，
    每个请求都会先走这一步，KeyError: 'data' 会让首页推荐、视频信息、AI 总结
    全部拿不到，且只在采集层被 except 吞掉（表现为“首页推荐为空”，很难定位）。

    兜底策略：第一次获取失败后立刻把 bili_ticket 全局开关关掉，后续请求完全
    不再走这条路径（也不再发多余请求），浏览功能不受影响。
    """
    global _TICKET_PATCHED
    if _TICKET_PATCHED:
        return
    try:
        from bilibili_api.utils import network
    except Exception:
        return

    orig_ticket = network.get_bili_ticket
    state = {"failed": False}
    log = DefaultLog().getLogger()

    async def _safe_get_bili_ticket(credential=None):
        if state["failed"]:
            return "", ""
        try:
            return await orig_ticket(credential)
        except Exception as e:
            state["failed"] = True
            try:
                from bilibili_api import request_settings
                request_settings.set_enable_bili_ticket(False)
            except Exception:
                pass
            log.warning(
                f"[WebBrowse] bili_ticket 获取失败，已关闭该功能（浏览不受影响）: {e}"
            )
            return "", ""

    network.get_bili_ticket = _safe_get_bili_ticket
    _TICKET_PATCHED = True


class AutoBiliClient:
    """封装 bilibili_api 的异步调用，对外提供同步方法（内部 asyncio.run）。

    - 登录态只读 llm_active.web_browse 自己的 SESSDATA / bili_jct（不读别的模块的配置）；
    - 从 B站「首页推荐流」随机抓一个视频（每次刷新可换，等价于打开 bilibili.com 首页）；
    - 返回视频元信息 + 可抽帧的流地址。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = AutoWebBrowseConfig()
        # 启用 bili_ticket，应对 B站 412 安全风控（需在发请求前设置）；
        # 必须配套装兜底：该接口失败时 bilibili_api 会抛 KeyError 打死所有请求
        try:
            from bilibili_api import request_settings
            request_settings.set_enable_bili_ticket(True)
        except Exception:
            pass
        _patch_bili_ticket()
        self.sessdata, self.bili_jct, self.mid = self._load_credential()

    @staticmethod
    def _load_credential():
        """读取 B站登录态：只认 llm_active.web_browse 自己的配置，不读别的模块的配置"""
        from func.pipeline.config_reader import ConfigReader
        cfg = ConfigReader().get('llm_active', {})
        wb = cfg.get('web_browse', {}) if isinstance(cfg, dict) else {}
        mid = str(wb.get('mid', '') or '').strip()
        return (str(wb.get('sessdata', '') or '').strip(),
                str(wb.get('bili_jct', '') or '').strip(),
                mid if mid.isdigit() else '')

    def _credential(self):
        """构造 B站凭据（带 dedeuserid，且用修过 cookie 的 Credential 子类）"""
        cls = _get_credential_cls()
        return cls(
            sessdata=self.sessdata,
            bili_jct=self.bili_jct,
            dedeuserid=self.mid or None,
        )

    # ==================== 对外同步入口 ====================
    def fetch_candidate(self) -> Optional[Dict]:
        """随机抓取一个「首页推荐」视频的元信息 + 流地址，失败返回 None"""
        if not self.sessdata:
            self.log.warning("[WebBrowse] 未配置 B站 SESSDATA，首页推荐可能为空/非个性化，仍尝试抓取")
        try:
            return asyncio.run(self._fetch_candidate_async())
        except Exception:
            self.log.exception("[WebBrowse] 抓取视频候选异常")
            return None

    # ==================== 异步实现 ====================
    async def _fetch_home_feed(self, ps: int = 30) -> list:
        """调用 B站首页推荐接口，返回推荐视频列表（刷新可换）"""
        from bilibili_api.utils.network import Api
        api = Api(
            url="https://api.bilibili.com/x/web-interface/wbi/index/top/feed/rcmd",
            method="GET",
            credential=self._credential(),
            wbi=True,
            no_csrf=True,
        )
        try:
            resp = await api.update_params(
                ps=ps,
                fresh_idx=1,
                brush=1,
                homepage_ver=1,
                fetch_row=1,
                fresh_idx_1h=1,
            ).result
        except Exception as e:
            self.log.warning(f"[WebBrowse] 获取首页推荐失败: {e}")
            return []
        # bilibili_api 的 result 已解包 code/data，resp 即 data 部分
        return (resp or {}).get("item") or []

    async def _fetch_candidate_async(self) -> Optional[Dict]:
        from bilibili_api import video

        # 1. 从首页推荐流随机取一个视频
        items = await self._fetch_home_feed()
        if not items:
            self.log.warning("[WebBrowse] 首页推荐为空")
            return None

        item = random.choice(items)
        bvid = str(item.get("bvid") or "").strip()
        if not bvid:
            return None

        # 2. 拿视频信息
        v = video.Video(bvid=bvid, credential=self._credential())
        try:
            info = await v.get_info()
        except Exception as e:
            self.log.warning(f"[WebBrowse] 获取视频信息失败: {e}")
            return None
        if not info:
            return None

        cid = self._first_cid(info)
        title = str(info.get("title") or item.get("title") or "").strip()
        desc = str(info.get("desc") or "").strip()
        duration = int(info.get("duration") or item.get("duration") or 0)
        owner_name = str((info.get("owner") or {}).get("name")
                         or (item.get("owner") or {}).get("name") or "").strip()

        # 3. 视频自身标签
        label = ""
        if cid:
            try:
                tags = await v.get_tags(cid=cid)
                names = [str(t.get("tag_name") or "").strip() for t in (tags or [])]
                label = "、".join([n for n in names if n])
            except Exception:
                self.log.exception("[WebBrowse] 获取视频标签失败")
        if not label:
            label = str(info.get("tname") or "").strip()

        # 4. 流地址（html5 mp4，抽帧用）
        stream_url = await self._get_stream_url(v)

        return {
            "bvid": bvid,
            "url": f"https://www.bilibili.com/video/{bvid}",
            "title": title,
            "introduction": desc,
            "len": self._format_duration(duration),
            "duration_sec": duration,
            "uploader": owner_name,
            "label": label,
            "stream_url": stream_url,
        }

    @staticmethod
    def _first_cid(info: Dict) -> Optional[int]:
        cid = info.get("cid")
        if cid:
            return int(cid)
        pages = info.get("pages") or []
        if pages:
            return int(pages[0].get("cid") or 0) or None
        return None

    @staticmethod
    def _format_duration(seconds: int) -> str:
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h}小时{m}分{s}秒"
        if m > 0:
            return f"{m}分{s}秒"
        return f"{s}秒"

    async def _get_stream_url(self, v) -> Optional[str]:
        """取可抽帧的视频流地址，失败返回 None。

        B站已基本不再下发 html5 的 durl（实测 8/8 视频 durl 为空，只有 dash），
        只读 durl 会让抽帧必然失败。这里回落 DASH：取 avc 编码、最低清晰度的那
        一路——抽帧不需要高画质，带宽最小。
        """
        try:
            data = await v.get_download_url(page_index=0, html5=True)
        except Exception:
            self.log.exception("[WebBrowse] 获取视频流地址失败")
            return None
        data = data or {}

        # ① 旧格式 durl（部分视频/分 P 仍有）
        durl = data.get("durl") or []
        if durl:
            url = str(durl[0].get("url") or "").strip()
            if url:
                return url

        # ② 回落 DASH：avc 优先 + 清晰度最低
        videos = (data.get("dash") or {}).get("video") or []
        if not videos:
            return None
        avc = [x for x in videos if "avc" in str(x.get("codecs") or "").lower()]
        pool = sorted(avc or videos, key=lambda x: int(x.get("id") or 0))
        pick = pool[0]
        url = str(pick.get("baseUrl") or pick.get("base_url") or "").strip()
        if url:
            self.log.info(
                f"[WebBrowse] 使用 DASH 流抽帧 id={pick.get('id')} "
                f"codecs={pick.get('codecs')}"
            )
        return url or None
