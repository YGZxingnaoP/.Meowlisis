# -*- coding: utf-8 -*-
# func/toolbox/weather/weather_core.py
# Weather 天气查询模块：父级 toolcalls 触发型工具入口
# 流程：城市代码查询 → calendar_new 获取预报 → （可选）excuse 追问城市 → LLM 拟播报 → TTS 播放(source=toolbox_weather)

import re
import json
import uuid
import datetime
from typing import Dict, List, Optional

import requests

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.weather.config import TBWeatherConfig
from func.toolbox.get_prompt import TBoxGetPrompt
from func.pipeline.toolbox_tts import ToolboxTtsBridge

# 中国天气网接口需带 Referer，否则返回数据合作提示页
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "http://www.weather.com.cn/",
}


@singleton
class TBWeatherCore:
    """天气查询模块入口：父级只暴露 query_weather 一个工具。

    - 城市缺失时通过 TBExcuse 以角色口吻追问（阻塞等待补充）；
    - 日期类型缺失时默认今天（追问粒度由 AI 自己把握，不做死约束）；
    - 拿到数据后组装完整角色提示词，由 toolbox LLM 以角色身份拟播报文案；
    - 文案经 TTS 合成播放，source 标注 toolbox_weather。
    """

    TOOL_NAME = "query_weather"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBWeatherConfig()
        self._username = ""

    def set_username(self, username: str):
        """注入当前用户（供 excuse 追问 / 提示词使用）"""
        self._username = username or ""

    def build_tools(self) -> List[Dict]:
        """父级暴露的天气查询工具 schema"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "查询并播报指定城市的天气（数据来自中国天气网）。\n"
                    "【仅在以下情况调用】用户明确询问天气、气温、会不会下雨、要不要带伞、冷不冷热不热。\n"
                    "【严格禁止调用】以下情况绝不调用本工具：\n"
                    "- 用户说「搜索」「查一下」「了解」「搜搜」某个具体游戏/人物/作品/事件/概念（这是搜索/知识库的职责）；\n"
                    "- 询问新闻、热点、最近发生了什么（用 read_news）；\n"
                    "- 发消息、看屏幕、看图片等其它操作；\n"
                    "- 普通闲聊、讨论、询问观点。\n"
                    "只有用户明确在问天气时才调用，模糊不清时宁可不要调用。\n"
                    "city 填城市名（如北京、长沙）；date_type 填 today(今天)/tomorrow(明天)/all(未来7天)，缺省 today。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "要查询天气的城市名，如北京、长沙。未知时留空。",
                        },
                        "date_type": {
                            "type": "string",
                            "enum": ["today", "tomorrow", "all"],
                            "description": "日期范围：today 今天 / tomorrow 明天 / all 未来7天，缺省默认 today。",
                        },
                    },
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        if not self.config.enabled:
            return "天气查询模块未启用"

        arguments = arguments or {}
        city = (arguments.get("city") or "").strip()
        date_type = self._norm_date_type(arguments.get("date_type"))

        # 城市缺失 → excuse 追问（阻塞等待用户补充）
        if not city:
            city = self._ask_city()
            if not city:
                return "用户未提供城市，已取消天气查询"

        # 获取天气数据
        days = self._fetch_forecast(city)
        if not days:
            return f"获取 {city} 天气数据失败"

        # 截取目标日期范围
        picked = self._pick(days, date_type)
        if not picked:
            return f"未获取到 {city} 的天气数据"

        label = {"today": "今天", "tomorrow": "明天", "all": "未来7天"}.get(date_type, "今天")

        # LLM 拟播报文案
        reply = self._build_reply(city, label, picked)
        if not reply:
            return f"{city} 天气数据已获取，但播报文案生成失败"

        self._speak(reply, source="toolbox_weather")
        return reply

    # ==================== QQ 场景入口（napcat 专用） ====================
    def dispatch_qq(self, name: str, arguments: Dict, qq_context: Dict) -> Optional[str]:
        """QQ 场景：excuse 走 napcat_plugin（发 QQ 询问 + 绑定用户等待），
        结果用 toolbox LLM 加工后交给 napcat 模块发 QQ（不走 pipeline TTS）。

        返回最终文案；用户另起话题/放弃/失败返回 None。
        """
        if name != self.TOOL_NAME:
            return None
        if not self.config.enabled:
            return None

        arguments = arguments or {}
        city = (arguments.get("city") or "").strip()
        date_type = self._norm_date_type(arguments.get("date_type"))

        # 城市缺失 → QQ excuse 追问（绑定用户）
        if not city:
            from func.toolbox.weather.napcat_plugin import TBWeatherNapcatPlugin
            city = TBWeatherNapcatPlugin().ask_city(qq_context, self._username)
            # 用户另起话题 → 透传重新投递标记给上层
            if isinstance(city, tuple) and city and city[0] == "redeliver":
                return city
            if not city:
                return None

        days = self._fetch_forecast(city)
        if not days:
            self._send_qq_reply(qq_context, f"抱歉，我没有查到{city}的天气数据呢")
            return None

        picked = self._pick(days, date_type)
        if not picked:
            self._send_qq_reply(qq_context, f"抱歉，我没有查到{city}的天气数据呢")
            return None

        label = {"today": "今天", "tomorrow": "明天", "all": "未来7天"}.get(date_type, "今天")
        reply = self._build_reply(city, label, picked)
        if not reply:
            self._send_qq_reply(qq_context, f"抱歉，我组织{city}的天气播报失败了呢")
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

    # ==================== 日期类型归一化 ====================
    @staticmethod
    def _norm_date_type(value) -> str:
        s = str(value or "").strip().lower()
        if s in ("今天", "today", "今日"):
            return "today"
        if s in ("明天", "tomorrow", "明日"):
            return "tomorrow"
        if s in ("所有", "all", "7天", "七天", "一周", "未来7天", "最近7天", "7日", "本周"):
            return "all"
        return "today"

    # ==================== 城市代码查询 ====================
    @staticmethod
    def _get_city_code(city: str) -> Optional[str]:
        """根据城市名查询城市代码，如 长沙 -> 101250101"""
        try:
            url = "http://toy1.weather.com.cn/search"
            r = requests.get(url, params={"cityname": city}, headers=HEADERS, timeout=10)
            r.encoding = "utf-8"
            m = re.search(r"\[.*\]", r.text, re.S)
            arr = json.loads(m.group(0))
            if not arr:
                return None
            for item in arr:
                ref = item["ref"].split("~")
                code, name_cn = ref[0], ref[2]
                if name_cn == city:
                    return code
            return arr[0]["ref"].split("~")[0]
        except Exception:
            return None

    # ==================== 天气数据获取 ====================
    def _fetch_forecast(self, city: str) -> List[Dict]:
        """获取未来 15 天预报（合并当月 + 下月，按日期升序去重）"""
        code = self._get_city_code(city)
        if not code:
            self.log.warning(f"[Weather] 未找到城市代码: {city}")
            return []

        now = datetime.datetime.now()
        months = [(now.year, now.month)]
        ny, nm = self._next_month(now.year, now.month)
        months.append((ny, nm))

        days: List[Dict] = []
        seen = set()
        for y, m in months:
            url = f"http://d1.weather.com.cn/calendar_new/{y}/{code}_{y}{m:02d}.html"
            try:
                r = requests.get(url, headers=HEADERS, timeout=10)
                r.encoding = "utf-8"
                mre = re.search(r"=\s*(\[.*\])", r.text, re.S)
                if not mre:
                    continue
                arr = json.loads(mre.group(1))
                for d in arr:
                    if d.get("cla") != "d15":
                        continue
                    date = d.get("date") or ""
                    if not date or date in seen:
                        continue
                    seen.add(date)
                    days.append(d)
            except Exception:
                self.log.exception(f"[Weather] 获取 {y}-{m:02d} 预报失败")
        days.sort(key=lambda x: x.get("date", ""))
        return days

    @staticmethod
    def _next_month(y: int, m: int):
        if m == 12:
            return y + 1, 1
        return y, m + 1

    def _pick(self, days: List[Dict], date_type: str) -> List[Dict]:
        """按日期类型截取：today 今日 / tomorrow 明日 / all 未来7天"""
        today = datetime.date.today().strftime("%Y%m%d")
        if date_type == "today":
            for d in days:
                if d.get("date") == today:
                    return [d]
            return days[:1]
        if date_type == "tomorrow":
            # 找今天之后的第一个
            for i, d in enumerate(days):
                if d.get("date", "") > today:
                    return [d]
            return days[1:2]
        # all：未来 7 天（从今天起）
        result = []
        for d in days:
            if d.get("date", "") >= today:
                result.append(d)
            if len(result) >= 7:
                break
        return result

    @staticmethod
    def _format_day(d: Dict) -> str:
        date = d.get("date", "")
        wk = d.get("wk") or ""
        w1 = d.get("w1") or ""
        tmin = d.get("min") or d.get("hmin") or ""
        tmax = d.get("max") or d.get("hmax") or ""
        wind = d.get("wd1") or ""
        seg = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        if wk:
            seg += f"(周{wk})"
        parts = [seg, w1]
        if tmin and tmax:
            parts.append(f"气温{tmin}~{tmax}°C")
        if wind:
            parts.append(wind)
        return "，".join(p for p in parts if p)

    # ==================== LLM 拟播报 ====================
    def _build_reply(self, city: str, label: str, days: List[Dict]) -> str:
        system = TBoxGetPrompt().get_system_prompt(self._username, f"帮我播报{city}{label}天气")
        data_text = "\n".join(self._format_day(d) for d in days)
        user = (
            f"以下是来自中国天气网的【{city} {label}】天气数据：\n\n{data_text}\n\n"
            f"请以你的角色身份，自然、口语化地向用户播报{city}{label}的天气情况，"
            f"可以适当加入关心、穿衣/带伞等贴心提醒。直接输出播报内容即可。"
        )
        llm = self._llm()
        if not llm or not llm.client:
            self.log.error("[Weather] toolbox LLM 不可用")
            return ""
        resp = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        content = ""
        try:
            if resp and resp.choices:
                content = (resp.choices[0].message.content or "").strip()
        except Exception:
            self.log.exception("[Weather] 解析 LLM 回复失败")
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

    # ==================== excuse 追问城市 ====================
    def _ask_city(self) -> str:
        try:
            from func.toolbox.excuse import TBExcuse
            reply = TBExcuse().ask("你想查询哪个城市的天气？", username=self._username)
        except Exception:
            self.log.exception("[Weather] excuse 追问城市失败")
            return ""
        if not reply:
            return ""
        city = re.sub(r"(帮我|请)?(查|查询|看看)?(一下|下)?(的)?(天气|天气预报|天气情况)?", "", reply).strip()
        return city or reply.strip()
