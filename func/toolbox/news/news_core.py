# -*- coding: utf-8 -*-
# func/toolbox/news/news_core.py
# News 新闻查询模块：父级 toolcalls 触发型工具入口
# 流程：爬取 readhub 热榜标题 → 进详情页取正文(主标题+相关报道) → LLM 概括 → TTS 播放(source=toolbox_news)
# 零新增依赖：仅用标准库 re + requests 解析 SSR 内嵌 JSON 数据。

import re
import json
import uuid
from typing import Dict, List, Optional

import requests

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.news.config import TBNewsConfig
from func.toolbox.get_prompt import TBoxGetPrompt
from func.pipeline.toolbox_tts import ToolboxTtsBridge

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

HOT_URL = "https://www.readhub.cn/hot"
TOPIC_URL = "https://www.readhub.cn/topic/{tid}"


@singleton
class TBNewsCore:
    """新闻查询模块入口：父级只暴露 read_news 一个工具。

    - 爬取 readhub 热榜前 N 条标题（N 可配置，默认 3）；
    - 逐条进详情页提取正文（主标题 topicTitle + 相关报道标题列表，不跳第三方站点）；
    - 组装完整角色提示词，由 toolbox LLM 概括新闻并告知用户；
    - 文案经 TTS 合成播放，source 标注 toolbox_news。
    """

    TOOL_NAME = "read_news"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNewsConfig()
        self._username = ""

    def set_username(self, username: str):
        """注入当前用户（供提示词使用）"""
        self._username = username or ""

    def build_tools(self) -> List[Dict]:
        """父级暴露的新闻查询工具 schema"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "查询并播报最新新闻/今日热点（Readhub 热榜）。\n"
                    "【仅在以下情况调用】用户明确要求看新闻、今日热点、新闻资讯、头条、最近新闻、有什么新闻。\n"
                    "【严格禁止调用】以下情况绝不调用本工具：\n"
                    "- 用户说「搜索」「查一下」「了解」「搜搜」某个具体游戏/人物/作品/事件/概念（这是搜索/知识库的职责）；\n"
                    "- 询问天气、气温、下雨、带伞（用 query_weather）；\n"
                    "- 发消息、看屏幕、看图片等其它操作；\n"
                    "- 普通闲聊、讨论、询问观点。\n"
                    "只有用户明确表达「看新闻/热点」时才调用，模糊不清时宁可不要调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "要获取的新闻条数，默认3，最多10。",
                        },
                    },
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        if not self.config.enabled:
            return "新闻查询模块未启用"

        arguments = arguments or {}
        try:
            count = int(arguments.get("count") or self.config.top_n)
        except (TypeError, ValueError):
            count = self.config.top_n
        count = max(1, min(count, 10))

        items = self._fetch_hot(count)
        if not items:
            return "获取新闻热榜失败"

        # 逐条进详情页取正文
        news_list = []
        for it in items:
            detail = self._fetch_topic(it.get("id", ""))
            news_list.append({
                "title": it.get("title", ""),
                "detail": detail,
            })

        reply = self._build_reply(news_list)
        if not reply:
            return "新闻数据已获取，但概括文案生成失败"

        self._speak(reply, source="toolbox_news")
        return reply

    # ==================== QQ 场景入口（napcat 专用） ====================
    def dispatch_qq(self, name: str, arguments: Dict, qq_context: Dict) -> Optional[str]:
        """QQ 场景：结果用 toolbox LLM 加工后交给 napcat 模块发 QQ（不走 pipeline TTS）。

        count 缺省时用配置 top_n（默认3），不做 QQ excuse 追问。
        返回最终文案；失败返回 None。
        """
        if name != self.TOOL_NAME:
            return None
        if not self.config.enabled:
            return None

        arguments = arguments or {}
        try:
            count = int(arguments.get("count") or self.config.top_n)
        except (TypeError, ValueError):
            count = self.config.top_n
        count = max(1, min(count, 10))

        items = self._fetch_hot(count)
        if not items:
            self._send_qq_reply(qq_context, "抱歉，新闻获取失败了呢")
            return None

        news_list = []
        for it in items:
            detail = self._fetch_topic(it.get("id", ""))
            news_list.append({
                "title": it.get("title", ""),
                "detail": detail,
            })

        reply = self._build_reply(news_list)
        if not reply:
            self._send_qq_reply(qq_context, "抱歉，我概括新闻失败了呢")
            return None

        self._send_qq_reply(qq_context, reply)
        return reply

    @staticmethod
    def _send_qq_reply(qq_context: Dict, text: str):
        """结果交给 napcat 模块发 QQ（私聊或群聊）"""
        if not text:
            return
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        core = TBNapCatCore()
        if str(qq_context.get("message_type", "")) == "group":
            core.send_group_text(str(qq_context.get("target_id", "")), text)
        else:
            core.send_private_text(
                str(qq_context.get("target_id", "") or qq_context.get("user_id", "")), text
            )

    # ==================== 热榜爬取 ====================
    def _fetch_hot(self, n: int) -> List[Dict]:
        """爬取 readhub 热榜前 N 条（title + id + publishDate）"""
        try:
            r = requests.get(HOT_URL, headers=HEADERS, timeout=15)
            r.encoding = "utf-8"
            text = r.text
        except Exception:
            self.log.exception("[News] 请求热榜失败")
            return []

        items: List[Dict] = []
        # 热榜 items 形如 {\"title\":\"...\",\"id\":\"...\",\"publishDate\":\"...\"}
        # 兼容带/不带反斜杠转义两种形态；weekly 用 uniqueId，不会命中此模式。
        pattern = re.compile(
            r'\\?"title\\?":\\?"(.*?)\\?",\\?"id\\?":\\?"(.*?)\\?",\\?"publishDate\\?":\\?"(.*?)\\?"'
        )
        seen_titles = set()
        for m in pattern.finditer(text):
            title = self._unescape(m.group(1))
            tid = self._unescape(m.group(2))
            pub = self._unescape(m.group(3))
            if not title or not tid:
                continue
            # 去重（热榜可能同一标题不同 id 重复出现）
            if title in seen_titles:
                continue
            seen_titles.add(title)
            items.append({"title": title, "id": tid, "publish_date": pub})
            if len(items) >= n:
                break
        return items

    # ==================== 详情页正文 ====================
    def _fetch_topic(self, tid: str) -> str:
        """进详情页提取正文：主标题 + 摘要(如有) + 相关报道标题列表（不跳第三方站点）"""
        if not tid:
            return ""
        try:
            r = requests.get(TOPIC_URL.format(tid=tid), headers=HEADERS, timeout=15)
            r.encoding = "utf-8"
            text = r.text
        except Exception:
            self.log.exception(f"[News] 请求详情页失败: {tid}")
            return ""

        # 主标题
        main_title = ""
        m = re.search(r'topicTitle\\?":\\?"(.*?)\\?"', text)
        if m:
            main_title = self._unescape(m.group(1))

        # 相关报道标题：提取所有干净 title 字段值（过滤 JSON 残留与区块标题）
        related: List[str] = []
        for tm in re.finditer(r'\\?"title\\?":\\?"(.*?)\\?"', text):
            t = self._unescape(tm.group(1))
            if not self._is_clean_title(t):
                continue
            if t and t != main_title and t not in related:
                related.append(t)
            if len(related) >= 8:
                break

        parts: List[str] = []
        if main_title:
            parts.append(main_title)
        if related:
            parts.append("相关报道：" + "；".join(related[:6]))
        return "\n".join(parts).strip()

    @staticmethod
    def _is_clean_title(t: str) -> bool:
        """判断提取的 title 是否为干净文本（过滤 JSON 残留与区块标题）"""
        if not t:
            return False
        if len(t) > 120:
            return False
        # 区块标题 / 明显非新闻标题
        if t.strip() in ("相关事件", "话题追踪"):
            return False
        for ch in ('"', '{', '}', '[', ']', '\\', ':', '}'):
            if ch in t:
                return False
        return True

    @staticmethod
    def _unescape(s: str) -> str:
        """反转义 JSON 字符串（处理 \\\" 等常见转义）"""
        if not s:
            return ""
        try:
            return json.loads(f'"{s}"')
        except Exception:
            return s.replace('\\"', '"').replace('\\n', '\n').replace('\\u0026', '&')

    # ==================== LLM 概括 ====================
    def _build_reply(self, news_list: List[Dict]) -> str:
        system = TBoxGetPrompt().get_system_prompt(self._username, "帮我看看今天有什么新闻")
        lines = []
        for i, item in enumerate(news_list, 1):
            title = item.get("title", "")
            detail = item.get("detail", "")
            if detail:
                lines.append(f"{i}. {title}\n   {detail}")
            else:
                lines.append(f"{i}. {title}")
        news_text = "\n\n".join(lines)

        user = (
            f"以下是来自 Readhub 的最新科技新闻（共 {len(news_list)} 条）：\n\n{news_text}\n\n"
            f"请以你的角色身份，概括这些新闻的要点并自然地告诉用户，"
            f"可以适当加入你自己的看法、情绪或吐槽。直接输出概括内容即可。"
        )
        llm = self._llm()
        if not llm or not llm.client:
            self.log.error("[News] toolbox LLM 不可用")
            return ""
        resp = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        content = ""
        try:
            if resp and resp.choices:
                content = (resp.choices[0].message.content or "").strip()
        except Exception:
            self.log.exception("[News] 解析 LLM 回复失败")
        return self._clean(content)

    def _llm(self):
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)

    @staticmethod
    def _clean(text: str) -> str:
        """正则优化：去 think 标签、方括号/圆括号内容"""
        if not text:
            return ""
        text = str(text)
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"【[^】]*】", "", text)
        text = re.sub(r"（[^）]*）", "", text)
        text = re.sub(r"\([^)]*\)", "", text)
        return re.sub(r"[ \t]+", " ", text).strip()

    # ==================== TTS ====================
    @staticmethod
    def _speak(text: str, source: str):
        ToolboxTtsBridge().send_stream(text, source=source)
