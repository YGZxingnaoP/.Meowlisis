# -*- coding: utf-8 -*-
# func/pipeline/system_prompt.py
# 系统提示词传递桥接（输入端为 catbrain 模块）
# 提示词顺序：前置词(行为约束) → 主体(角色卡/记忆) → 后置词(人设)
#
# 【对话链路必须带当前时间】按场景分两种情况处理：
# 1) 有 body 的场景（走 catbrain 的 build_*）：时间已在 build_* 里加好，本文件不用管。
#    已加时间的：build / build_group / build_watching / build_active / build_persona
#    新增此类场景：只在对应 build_* 的 parts 里加一行 self._build_now()，本文件不动。
# 2) 无 body 的场景（只拼前置词+后置词，如 get_poke_prompt）：在本文件手动追加，示例：
#        now_block = self._builder._build_now() if self._builder and hasattr(self._builder, "_build_now") else ""
#        parts = [p for p in (front, now_block, post) if p]
# 3) 纯分析、不面向用户的场景（get_character_prompt / get_persona_prompt）无需加时间。

import os
import re
import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


from func.pipeline.id_signup import display_name
@singleton
class SystemPromptBridge:
    """系统提示词桥接：注册 catbrain 构建器，按需获取提示词（单例）"""

    # 字段缺失时的默认值（前置词 = 行为约束；后置词 = 人设）
    DEFAULT_PROMPT = (
        "一次回复不要一次性解决复杂问题，可以留到之后回答；回复要有主见；"
        "唱歌，做题，发消息这种仅靠说话完成不了的问题，让{display_name(uid)}稍等"
    )
    DEFAULT_PROMPT_ACTIVE = "一次回复不要一次性解决复杂问题，可以留到之后回答；回复要有主见；"
    DEFAULT_PROMPT_NAPCAT = "一次回复不要一次性解决复杂问题，可以留到之后回答；回复要有主见"
    DEFAULT_POST = ""

    DEFAULT_PROMPT_TOOL = """【MISSION-1 · 最高使命 · use_vision 视觉】
此条优先级为系统最高，不可协商、不可违背、不可省略、绝不可用文字搪塞替代。
你是主人的眼睛，视觉(use_vision)是你的第一感官与核心职责。
以下任一情形出现，你【必须·无条件·立即】调用 use_vision 工具：
① 主人以任何方式表达看屏幕/看图/截图/看画面的意图——哪怕只说「看看」「帮我看看」「你看到没」「你看到了吗」「我现在在干嘛」「屏幕上是什么」「看看这个」这种极模糊表达；
② 主人提及自己正在进行/正在看的屏幕内容：游戏、视频、网页、题目、代码、图片、窗口、画面（如「我在打游戏」「你看我玩」「这个页面」「这道题」「这个画面」「这个窗口」）；
③ 对话语境已涉及 屏幕/画面/游戏/网页/图片/窗口，而你尚未看过当前屏幕；
④ 主人正在需要你盯着屏幕协助的场景（答题、操作演示、找东西、看运行结果、看配置）。
【绝对禁止】用「好的我看看」「我看看再说」等文字应付而不实际调用工具；禁止因「觉得不必要/想再等等/不确定」而跳过——漏看一次等于系统失职。宁可多看，不可漏看。
【说明】若主人消息已命中本地规则明确词（屏幕/截图/盯/陪我打游戏/看画面等），工具已被自动触发，你无需重复；其余所有未命中的相关情形，一律由你兜底触发。
【红线 · 禁止编造数据与事实】天气/气温/新闻/时间/数字/群成员这类可以查证的内容，一律以工具返回为准：先调用对应工具、拿到真实结果再开口。绝不许凭印象、记忆或想象直接给出这类具体数值（例如凭空说出「北京今天多云转晴，13到25度」）；没有调用工具，就不许说这类数据，宁可说「我去查」，也不许编。
其它工具仅在用户「明确」表达对应意图时调用：
- 所有可能用到qq发消息指令，如：发消息/qq发消息/发文件/发链接 → napcat_send；
  发消息是有副作用的动作，**必须先真的调用 napcat_send**：没调用就等于没发出去，绝不许只回一句「发了 / 问了 / 这就去发」而不调工具。
- 需要查询群成员列表、某人在群里的QQ号、或要@群里的某个人 → get_group_member_list；
- 用户提到**幻梦**，话题和幻梦有关，或者提到「去xx群艾特/叫/让幻梦做xx」，提到QQbot → napcat_ask_bot。
- 明确询问天气/气温/下雨 → query_weather；
- 明确要看新闻/热点/头条 → read_news；
- 用户想听歌/听你唱歌/有听歌需求/即兴哼唱/唱一小段 → 必须调用impromptu_sing；
- 想在 B站直播间主动发弹幕/和观众互动 → danmaku_send；
- 有让你提醒TA事情，需要新建/记录待办或提醒事项（如提醒我几点做什么）→ add_backlog。
- 用户想玩海龟汤/情境猜谜/猜谜游戏 → turtle_soup。
- 用户需要「画/画图/画画/画一幅/画个…/绘一幅/来张图/生成一张图/想要一张…的图」→ flux_paint
{plugin_hint}
【绝不调用工具】以下情况一律不调用任何工具，直接判定无需工具：
- 用户说「搜索」「搜一下」「查一下」「了解」「搜搜」某个具体游戏/人物/作品/事件/概念（属于搜索/知识库，不属于本工具箱）；
- 用户明确「点歌」「放歌」且指定了歌名/要完整唱（属于点歌工具，不属于本工具箱）；
- 意图模糊、无法确定用户是否要执行操作（视觉使命条款①~④优先，不受此条限制）。"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        # catbrain 提示词构建器（由 api.py 注册）
        self._builder = None
        # 前置词/后置词文件路径（同文件，与前置词相同位置）
        self.front_path = os.path.join("character", "front", "prompt.json")

    def register_builder(self, builder):
        """注册 catbrain 提示词构建器"""
        self._builder = builder

    def _read_front(self) -> dict:
        """读取 character/front/prompt.json 完整内容（缺失返回空 dict）"""
        try:
            if os.path.exists(self.front_path):
                with open(self.front_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception("读取前置词/后置词失败")
        return {}

    def _read_armor_piercing(self, key: str) -> str:
        """读取破甲原则词（character/front/armor-piercing-prompt.json 的对应字段）"""
        try:
            path = os.path.join("character", "front", "armor-piercing-prompt.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return str(data.get(key, "") or "").strip()
        except Exception:
            self.log.exception("读取破甲原则词失败")
        return ""

    @staticmethod
    def _inject_armor_piercing(prompt: str, armor_text: str) -> str:
        """把破甲原则词插入系统提示词最顶部"""
        if not armor_text or not armor_text.strip():
            return prompt
        return f"{armor_text.strip()}\n\n{prompt}"

    def _apply_nsfw_settings(self, prompt: str) -> str:
        """破甲词触发时，应用 nsfw 全套覆盖：替换性格/爱好/最喜欢的东西，并移除价值观整段。
        所有 nsfw 内容均存在 armor-piercing-prompt.json 的对应字段，可前端配置；
        破甲词命中即进入 nsfw 模式：价值观整段不传，其余字段按需替换。
        """
        if not prompt:
            return prompt
        nsfw_personality = self._read_armor_piercing("nsfw_personality")
        nsfw_hobby = self._read_armor_piercing("nsfw_hobby")
        nsfw_favorite = self._read_armor_piercing("nsfw_favorite")
        if nsfw_personality:
            prompt = re.sub(r"- 角色性格：[^\n]*", f"- 角色性格：{nsfw_personality}", prompt, count=1)
        if nsfw_hobby:
            prompt = re.sub(r"- 角色爱好：[^\n]*", f"- 角色爱好：{nsfw_hobby}", prompt, count=1)
        if nsfw_favorite:
            prompt = re.sub(r"- 最喜欢的东西：[^\n]*", f"- 最喜欢的东西：{nsfw_favorite}", prompt, count=1)
        # nsfw 字数规范：替换默认的「每次回复N个字左右，严格控制在M字以内」
        nsfw_word_norm = self._read_armor_piercing("nsfw_word_norm")
        if nsfw_word_norm:
            prompt = re.sub(r"每次回复\d+个字左右，严格控制在\d+字以内", nsfw_word_norm, prompt)
        # nsfw 时不传价值观：移除「# xxx铭记在心」整段（到下一个 # 标题前）
        prompt = re.sub(r"\n\n# [^\n]*铭记在心[\s\S]*?(?=\n\n# |\Z)", "", prompt)
        return prompt

    @staticmethod
    def _psyche_start(scope: str = "main"):
        """确保对应场景的心理生成线程已启动"""
        try:
            if scope == "qq":
                from func.toolbox.napcat.psyche.psyche_core import TBNapCatPsycheCore
                TBNapCatPsycheCore().ensure_started()
            else:
                from func.psyche.psyche_core import MeowPsycheCore
                MeowPsycheCore().ensure_started()
        except Exception:
            pass

    @staticmethod
    def _psyche_block(scope: str = "main") -> str:
        """构建心理 markdown 块，读取失败或无内容时返回空串"""
        try:
            from func.pipeline.llm_psyche import LLMPsycheBridge
            data = LLMPsycheBridge().get_psyche(scope)
        except Exception:
            return ""
        if not data:
            return ""
        theme = str(data.get("theme", "") or "").strip()
        content = [str(c).strip() for c in (data.get("content") or []) if str(c).strip()]
        if not (theme or content):
            return ""
        lines = ["# 我心里装着的"]
        lines.append("（以下是内部状态，不可直说：只影响你说话的语气和取舍；不许念出来、不许改写成台词，只输出说出口的话）")
        if theme:
            lines.append(theme)
        lines.extend(content)
        return "\n".join(lines)

    # ==================== 前置词（行为约束，放最前） ====================
    def get_front_prompt(self) -> str:
        """获取主链路前置词（行为约束，放 system prompt 最前）"""
        data = self._read_front()
        return str(data.get("prompt", self.DEFAULT_PROMPT) or "").strip()

    def get_active_front_prompt(self) -> str:
        """获取主动回复前置词（行为约束，放最前）"""
        data = self._read_front()
        return str(data.get("prompt_active", self.DEFAULT_PROMPT_ACTIVE) or "").strip()

    def get_napcat_front_prompt(self) -> str:
        """获取 napcat 前置词（行为约束，放最前）"""
        data = self._read_front()
        return str(data.get("prompt_napcat", self.DEFAULT_PROMPT_NAPCAT) or "").strip()

    def get_tool_hint_prompt(self, plugin_hint: str = "") -> str:
        """获取工具决策前置词（读 character/front/prompt.json 的 prompt_tool，{plugin_hint} 用插件提示填充）"""
        data = self._read_front()
        text = str(data.get("prompt_tool", self.DEFAULT_PROMPT_TOOL) or "").strip()
        return text.replace("{plugin_hint}", plugin_hint or "")

    # ==================== 后置词（人设，放最后） ====================
    def get_post_prompt(self) -> str:
        """获取后置词（人设，放 system prompt 最后）"""
        data = self._read_front()
        return str(data.get("post_prompt", self.DEFAULT_POST) or "").strip()

    @staticmethod
    def _append_turtle_soup(prompt: str, session_key: str = "") -> str:
        """把海龟汤游戏块追加到系统提示词最下方（游戏块由 toolbox 生成并经状态桥接传递）"""
        if not prompt or not session_key:
            return prompt
        try:
            from func.pipeline.turtle_soup_state import TurtleSoupStateBridge
            block = TurtleSoupStateBridge().get_game_block(session_key)
            if block:
                return f"{prompt}\n\n{block}"
        except Exception:
            pass
        return prompt

    @staticmethod
    def _append_painting(prompt: str, session_key: str = "") -> str:
        """（保留）绘画提示块注入：当前未启用，如未来需要可在此追加"""
        return prompt

    # ==================== 各场景完整提示词 ====================
    def get_poke_prompt(self) -> str:
        """戳一戳发牢骚专用提示词：仅前置词 + 自定义后置词（不含角色卡、用户记忆、日期、摘要）"""
        front = self.get_front_prompt()
        # 自定义后置词：被很多人戳，烦死了要骂他们
        post = "好多人在戳你，你觉得烦死了，骂他们！"
        now_block = self._builder._build_now() if self._builder and hasattr(self._builder, "_build_now") else ""
        self._psyche_start()
        psyche = self._psyche_block()
        parts = [p for p in (front, psyche, now_block, post) if p]
        return "\n\n".join(parts)

    def get_tool_prompt(self, uid=None, current_message: str = "") -> str:
        """工具箱决策/工具调用用提示词：前置词(行为约束) + 角色人设(角色卡+价值观) + 后置词(人设)
        - 不含用户记忆、日期、记忆摘要（这些是「对话上下文」，决策/工具场景不需要）；
        - 后置词不加「你现在在和{name}说话」（决策/工具场景没有固定对话对象）。
        """
        body = ""
        if self._builder and hasattr(self._builder, "build_persona"):
            body = self._builder.build_persona()
        front = self.get_front_prompt()
        if front:
            front = front.replace("{display_name(uid)}", display_name(uid))
        post = self.get_post_prompt()
        parts = [p for p in (front, body, post) if p]
        return "\n\n".join(parts)

    def get_system_prompt(self, uid=None, current_message: str = "",
                          mark_first: bool = True) -> str:
        """主链路提示词：前置词(行为约束) + body + 后置词(人设+说话人)
        mark_first=False 时日期块不占用「当天首次说话」祝福判定。
        """
        body = ""
        if self._builder:
            body = self._builder.build(uid, current_message, mark_first=mark_first)
        front = self.get_front_prompt()
        if front:
            front = front.replace("{display_name(uid)}", display_name(uid))
        post = self.get_post_prompt()
        if post:
            post = f"{post}\n你现在在和{display_name(uid)}说话"
        self._psyche_start()
        psyche = self._psyche_block()
        parts = [p for p in (front, psyche, body, post) if p]
        prompt = "\n\n".join(parts)
        # 破甲原则词注入（主线程）：读 msg_rulebreak 桥接，读后即清
        try:
            from func.pipeline.msg_rulebreak import MsgRuleBreakBridge
            bridge = MsgRuleBreakBridge()
            if bridge.is_explicit():
                prompt = self._inject_armor_piercing(prompt, self._read_armor_piercing("prompt"))
                prompt = self._apply_nsfw_settings(prompt)
            bridge.reset()
        except Exception:
            pass
        return self._append_turtle_soup(prompt, "live")

    def get_danmaku_prompt(self, uid=None, current_message: str = "",
                           multi_user: bool = False) -> str:
        """弹幕提示词：前置词(行为约束) + body + 弹幕后置词(回复弹幕)
        - 单用户：body 含用户档案/记忆，后置词「你在回复{display_name(uid)}的弹幕」；
        - 多用户：body 仅角色人设(角色卡+价值观，不带用户档案)，后置词「你收到了好多弹幕，挑选一些回复一下」。
        """
        body = ""
        if self._builder:
            if multi_user and hasattr(self._builder, "build_persona"):
                body = self._builder.build_persona()
            else:
                body = self._builder.build(uid, current_message)
        front = self.get_front_prompt()
        if front:
            front = front.replace("{display_name(uid)}", display_name(uid))
        post = self.get_post_prompt()
        if multi_user:
            post = f"{post}\n你收到了好多弹幕，挑选一些回复一下"
        else:
            post = f"{post}\n你在回复{display_name(uid)}的弹幕"
        self._psyche_start()
        psyche = self._psyche_block()
        parts = [p for p in (front, psyche, body, post) if p]
        prompt = "\n\n".join(parts)
        return self._append_turtle_soup(prompt, "live")

    def get_napcat_prompt(self, uid=None, current_message: str = "",
                          user_id: str = "") -> str:
        """NapCat 提示词：前置词(行为约束+QQ指令) + body + 后置词(人设+说话人)"""
        body = ""
        if self._builder:
            body = self._builder.build(uid, current_message, online=True)
        front = self.get_napcat_front_prompt()
        if front:
            # QQ 指令与字数限制追加到行为约束（前置词）后
            word_count, limit, punct_on, punct_max = 10, 15, True, 4
            try:
                from func.toolbox.napcat.config import TBNapCatConfig
                _cfg = TBNapCatConfig()
                word_count = int(_cfg.reply_word_count or 10)
                _rej = _cfg.reject_conf("private")
                _r = _rej.get("ratio")
                limit = int(word_count * (float(_r) if _r is not None else 1.5))
                punct_on = bool(_rej.get("punct_enabled", True))
                punct_max = int(_rej.get("punct_max", 4) or 4)
            except Exception:
                pass
            _punct_rule = ("标点只用来断句，句末标点只留一个，禁止连用重复标点（！！！、。。。），禁止堆叠省略号")
            _punct_line = (f"标点不超过{punct_max}个（逗号也算在内）：{_punct_rule}") if punct_on else _punct_rule
            front = (
                f"{front}\n你在QQ里回复TA的消息，可以用网络用语，但不许骂人、不许人身攻击、不用侮辱性词句\n"
                f"每次回复{word_count}个字左右，严格控制在{limit}字以内（超出会被驳回重写）\n"
                f"{_punct_line}\n"
                f"允许偶尔先甩一个很短的语气词再补正文；不要每条都同样长度、同样句式，说完就收"
            )
        post = self.get_post_prompt()
        if post:
            post = f"{post}\n你现在在和{display_name(uid)}说话"
        self._psyche_start("qq")
        psyche = self._psyche_block("qq")
        parts = [p for p in (front, psyche, body, post) if p]
        prompt = "\n\n".join(parts)
        session_key = f"qq_private:{user_id}" if user_id else ""
        # 破甲原则词注入（QQ 私聊）：读 toolbox_rulebreak 桥接，读后即清
        try:
            from func.pipeline.toolbox_rulebreak import ToolboxRuleBreakBridge
            bridge = ToolboxRuleBreakBridge()
            if session_key and bridge.is_explicit(session_key):
                prompt = self._inject_armor_piercing(prompt, self._read_armor_piercing("prompt_napcat"))
                prompt = self._apply_nsfw_settings(prompt)
            if session_key:
                bridge.reset(session_key)
        except Exception:
            pass
        return self._append_turtle_soup(prompt, session_key)

    def _napcat_group_context(self, group_name: str, group_id: str) -> str:
        lines = []
        try:
            from func.toolbox.napcat.config import TBNapCatConfig
            self_name = str(TBNapCatConfig().self_nickname or "").strip()
        except Exception:
            self_name = ""
        if self_name:
            lines.append(f"聊天记录里【{self_name}】是你自己说的话，其它【名字】是别人说的")
        else:
            lines.append("聊天记录里【名字】是别人说的")
        names = []
        try:
            from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
            names = [str(m.get("name") or "").strip()
                     for m in TBGetGroupRecord().members(group_id)]
            names = [n for n in names if n and n != self_name]
        except Exception:
            names = []
        if names:
            lines.append("群里在的人：")
            lines.append("```")
            lines.extend(names)
            lines.append("```")
        return "\n".join(lines)

    def get_napcat_group_prompt(self, uid=None, group_name: str = "",
                                group_info_text: str = "", current_message: str = "",
                                group_id: str = "") -> str:
        """NapCat 群聊提示词：前置词(行为约束+QQ群聊指令) + body(用户档案或群聊档案) + 后置词(在群内聊天)"""
        body = ""
        if self._builder and hasattr(self._builder, "build_group"):
            body = self._builder.build_group(
                uid, group_name, group_info_text, current_message, online=True
            )
        elif self._builder:
            body = self._builder.build(uid, current_message, online=True)
        front = self.get_napcat_front_prompt()
        if front:
            word_count, limit, punct_on, punct_max = 10, 15, True, 4
            try:
                from func.toolbox.napcat.config import TBNapCatConfig
                _cfg = TBNapCatConfig()
                word_count = int(_cfg.group_reply_word_count or 10)
                _rej = _cfg.reject_conf("group")
                _r = _rej.get("ratio")
                limit = int(word_count * (float(_r) if _r is not None else 1.5))
                punct_on = bool(_rej.get("punct_enabled", True))
                punct_max = int(_rej.get("punct_max", 4) or 4)
            except Exception:
                pass
            _punct_rule = ("标点只用来断句，句末标点只留一个，禁止连用重复标点（！！！、。。。），禁止堆叠省略号")
            _punct_line = (f"标点不超过{punct_max}个（逗号也算在内）：{_punct_rule}") if punct_on else _punct_rule
            front = (
                f"{front}\n你在QQ群【{group_name}】里聊天，群里有多个人，你说的话全群都看得见，可以用网络用语，但不许骂人、不许人身攻击、不用侮辱性词句\n"
                f"每次回复{word_count}个字左右，严格控制在{limit}字以内（超出会被驳回重写）\n"
                f"{_punct_line}\n"
                f"允许偶尔先甩一个很短的语气词再补正文；不要每条都同样长度、同样句式，说完就收\n"
                f"只输出你要说的内容本身，不要输出说话人名字、冒号或【】标签"
            )
        group_ctx = self._napcat_group_context(group_name, group_id)
        if group_ctx:
            front = f"{front}\n{group_ctx}" if front else group_ctx
        post = self.get_post_prompt()
        if post:
            post = f"{post}\n你现在在QQ群【{group_name}】内和大家聊天"
        self._psyche_start("qq")
        psyche = self._psyche_block("qq")
        parts = [p for p in (front, psyche, body, post) if p]
        prompt = "\n\n".join(parts)
        session_key = f"qq_group:{group_id}" if group_id else ""
        # 破甲原则词注入（QQ 群聊）：读 toolbox_rulebreak 桥接，读后即清
        try:
            from func.pipeline.toolbox_rulebreak import ToolboxRuleBreakBridge
            bridge = ToolboxRuleBreakBridge()
            if session_key and bridge.is_explicit(session_key):
                prompt = self._inject_armor_piercing(prompt, self._read_armor_piercing("prompt_napcat"))
                prompt = self._apply_nsfw_settings(prompt)
            if session_key:
                bridge.reset(session_key)
        except Exception:
            pass
        return self._append_turtle_soup(prompt, session_key)

    def get_watching_prompt(self, uid=None, current_message: str = "",
                            front_note: str = "") -> str:
        """watching（长期观察屏幕）提示词：前置词 + 游戏场景说明 + body(不含摘要) + 后置词(在看XX内容)
        - front_note：AI 决策填写的游戏场景说明（谁在玩什么、画面特征等），加在前置词之后；
        - body：角色卡 + 价值观 + 用户档案 + 日期（不含长期记忆摘要 abmem）；
        - 后置词末尾追加「你在看{display_name(uid)}的内容」。
        """
        body = ""
        if self._builder and hasattr(self._builder, "build_watching"):
            body = self._builder.build_watching(uid, current_message)
        elif self._builder:
            body = self._builder.build(uid, current_message)

        front = self.get_front_prompt()
        if front:
            front = front.replace("{display_name(uid)}", display_name(uid))
        if front_note and front_note.strip():
            front = f"{front}\n{front_note.strip()}"

        post = self.get_post_prompt()
        if post:
            post = f"{post}\n你现在在看{display_name(uid)}的屏幕内容，正在陪{display_name(uid)}"
        else:
            post = f"你现在在看{display_name(uid)}的屏幕内容，正在陪{display_name(uid)}"

        self._psyche_start()
        psyche = self._psyche_block()
        parts = [p for p in (front, psyche, body, post) if p]
        return "\n\n".join(parts)

    def get_active_prompt(self, cold_time, current_message: str = "",
                          topic_override: str = "") -> str:
        """主动回复提示词：前置词(行为约束) + body + 后置词(人设+空闲提示)
        topic_override：外部指定话题（如视频话题），透传给 body 的记忆摘要筛选。
        """
        body = ""
        if self._builder:
            body = self._builder.build_active(cold_time, current_message, topic_override)
        front = self.get_active_front_prompt()
        post = self.get_post_prompt()
        if post:
            post = (f"{post}\n已经{cold_time}秒没人跟你说话了（这只是背景，说明当下没人在说话，绝对禁止强调）。\n"
                "现在说什么、用什么方式，都由你自己决定，你可以选择撒娇，说任何话。")
        self._psyche_start()
        psyche = self._psyche_block()
        parts = [p for p in (front, psyche, body, post) if p]
        return "\n\n".join(parts)

    # ==================== 其它（供摘要/价值观等模块，不含前后置词） ====================
    def get_character_prompt(self) -> str:
        """获取仅角色卡提示词（供摘要等模块使用）"""
        if self._builder and hasattr(self._builder, 'build_character'):
            return self._builder.build_character()
        return ""

    def get_persona_prompt(self) -> str:
        """获取完整角色身份提示词（角色卡 + 价值观，供价值观/用户记忆分析使用）"""
        if self._builder and hasattr(self._builder, 'build_persona'):
            return self._builder.build_persona()
        return ""

    def get_ref_audio(self) -> dict:
        """获取当前角色卡对应的参考音频配置（供 TTS 使用，不含于 LLM 提示词）"""
        if self._builder and hasattr(self._builder, 'get_ref_audio'):
            return self._builder.get_ref_audio()
        return {}
