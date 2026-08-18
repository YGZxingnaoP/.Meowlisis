# -*- coding: utf-8 -*-
# func/catbrain/CatValues/update_values.py
# 价值观更新：纯更新功能（不含触发条件），分析→格式检查→审查→提交

import os
import json
import datetime
from typing import Dict, List, Optional, Tuple

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.CatValues.port.deepseek import MeowValuesDeepSeekLLM
from func.catbrain.CatValues.port.aliyun import MeowValuesAliyunLLM
from func.catbrain.CatValues.port.review import MeowValuesReviewLLM
from func.catbrain.CatValues.values_tools import MeowValuesUpdateTool, MeowValuesReviewTool
from func.catbrain.CatValues.load_values import MeowLoadValues
from func.toolbox.txt_reader.file_analysis import MeowFileAnalysis


class MeowUpdateValues:
    """价值观更新类：LLM 自主分析记忆并更新价值观（不含触发条件）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.update_tool = MeowValuesUpdateTool()
        self.review_tool = MeowValuesReviewTool()
        self.file_analysis = MeowFileAnalysis()
        self.loader = MeowLoadValues()
        self.llm = None
        self.values_dir = os.path.join("character", "info", "values")
        self.latest_path = os.path.join(self.values_dir, "latest.json")
        self.unchecked_path = os.path.join(self.values_dir, "unchecked.json")

    def _ensure_llm(self):
        """懒加载价值观独立 LLM 客户端"""
        if self.llm is None:
            if self.config.values_llm_type == "aliyun":
                self.llm = MeowValuesAliyunLLM()
            else:
                self.llm = MeowValuesDeepSeekLLM()
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
        path = os.path.join("func", "catbrain", "CatValues", filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            self.log.exception(f"读取提示词失败: {filename}")
            return fallback

    def _build_system_prompt(self, current: Dict) -> str:
        """构建分析阶段的系统提示词（角色身份 + 更新指令 + 当前价值观）"""
        instruction = self._load_prompt(
            "values_prompt.txt",
            "请回顾自己的记忆并更新价值观，必须调用 update_values 工具。")
        instruction = instruction.format(
            current_values=json.dumps(current, ensure_ascii=False, indent=2))
        persona = self._get_persona_prompt()
        if persona:
            return (
                f"你现在就是{AppConfig().ai_name}。请全程以{AppConfig().ai_name}的第一人称视角，"
                f"基于你自己的角色设定与价值观去回忆、思考和表达，不要跳出角色，"
                f"不要用第三人称称呼自己。\n\n"
                f"【你的角色设定与价值观】\n{persona}\n\n"
                f"【任务指令】\n{instruction}"
            )
        return instruction

    def _run_analysis(self, messages: List[Dict]) -> Optional[Dict]:
        """执行工具调用分析循环（上限100轮，超出直接结束不走后续流程）"""
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("价值观 LLM 不可用，跳过更新")
            return None
        tools = self.file_analysis.build_tools() + self.update_tool.build_tools()
        max_rounds = self.config.values_max_tool_rounds
        for round_idx in range(max_rounds):
            resp = llm.chat(messages, tools=tools)
            if not resp or not resp.choices:
                self.log.error("价值观 LLM 无响应")
                return None
            msg = resp.choices[0].message
            if not msg.tool_calls:
                # AI 未调用工具，提示其继续
                messages.append({"role": "assistant", "content": msg.content or ""})
                messages.append({"role": "user", "content": "请继续使用工具分析，或调用 update_values 输出结果。"})
                continue
            # 回填 assistant 的 tool_calls
            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                               for tc in msg.tool_calls]
            })
            for tc in msg.tool_calls:
                if tc.function.name == self.update_tool.TOOL_NAME:
                    try:
                        result = json.loads(tc.function.arguments)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": "ok"})
                        return result
                    except Exception:
                        self.log.exception("解析 update_values 参数失败")
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": "参数解析失败，请重新调用"})
                else:
                    # 文件分析工具分发执行
                    tool_result = self.file_analysis.dispatch(tc.function.name, tc.function.arguments)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})
        self.log.error(f"价值观分析超出最大轮数 {max_rounds}，直接结束")
        return None

    def _check_format(self, result: Dict) -> Tuple[bool, str]:
        """检查格式：5字段齐全且为非空字符串（主人的话由系统回填，不参与校验）"""
        for field in self.update_tool.FIELDS:
            if field not in result:
                return False, f"缺少字段: {field}"
            if not isinstance(result[field], str) or not result[field].strip():
                return False, f"字段 {field} 为空或非字符串"
        return True, ""

    def _fill_lock_field(self, result: Dict, lock_value: str):
        """程序化回填主人的话原值，彻底消除被修改的可能"""
        result[self.update_tool.LOCK_FIELD] = lock_value

    def _review(self, result: Dict, llm, current: Dict) -> Tuple[bool, str]:
        """审查环节：调用审查 LLM 判断新价值观是否合理，返回(是否通过, 意见)"""
        instruction = self._load_prompt(
            "review_prompt.txt",
            "你是审查员，请审查价值观更新结果，调用 review_values 工具输出结论。")
        instruction = instruction.format(ai_name=AppConfig().ai_name)
        system_text = instruction
        persona = self._get_persona_prompt()
        if persona:
            system_text += "\n\n【角色设定与价值观（供审查参照）】\n" + persona
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": f"角色当前价值观：\n{json.dumps(current, ensure_ascii=False, indent=2)}"},
            {"role": "user", "content": f"待审查的新价值观：\n{json.dumps(result, ensure_ascii=False, indent=2)}"}
        ]
        resp = llm.chat(messages, tools=self.review_tool.build_tools(),
                        tool_choice=self.review_tool.force_tool_choice())
        if not resp or not resp.choices:
            self.log.error("审查 LLM 无响应，默认不通过")
            return False, "审查 LLM 无响应"
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == self.review_tool.TOOL_NAME:
                    args = json.loads(tc.function.arguments)
                    return bool(args.get("pass")), str(args.get("feedback", ""))
        except Exception:
            self.log.exception("解析审查工具调用失败")
        return False, "审查结果解析失败"

    def _revise(self, messages: List[Dict], feedback: str) -> Optional[Dict]:
        """将审查意见反馈给分析 LLM 进行修改并重新输出"""
        messages.append({"role": "user", "content": f"审查未通过，修改意见如下，请修改后重新调用 update_values：\n{feedback}"})
        return self._run_analysis(messages)

    def update(self, reason: str = "") -> bool:
        """执行完整更新流程：分析→格式检查(3次)→一次审查(3次)→二次审查→提交"""
        self.log.info(f"价值观更新开始，触发原因: {reason}")
        current = self.loader.load()
        if not current:
            self.log.error("当前价值观为空，无法更新")
            return False
        lock_value = str(current.get(self.update_tool.LOCK_FIELD, ""))
        system_prompt = self._build_system_prompt(current)
        messages = [{"role": "system", "content": system_prompt}]

        # ===== 分析 + 格式检查（最多3次） =====
        result = None
        for attempt in range(3):
            result = self._run_analysis(list(messages))
            if result is None:
                self.log.error("分析流程未产出结果，放弃更新")
                return False
            ok, err = self._check_format(result)
            if ok:
                self._fill_lock_field(result, lock_value)
                break
            self.log.warning(f"价值观格式检查不通过(第{attempt + 1}次): {err}")
            messages.append({"role": "user", "content": f"上次输出格式错误: {err}，请重新分析并调用 update_values。"})
        else:
            self.log.error("价值观格式检查三次不通过，放弃更新")
            return False

        # 写入 unchecked.json
        self._write_unchecked(result)

        # ===== 一次审查（最多3次） =====
        review_messages = list(messages)
        for attempt in range(3):
            passed, feedback = self._review(result, self._ensure_llm(), current)
            if passed:
                break
            self.log.warning(f"一次审查不通过(第{attempt + 1}次): {feedback}")
            result = self._revise(review_messages, feedback)
            if result is None:
                self.log.error("审查修改流程未产出结果，放弃修改")
                return False
            ok, err = self._check_format(result)
            if not ok:
                self.log.warning(f"审查修改后格式不通过: {err}")
                continue
            self._fill_lock_field(result, lock_value)
            self._write_unchecked(result)
        else:
            self.log.error("一次审查三次不通过，放弃修改")
            return False

        # ===== 二次审查（config 开关，默认关闭） =====
        if self.config.values_second_review_enabled:
            review_llm = MeowValuesReviewLLM()
            if review_llm.client:
                for attempt in range(3):
                    passed, feedback = self._review(result, review_llm, current)
                    if passed:
                        break
                    self.log.warning(f"二次审查不通过(第{attempt + 1}次): {feedback}")
                    result = self._revise(review_messages, feedback)
                    if result is None:
                        self.log.error("二次审查修改流程未产出结果，放弃修改")
                        return False
                    ok, err = self._check_format(result)
                    if not ok:
                        continue
                    self._fill_lock_field(result, lock_value)
                    self._write_unchecked(result)
                else:
                    self.log.error("二次审查三次不通过，放弃修改")
                    return False
            else:
                self.log.warning("二次审查 LLM 不可用，跳过二次审查")

        # ===== 提交 =====
        self._fill_lock_field(result, lock_value)
        self._commit(result)
        self.log.info("价值观更新完成")
        return True

    def _write_unchecked(self, result: Dict):
        """将待审结果写入 unchecked.json"""
        os.makedirs(self.values_dir, exist_ok=True)
        try:
            with open(self.unchecked_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入 unchecked.json 失败")

    def _commit(self, result: Dict):
        """提交更新：旧 latest.json 重命名为 version-日期.json，写入新值并删除 unchecked"""
        os.makedirs(self.values_dir, exist_ok=True)
        if os.path.exists(self.latest_path):
            date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
            backup_path = os.path.join(self.values_dir, f"version-{date_str}.json")
            try:
                os.replace(self.latest_path, backup_path)
            except Exception:
                self.log.exception("价值观版本备份失败")
        try:
            with open(self.latest_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入价值观 latest.json 失败")
        # 删除 unchecked.json
        try:
            if os.path.exists(self.unchecked_path):
                os.remove(self.unchecked_path)
        except Exception:
            self.log.exception("删除 unchecked.json 失败")
