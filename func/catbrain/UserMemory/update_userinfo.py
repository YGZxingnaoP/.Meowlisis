# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/update_userinfo.py
# 用户信息更新：新用户猜测建档 + 轮数触发分析更新

import os
import json
import datetime
from threading import Thread, Lock
from typing import Dict, Optional

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.UserMemory.port.deepseek import MeowUserMemoryDeepSeekLLM
from func.catbrain.UserMemory.port.aliyun import MeowUserMemoryAliyunLLM
from func.catbrain.UserMemory.userinfo_tool import MeowUserInfoTool
from func.catbrain.UserMemory.get_userrecord import MeowGetUserRecord
from func.catbrain.UserMemory.load_usrmem import MeowLoadUserMemory


class MeowUpdateUserInfo:
    """用户信息更新类：新用户首条消息猜测建档，已有用户按轮数分析更新"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.tool = MeowUserInfoTool()
        self.userrecord = MeowGetUserRecord()
        self.loader = MeowLoadUserMemory()
        self.llm = None
        self.info_dir = os.path.join("character", "info", "users_info")
        # 建档写锁：保证“判断不存在→建占位档”原子，防止并发重复建档
        self._lock = Lock()

    def _ensure_llm(self):
        """懒加载用户记忆独立 LLM 客户端"""
        if self.llm is None:
            if self.config.user_llm_type == "aliyun":
                self.llm = MeowUserMemoryAliyunLLM()
            else:
                self.llm = MeowUserMemoryDeepSeekLLM()
        return self.llm

    def _get_persona_prompt(self) -> str:
        """延迟获取完整角色身份提示词（角色卡+价值观，方法内导入避免循环依赖）"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_persona_prompt() or ""
        except Exception:
            return ""

    def _load_prompt(self, filename: str, fallback: str) -> str:
        """读取提示词文件（缺失时使用兜底指令）"""
        path = os.path.join("func", "catbrain", "UserMemory", filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            self.log.exception(f"读取提示词失败: {filename}")
            return fallback

    def record(self, username: str, line: str, is_user: bool):
        """记录一条消息：新用户先建占位档并猜测，已有用户按轮数触发更新"""
        if not username:
            return
        # 加锁保证“判断不存在→建占位档”原子，防止后台建档期间的重复建档
        with self._lock:
            is_new = is_user and not self.loader.exists(username)
            if is_new:
                self._save_placeholder(username)
                self.userrecord.init_record(username, line)
        if is_new:
            # 占位档已落地，后台猜测失败也不会导致后续重复建档
            Thread(target=self._guess_new_user, args=(username, line), daemon=True).start()
            return
        # 已有用户：缓存消息，达到轮数触发分析更新
        if self.userrecord.record_message(username, line, is_user):
            Thread(target=self._analyze_update, args=(username,), daemon=True).start()

    def _guess_new_user(self, username: str, line: str):
        """新用户猜测建档：以角色视角根据首条消息猜测信息并写入档案"""
        from func.gobal.data import LLmData
        instruction = self._load_prompt(
            "guess_prompt.txt",
            "请以角色视角根据这条消息猜测该用户的基本信息，未知填 unknown，必须调用 save_user_info 工具。")
        system_text = instruction
        persona = self._get_persona_prompt()
        if persona:
            system_text = (
                f"你现在就是{LLmData().Ai_Name}。请全程以{LLmData().Ai_Name}的第一人称视角，"
                f"基于你自己的角色设定与价值观去看待这位用户，不要跳出角色，"
                f"不要用第三人称称呼自己。\n\n"
                f"【你的角色设定与价值观】\n{persona}\n\n"
                f"【任务指令】\n{instruction}"
            )
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": f"该用户发来的第一条消息：\n{line}"}
        ]
        result = self._call_tool(messages)
        if not result:
            self.log.error(f"新用户猜测建档失败: {username}")
            return
        result["name"] = username
        result["changed"] = True
        if self._check_format(result):
            self._save(username, result)

    def _analyze_update(self, username: str):
        """已有用户分析更新：以角色视角分析缓存对话并更新档案（AI 可决策不改动）"""
        content, count = self.userrecord.take_content(username)
        if not content.strip():
            return
        from func.gobal.data import LLmData
        instruction = self._load_prompt(
            "analyze_prompt.txt",
            "请以角色视角分析以下对话更新该用户信息档案，无变化时 changed 设为 false，必须调用 save_user_info 工具。")
        system_text = instruction
        persona = self._get_persona_prompt()
        if persona:
            system_text = (
                f"你现在就是{LLmData().Ai_Name}。请全程以{LLmData().Ai_Name}的第一人称视角，"
                f"基于你自己的角色设定与价值观去看待这位用户，不要跳出角色，"
                f"不要用第三人称称呼自己。\n\n"
                f"【你的角色设定与价值观】\n{persona}\n\n"
                f"【任务指令】\n{instruction}"
            )
        existing = self.loader.load(username)
        existing_text = json.dumps(existing, ensure_ascii=False) if existing else "（暂无档案）"
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": f"该用户当前档案：\n{existing_text}"},
            {"role": "user", "content": f"待分析的对话记录：\n{content}"}
        ]
        result = self._call_tool(messages)
        if not result:
            self.log.error(f"用户信息分析更新失败，写回缓存: {username}")
            self.userrecord.restore_content(username, content, count)
            return
        result["name"] = username
        # AI 决策不改动时跳过写入
        if result.get("changed") is False:
            self.log.info(f"用户信息无变化，跳过更新: {username}")
            return
        if self._check_format(result):
            self._save(username, result)

    def _call_tool(self, messages) -> Optional[Dict]:
        """调用 LLM 强制工具并解析 save_user_info 结果"""
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("用户记忆 LLM 不可用，跳过更新")
            return None
        resp = llm.chat(messages, tools=self.tool.build_tools(),
                        tool_choice=self.tool.force_tool_choice())
        if not resp or not resp.choices:
            self.log.error("用户记忆 LLM 无响应")
            return None
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == self.tool.TOOL_NAME:
                    return json.loads(tc.function.arguments)
        except Exception:
            self.log.exception("解析用户信息工具调用失败")
        return None

    def _check_format(self, result: Dict) -> bool:
        """检查格式：7 个字段齐全且值为字符串（仅格式校验，不做审查）"""
        for field in self.tool.FIELDS:
            if field not in result or not isinstance(result[field], str):
                self.log.error(f"用户信息格式不合法，缺少字段: {field}")
                return False
        return True

    def _is_placeholder(self, data: Dict) -> bool:
        """判断档案是否为占位档（除 name 外全部为 unknown）"""
        if not isinstance(data, dict):
            return False
        for field in self.tool.FIELDS:
            if field == "name":
                continue
            if str(data.get(field, "") or "").strip().lower() != "unknown":
                return False
        return True

    def _save_placeholder(self, username: str):
        """同步创建 unknown 占位档案（name 为用户名，其余字段 unknown）"""
        safe = self.loader._safe_name(username)
        if not safe:
            self.log.error("用户名清洗后为空，无法创建占位档案")
            return
        os.makedirs(self.info_dir, exist_ok=True)
        latest_path = os.path.join(self.info_dir, f"{safe}_latest.json")
        data = {field: "unknown" for field in self.tool.FIELDS}
        data["name"] = username
        try:
            with open(latest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log.info(f"已创建新用户占位档案: {latest_path}")
        except Exception:
            self.log.exception(f"创建占位档案失败: {latest_path}")

    def _save(self, username: str, result: Dict):
        """保存用户档案：旧文件重命名为 用户名-修改日期.json 保留，再写 latest"""
        os.makedirs(self.info_dir, exist_ok=True)
        safe = self.loader._safe_name(username)
        latest_path = os.path.join(self.info_dir, f"{safe}_latest.json")
        # 旧文件保留为 用户名-修改日期.json（占位档直接覆盖，避免垃圾备份）
        if os.path.exists(latest_path):
            old = self.loader.load(username)
            if not self._is_placeholder(old):
                date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
                backup_path = os.path.join(self.info_dir, f"{safe}-{date_str}.json")
                try:
                    os.replace(latest_path, backup_path)
                except Exception:
                    self.log.exception(f"用户档案备份失败: {latest_path}")
        # 只保留 7 个标准字段
        data = {k: result.get(k, "unknown") for k in self.tool.FIELDS}
        try:
            with open(latest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log.info(f"用户档案已更新: {latest_path}")
        except Exception:
            self.log.exception(f"写入用户档案失败: {latest_path}")
