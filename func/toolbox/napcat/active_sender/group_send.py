# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/group_send.py
# 群发：AI 从群列表选目标群、拟定消息，必要时发送链接/文件

import json
from typing import List, Dict, Optional

from func.log.default_log import DefaultLog
from func.toolbox.napcat.active_sender.sender import TBSender
from func.toolbox.napcat.active_sender.get_grouplist import TBGetGroupList


class TBGroupSend:
    """群聊主动发送编排：群列表 → LLM 选目标群并拟稿 → 发送

    excuse 触发策略：
    - AI 信息充足时直接果断发送，不做每次发送前确认；
    - 仅当 AI 判定「信息极度不全面」（need_clarify=true）时，才角色口吻询问用户。
    """

    TOOL_NAME = "send_to_groups"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.sender = TBSender()
        self.get_grouplist = TBGetGroupList()
        self._username = ""

    def set_username(self, username: str):
        """注入当前用户（供 excuse 询问时使用，由 analysis.dispatch 调用）"""
        self._username = username or ""

    def build_tools(self) -> List[Dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": "根据需求，从 QQ 群列表中选定一个或多个群并拟定消息发送（可带链接/文件）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string", "description": "发送需求，例如：在某个群发一条活动通知"},
                    },
                    "required": ["request"],
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        if name == self.TOOL_NAME:
            return self.execute(arguments.get("request", ""), self._username)
        return f"错误：未知工具 {name}"

    def execute(self, request: str = "", username: str = "",
                content_type: str = "", text: str = "", url: str = "",
                file_path: str = "", at_name: str = "") -> str:
        # 内容信息直传：text/url/file_path 由上层给定；request 仅作目标线索
        direct = self._direct_content(content_type, text, url, file_path)
        at_name = str(at_name or "").strip()
        if not request and not direct.get("type") and not at_name:
            return "发送失败：缺少需求描述或发送内容"
        # 主动发送开关 + 冷却检查
        err = self.sender.check_active_send()
        if err:
            return err
        groups = self.get_grouplist.get()
        if not groups:
            return "未获取到群列表，无法发送"

        plan = self._plan(request, groups, username, content_type=content_type,
                          text=text, url=url, file_path=file_path, at_name=at_name)

        # 不确定（信息不全面 / 未选定目标）→ 角色口吻询问补充需求后重试一次
        if self._uncertain(plan):
            from func.toolbox.excuse import TBExcuse
            question = (plan or {}).get("clarify_question") or \
                "我想帮你群发消息，但没太明白要发到哪个群、发什么内容，能再说清楚一点吗？"
            clarify = TBExcuse().ask(question, username=username)
            if clarify:
                plan = self._plan(f"{request}；用户补充：{clarify}", groups, username,
                                  content_type=content_type, text=text, url=url,
                                  file_path=file_path, at_name=at_name)

        if not plan or not plan.get("targets"):
            return "AI 未能确定发送目标与内容"

        # 信息充足：果断发送，不再每次确认；直传内容优先，LLM 拟稿兜底
        results = []
        has_direct = bool(direct.get("type"))
        for target in plan.get("targets", []):
            group_id = str(target.get("group_id", "") or "").strip()
            if not group_id:
                continue

            # 解析要 @ 的 QQ 号：直传 at_name 优先，其次计划里的 at_user_id / at_name
            at_qq = str(target.get("at_user_id", "") or "").strip()
            target_at_name = at_name or str(target.get("at_name", "") or "").strip()
            if target_at_name and not at_qq:
                try:
                    from func.toolbox.napcat.active_sender.get_group_memberlist import TBGetGroupMemberList
                    member = TBGetGroupMemberList().find_by_name(group_id, target_at_name)
                    if member:
                        at_qq = str(member.get("user_id", "") or "").strip()
                    else:
                        results.append(f"未在群 {group_id} 找到成员「{target_at_name}」，已改为普通文本发送")
                except Exception:
                    self.log.exception(f"反查群成员 QQ 失败: {target_at_name}")

            if has_direct:
                kind = direct["type"]
                if kind == "link" and direct["url"]:
                    if at_qq:
                        results.append(self.sender.send_group_at(group_id, at_qq, direct["url"]))
                    else:
                        results.append(self.sender.send_link("group", group_id, direct["url"], direct["text"]))
                elif kind == "image" and direct["file_path"]:
                    results.append(self.sender.send_image("group", group_id, direct["file_path"]))
                elif kind == "file" and direct["file_path"]:
                    results.append(self.sender.send_file("group", group_id, direct["file_path"]))
                elif direct["text"]:
                    if at_qq:
                        results.append(self.sender.send_group_at(group_id, at_qq, direct["text"]))
                    else:
                        results.append(self.sender.send_text("group", group_id, direct["text"]))
            else:
                t_text = str(target.get("text", "") or "").strip()
                if at_qq and t_text:
                    results.append(self.sender.send_group_at(group_id, at_qq, t_text))
                elif at_qq:
                    results.append(self.sender.send_group_at(group_id, at_qq, ""))
                elif t_text:
                    results.append(self.sender.send_text("group", group_id, t_text))
                t_file = str(target.get("file_path", "") or "").strip()
                if t_file:
                    results.append(self.sender.send_file("group", group_id, t_file))
                t_url = str(target.get("url", "") or "").strip()
                if t_url:
                    results.append(self.sender.send_link("group", group_id, t_url))
        self.sender.mark_active_send()
        return "；".join(results) if results else "未执行发送"

    @staticmethod
    def _direct_content(content_type: str, text: str, url: str, file_path: str) -> dict:
        """把上层直传的内容字段按 content_type 归类为 {type, text, url, file_path}"""
        ct = str(content_type or "").strip().lower()
        t = str(text or "").strip()
        u = str(url or "").strip()
        f = str(file_path or "").strip()
        if ct not in ("text", "link", "file", "image"):
            ct = "link" if u else ("file" if f else ("text" if t else ""))
        out = {"type": ct, "text": "", "url": "", "file_path": ""}
        if ct == "text":
            out["text"] = t
        elif ct == "link":
            out["url"] = u
            out["text"] = t
        elif ct in ("file", "image"):
            out["file_path"] = f
        return out

    @staticmethod
    def _uncertain(plan) -> bool:
        """是否需要向用户追问：未产出计划 / 明确要求澄清 / 未选定任何目标"""
        if not plan:
            return True
        if plan.get("need_clarify"):
            return True
        return not plan.get("targets")

    def _plan(self, request: str, groups: List[dict], username: str = "",
              content_type: str = "", text: str = "", url: str = "",
              file_path: str = "", at_name: str = "") -> Optional[dict]:
        llm = self._llm()
        if llm is None or not llm.client:
            return None
        group_lines = "\n".join(
            f"- group_id={g.get('group_id')} 群名={g.get('group_name') or ''}" for g in groups
        )
        # 内容已直传：模型只负责按列表选定目标，不要改写内容
        direct = self._direct_content(content_type, text, url, file_path)
        at_name = str(at_name or "").strip()
        direct_hint = ""
        if direct.get("type") or at_name:
            at_hint = f"，at_name={at_name!r}" if at_name else ""
            direct_hint = (
                "\n\n【本次要发送的内容已由用户确定，直接使用、不要改写】"
                f"content_type={direct['type']}，text={direct['text']!r}，"
                f"url={direct['url']!r}，file_path={direct['file_path']!r}{at_hint}；"
                "你只需从群列表选定发送目标群。"
            )
        # 完整系统提示词（角色人设 + 价值观 + 记忆），保证决策受角色约束
        system_prompt = self._system_prompt(username, request)
        resp = llm.chat([
            {"role": "system", "content": (
                f"{system_prompt}\n\n"
                f"根据群列表与用户需求，选定发送目标群并拟定消息。"
                f"如需求涉及文件或链接，可填写文件路径或链接。"
                f"如果用户要求 @ 群里的某个成员：已知其 QQ 号时填 at_user_id；"
                f"只知道昵称/群名片时填 at_name（由系统按名字反查 QQ 号，找不到会降级为普通文本发送）。"
                f"不需要 @ 时两者都留空。调用 send_to_groups_plan 工具输出计划。"
                f"若内容已确定（见下方提示），只选目标群、原样使用内容，不要改写。"
                f"只有在信息极度不全面、无法确定发到哪个群或发什么时，才把 need_clarify 设为 true 并给出询问问题；"
                f"信息足够时果断输出计划，need_clarify 设为 false。"
            )},
            {"role": "user", "content": f"群列表：\n{group_lines}\n\n需求：{request}{direct_hint}"},
        ], tools=self._plan_tools(), tool_choice={"type": "function", "function": {"name": "send_to_groups_plan"}})
        if not resp or not resp.choices:
            return None
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == "send_to_groups_plan":
                    return json.loads(tc.function.arguments or "{}")
        except Exception:
            self.log.exception("解析群发送计划失败")
        return None

    def _plan_tools(self) -> List[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "send_to_groups_plan",
                "description": "输出群发送计划，或在信息极度不全面时请求澄清",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "need_clarify": {
                            "type": "boolean",
                            "description": "信息是否极度不全面，无法确定目标群或内容",
                        },
                        "clarify_question": {
                            "type": "string",
                            "description": "需要询问用户的问题（need_clarify=true 时必填）",
                        },
                        "targets": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "group_id": {"type": "string"},
                                    "text": {"type": "string"},
                                    "at_name": {
                                        "type": "string",
                                        "description": "要 @ 的群成员昵称/群名片（按名字反查QQ号，可选）",
                                    },
                                    "at_user_id": {
                                        "type": "string",
                                        "description": "要 @ 的群成员QQ号（已知QQ号时直接填，可选）",
                                    },
                                    "file_path": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                                "required": ["group_id", "text"],
                            },
                        },
                    },
                    "required": ["need_clarify", "targets"],
                },
            },
        }]

    def _system_prompt(self, username: str, current_message: str) -> str:
        """获取决策用角色人设提示词（前置词+角色卡+价值观+后置词，无用户记忆、无「和谁说话」）"""
        try:
            from func.toolbox.get_prompt import TBoxGetPrompt
            return TBoxGetPrompt().get_tool_prompt(username, current_message) or ""
        except Exception:
            return ""

    def _llm(self):
        from func.toolbox.config import TBoxConfig
        cfg = TBoxConfig()
        if cfg.llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(cfg)
        if cfg.llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(cfg)
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(cfg)
