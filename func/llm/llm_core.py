# -*- coding: utf-8 -*-
# 文件位置: func/llm/llm_core.py
from func.log.default_log import DefaultLog
import re
import threading
import random
import json
import uuid
import os
import datetime
import atexit
from threading import Thread
from pathlib import Path
from func.config.default_config import defaultConfig
from func.tools.singleton_mode import singleton
from func.obs.obs_init import ObsInit
from func.tools.string_util import StringUtil
from func.vtuber.action_oper import ActionOper
from func.tts.tts_core import TTsCore

from func.llm.port.ollama import Ollama
from func.llm.port.aliyun import AliyunLLM
from func.llm.port.aliyun_stream import AliyunStreamLLM
from func.llm.port.bigmodel import BigModel
from func.llm.port.deepseek import DeepSeekLLM

from func.memory.memory import MemoryManager
from func.memory.memory_manager import Mem0Manager

from func.gobal.data import LLmData
from func.gobal.data import CommonData
from func.vision.qwen_vision_core import QwenVisionCore
from func.memory.character import CharacterCard
from func.llm.utils.response_processor import ResponseProcessor, StreamingResponseProcessor
from func.llm.utils.message_builder import MessageBuilder
from func.llm.utils.scene_manager import SceneManager
from func.llm.utils.ai_response_handler import AIResponseHandler


@singleton
class LLmCore:
    log = DefaultLog().getLogger()
    commonData = CommonData()
    llmData = LLmData()

    actionOper = ActionOper()
    ttsCore = TTsCore()

    local_llm_type: str = llmData.local_llm_type
    if local_llm_type == "ollama":
        ollama = Ollama()
        llm = ollama
    elif local_llm_type == "aliyun":
        aliyun_llm = AliyunStreamLLM()
        llm = aliyun_llm
    elif local_llm_type == "bigmodel":
        bigmodel = BigModel()
        llm = bigmodel
    elif local_llm_type == "deepseek":
        deepseek_llm = DeepSeekLLM()
        llm = deepseek_llm
    else:
        ollama = Ollama()
        llm = ollama

    def __init__(self):
        self.config = defaultConfig().get_config()
        self.obs = ObsInit().get_ws()
        self.mem0_managers = {}
        self.memory_trigger_keywords = [
            "记得", "知道", "还记得", "记不记得", "忘记", "回忆", "上次", "以前", "聊过",
            "说过", "提到过", "讨论过", "你记得吗", "你还记得", "那个事", "那件事", "那个谁"
        ]
        self.aliyun_llm = AliyunLLM()  # 非流式实例，供 Agent 工具内部使用
        ollama_config = self.config.get('llm', {}).get('ollama', {})
        self.ollama_stream = ollama_config.get('stream', False)
        self.chat_template = ollama_config.get('chat_template', 'auto')

        # 预设回复缓存
        self.preset_responses = {}
        self.load_preset_responses()
        self.last_msg_contain_dont_speak = False

        self._summary_generator = self._create_summary_generator()
        self._pause_timer = None
        atexit.register(self._cleanup)

        # 记忆配置
        memory_config = self.config.get('llm', {}).get('memory', {})
        self.memory_short_term_rounds = memory_config.get('short_term_rounds', 3)
        self.memory_shared = memory_config.get('shared', False)
        self.memory_enable_summary = memory_config.get('enable_summary', True)
        self.memory_max_pending = memory_config.get('max_pending_rounds', 5)
        model_level = memory_config.get('model_level', 'small')
        if model_level == 'large':
            self.memory_embedding_model_path = "./mem0model-large"
        else:
            self.memory_embedding_model_path = "./mem0model-small"

        # 视觉核心选择
        from func.vision.qwen_vision_core import QwenVisionCore
        self.vision_core = QwenVisionCore()

        # Agent 模式相关
        self.agent_mode = self.config.get('agent', {}).get('enabled', False)
        self.agent_prompt = ""
        if self.agent_mode:
            try:
                prompt_path = Path("./agent/prompt.txt")
                if prompt_path.exists():
                    with open(prompt_path, "r", encoding="utf-8") as f:
                        self.agent_prompt = f.read()
                    self.log.info("Agent 提示词已加载")
                else:
                    self.log.warning(f"Agent 提示词文件不存在: {prompt_path}，将使用默认格式要求")
                    self.agent_prompt = "你需要按照“调用工具：工具名”格式回复。"
            except Exception as e:
                self.log.error(f"加载 Agent 提示词失败: {e}")
                self.agent_mode = False

        self.vision_core.llm_core = self
        self.vision_core.username = None
        self.vision_core.uid = None

        # 加载角色卡配置
        self.character_cards = []
        self._load_character_cards()

        # 初始化响应处理器（仅非 Agent 模式使用）
        self.response_handler = AIResponseHandler(self)

    def _cleanup(self):
        if self._pause_timer:
            self._pause_timer.cancel()

    def _create_summary_generator(self):
        def generator(dialogue_text):
            prompt = f"概述一下对话内容，着重强调客观事实，明确事件、日期等，注意喵呜和对话人的关系，必须忽略情感表达，忽略与角色身份相关的已知设定。禁止出现情感评价和抽象概括，禁止添加对话中没有的内容，禁止输出不符合身份的内容。用简洁的中文总结，不超过200字\n对话：{dialogue_text}\n总结："
            messages = [{"role": "user", "content": prompt}]
            summary = self.aliyun_llm.chat(messages)
            summary = summary.strip()
            if len(summary) > 300:
                summary = summary[:300] + "…"
            return summary
        return generator

    def _load_character_cards(self):
        """同原代码，略"""
        char_configs = self.config.get('character_cards', [])
        if char_configs:
            for cfg in char_configs:
                file_path = Path("./character") / cfg.get('file', '')
                if file_path.exists():
                    try:
                        card = CharacterCard(str(file_path))
                        card.keywords = cfg.get('keywords', [])
                        card.weight = cfg.get('weight', 1.0)
                        card.token_strategy = cfg.get('token_strategy', getattr(card, 'token_strategy', 'chat'))
                        self.character_cards.append(card)
                        self.log.info(f"加载角色卡: {card.name}, 关键词: {card.keywords}, 权重: {card.weight}")
                    except Exception as e:
                        self.log.warning(f"加载角色卡失败 {file_path}: {e}")
        else:
            char_dir = Path("./character")
            if char_dir.exists():
                for file_path in char_dir.glob("*.yaml"):
                    try:
                        card = CharacterCard(str(file_path))
                        card.keywords = []
                        card.weight = 1.0
                        self.character_cards.append(card)
                        self.log.info(f"加载默认角色卡: {card.name}")
                    except Exception as e:
                        self.log.warning(f"加载角色卡失败 {file_path}: {e}")
            else:
                self.log.warning("角色卡目录不存在: ./character")
        if not self.character_cards:
            self.log.warning("未找到任何角色卡，将使用默认角色卡")
            default_path = Path("./character/MiaoWu.yaml")
            if default_path.exists():
                try:
                    card = CharacterCard(str(default_path))
                    card.keywords = []
                    card.weight = 1.0
                    self.character_cards.append(card)
                except Exception as e:
                    self.log.error(f"加载默认角色卡失败: {e}")

    def select_character_by_message(self, message: str) -> CharacterCard:
        """同原代码，略"""
        if not self.character_cards:
            default_path = Path("./character/MiaoWu.yaml")
            if default_path.exists():
                return CharacterCard(str(default_path))
            else:
                raise Exception("没有可用的角色卡")
        hit_cards = []
        for card in self.character_cards:
            if any(keyword in message for keyword in card.keywords):
                hit_cards.append(card)
        if hit_cards:
            weights = [c.weight for c in hit_cards]
            selected = random.choices(hit_cards, weights=weights, k=1)[0]
            self.log.info(f"根据关键词命中角色卡: {selected.name}")
            return selected
        else:
            weights = [c.weight for c in self.character_cards]
            selected = random.choices(self.character_cards, weights=weights, k=1)[0]
            self.log.info(f"未命中关键词，随机选择角色卡: {selected.name}")
            return selected

    def load_preset_responses(self):
        """同原代码，略"""
        preset_dir = "./chatpreset"
        if not os.path.exists(preset_dir):
            os.makedirs(preset_dir, exist_ok=True)
            self.log.info(f"创建预设目录: {preset_dir}")
        for filename in os.listdir(preset_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(preset_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            for key, replies in data.items():
                                if isinstance(replies, list):
                                    if key in self.preset_responses:
                                        self.preset_responses[key].extend(replies)
                                    else:
                                        self.preset_responses[key] = replies
                        self.log.info(f"加载预设文件: {filename}")
                except Exception as e:
                    self.log.error(f"加载预设文件失败 {filename}: {e}")

    def _ensure_memory_manager(self, uid_str, username=None):
        """同原代码，略"""
        if self.local_llm_type in ("aliyun", "ollama", "bigmodel", "deepseek"):
            if uid_str not in self.mem0_managers:
                memory_config = self.config.get('llm', {}).get('memory', {})
                long_term_dir = memory_config.get('long_term_dir', "./chatrecords")
                enable_mem0 = memory_config.get('enable_mem0', True)
                enable_chat_record_retrieval = memory_config.get('enable_chat_record_retrieval', True)
                chat_record_days = memory_config.get('chat_record_days', 7)
                chat_record_top_k = memory_config.get('chat_record_top_k', 3)
                mem0_config = {
                    "vector_store": {
                        "provider": "chroma",
                        "config": {
                            "collection_name": f"mem0_{uid_str}",
                            "path": f"./mem0_data/{uid_str}",
                        }
                    },
                    "embedder": {
                        "provider": "huggingface",
                        "config": {
                            "model": self.memory_embedding_model_path,
                        }
                    },
                    "llm": {
                        "provider": "ollama",
                        "config": {
                            "api_key": "dummy",
                            "model": "qwen2.5:1.5b",
                            "ollama_base_url": "http://localhost:11434"
                        }
                    }
                }
                self.mem0_managers[uid_str] = Mem0Manager(
                    uid=uid_str,
                    max_pending_rounds=self.memory_max_pending,
                    short_term_rounds=self.memory_short_term_rounds,
                    summary_generator=self._summary_generator if self.memory_enable_summary else None,
                    enable_summary=self.memory_enable_summary,
                    mem0_config=mem0_config,
                    shared_user_id=None,
                    long_term_dir=long_term_dir,
                    template_type=self.chat_template,
                    ai_name=self.llmData.Ai_Name,
                    chat_record_dir="./chatrecords",
                    enable_mem0=enable_mem0,
                    enable_chat_record_retrieval=enable_chat_record_retrieval,
                    chat_record_days=chat_record_days,
                    chat_record_top_k=chat_record_top_k
                )
            return self.mem0_managers[uid_str]
        else:
            return None

    def should_use_long_term_memory(self, message: str) -> bool:
        message_lower = message.lower()
        for keyword in self.memory_trigger_keywords:
            if keyword in message:
                return True
        if len(message) > 15:
            return random.random() < 0.5
        return False

    def aiResponseTry(self):
        try:
            self.ai_response()
        except Exception as e:
            self.log.exception(f"【ai_response】发生了异常：")
            self.llmData.is_ai_ready = True

    def _write_chat_record(self, username: str, message: str, role: str):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        filepath = os.path.join("./chatrecords", f"{today}.txt")
        os.makedirs("./chatrecords", exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%H:%M")
        message = message.replace('\n', ' ').replace('\r', ' ')
        message = ' '.join(message.split())
        line = f"[{timestamp}] {role}：{message}\n"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line)

    def ai_response(self):
        """根据 agent_mode 选择不同的处理流程"""
        if self.agent_mode:
            self._agent_response()
        else:
            self.response_handler.process()

    def _agent_response(self):
        """
        Agent 模式下的流式回复处理：
        1. 从 QuestionList 获取一条消息
        2. 构建 messages（加入 agent_prompt）
        3. 调用流式接口，拦截首行工具指令，后续正常发送 TTS
        """
        if self.llmData.QuestionList.empty():
            return
        question_data = self.llmData.QuestionList.get()
        traceid = question_data["traceid"]
        prompt = question_data["prompt"]
        uid = question_data.get("uid", 0)
        username = question_data.get("username", "用户")

        # 获取角色卡与系统提示
        selected_card = self.select_character_by_message(prompt)
        system_prompt = selected_card.build_system_prompt() if selected_card else ""
        # 追加 agent 格式指令
        if self.agent_prompt:
            system_prompt += "\n" + self.agent_prompt

        # 构建 messages（简化：仅包含系统和用户消息，记忆管理在外部已处理）
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        # 调用流式 LLM
        try:
            stream = self.llm.chat_stream(messages)  # 假设所有 LLM 实例都有 chat_stream 方法
        except AttributeError:
            self.log.error("当前 LLM 不支持流式调用，无法启用 Agent 模式")
            # 降级为非流式？此处简单忽略
            self.llmData.is_ai_ready = True
            return

        # 处理流式令牌
        agent_buffer = ""
        agent_handled = False
        tool_name = "none"
        full_reply = ""

        for token in stream:
            # 假设 token 是字符串 (不同 LLM 可能返回 dict，这里统一处理)
            if isinstance(token, dict):
                token_text = token.get("content", "")
            else:
                token_text = token

            if not agent_handled:
                # 在遇到第一个换行符之前缓存
                if '\n' in token_text:
                    parts = token_text.split('\n', 1)
                    agent_buffer += parts[0]
                    # 提取工具名
                    tool_name = self._parse_tool_header(agent_buffer)
                    if tool_name:
                        self.log.info(f"Agent 解析工具: {tool_name}")
                        # 异步执行工具
                        from func.agent.agent_core import AgentCore
                        agent = AgentCore()
                        threading.Thread(target=agent.execute_tool, args=(tool_name,), daemon=True).start()
                    else:
                        # 格式错误，将首行内容也加入回复
                        self._send_tts_chunk(agent_buffer + '\n', traceid, 0, 1)
                        full_reply += agent_buffer + '\n'
                    agent_handled = True
                    # 如果还有剩余文本（换行后的部分），继续处理
                    if len(parts) > 1 and parts[1]:
                        self._send_tts_chunk(parts[1], traceid, 0, 1)
                        full_reply += parts[1]
                else:
                    agent_buffer += token_text
            else:
                # 正常流式推送
                self._send_tts_chunk(token_text, traceid, 0, 1)
                full_reply += token_text

        # 流结束，未遇到换行符
        if not agent_handled:
            # 整个回复作为普通文本
            self._send_tts_chunk(agent_buffer, traceid, 0, 1)
            full_reply = agent_buffer

        # 写入聊天记录和记忆
        self._write_chat_record(username, prompt, username)  # 用户消息
        self._write_chat_record(selected_card.name if selected_card else "AI", full_reply, self.llmData.Ai_Name)
        # 写入短期记忆
        uid_str = str(uid)
        memory = self._ensure_memory_manager(uid_str, username)
        if memory:
            if hasattr(memory, 'short_term_memory'):
                memory.short_term_memory.append({"role": "assistant", "content": full_reply})
            elif hasattr(memory, 'short_term_buffer'):
                memory.short_term_buffer.append({"role": "assistant", "content": full_reply})

        self.llmData.is_ai_ready = True

    def _parse_tool_header(self, line: str) -> str:
        """从首行提取工具名，格式：调用工具：xxxx"""
        line = line.strip()
        pattern = r'调用工具[：:]\s*(\w+)'
        match = re.search(pattern, line)
        if match:
            tool = match.group(1).lower()
            return tool
        return ""

    def _send_tts_chunk(self, text: str, traceid: str, seg_index: int, total_segments: int):
        """将文本片段推送到 TTS 队列"""
        if not text:
            return
        json_msg = {
            "voiceType": "chat",
            "traceid": traceid,
            "chatStatus": "end",
            "question": "",
            "text": text,
            "lanuage": "AutoChange",
            "seg_index": seg_index,
            "total_segments": total_segments
        }
        self.llmData.AnswerList.put(json_msg)

    def check_answer(self):
        if not self.llmData.QuestionList.empty() and self.llmData.is_ai_ready:
            self.llmData.is_ai_ready = False
            answers_thread = Thread(target=self.aiResponseTry)
            answers_thread.start()

    def check_welcome_room(self):
        count = len(self.llmData.WelcomeList)
        numstr = ""
        if count > 1:
            numstr = f"{count}位"
        userlist = str(self.llmData.WelcomeList).replace("['", "").replace("']", "")
        if len(self.llmData.WelcomeList) > 0:
            traceid = str(uuid.uuid4())
            text = f'欢迎"{userlist}"{numstr}来到{self.commonData.Ai_Name}的直播间喵'
            self.log.info(f"[{traceid}]{text}")
            self.llmData.WelcomeList.clear()
            if self.llmData.is_llm_welcome == True:
                llm_json = {"traceid": traceid, "prompt": text, "uid": 0, "username": self.commonData.Ai_Name}
                self.llmData.QuestionList.put(llm_json)
            else:
                self.ttsCore.tts_say(text)

    def msg_deal(self, traceid, query, uid, user_name):
        text = self.llmData.cmd
        is_contain = StringUtil.has_string_reg_list(f"^{text}", query)
        if is_contain is not None:
            num = StringUtil.is_index_contain_string(text, query)
            queryExtract = query[num: len(query)]
            queryExtract = queryExtract.strip()
            self.log.info(f"[{traceid}]用户对话：" + queryExtract)
            if queryExtract == "":
                return True

            # 根据消息选择角色卡并通知 TTS
            try:
                selected_card = self.select_character_by_message(queryExtract)
                if selected_card:
                    char_name = Path(selected_card.file_path).stem
                    self.ttsCore.set_current_character(char_name)
                    self.log.info(f"[{traceid}] 当前使用角色卡: {char_name}")
            except Exception as e:
                self.log.error(f"[{traceid}] 选择角色卡失败: {e}")

            # 视觉触发
            self.vision_core.username = user_name
            self.vision_core.uid = uid
            if self.vision_core.check_and_trigger(queryExtract, traceid):
                return True

            # 连续“不要说话”检测
            current_contain = "不要说话" in queryExtract
            if current_contain and self.last_msg_contain_dont_speak:
                self.log.info(f'[{traceid}] 检测到连续"不要说话"，暂停语音输出30秒')
                self.ttsCore.pause()
                while not self.llmData.QuestionList.empty():
                    try:
                        self.llmData.QuestionList.get_nowait()
                    except:
                        break
                while not self.llmData.AnswerList.empty():
                    try:
                        self.llmData.AnswerList.get_nowait()
                    except:
                        break
                if self._pause_timer:
                    self._pause_timer.cancel()
                self._pause_timer = threading.Timer(30.0, self.ttsCore.resume)
                self._pause_timer.daemon = True
                self._pause_timer.start()
                self.last_msg_contain_dont_speak = current_contain
                return True
            self.last_msg_contain_dont_speak = current_contain

            # 预设回复匹配
            matched_keyword = None
            matched_reply = None
            for keyword, replies in self.preset_responses.items():
                if keyword in queryExtract:
                    matched_keyword = keyword
                    if user_name == "YGZ醒脑片":
                        replies_filtered = replies
                    else:
                        replies_filtered = [r for r in replies if "主人" not in r]
                    if replies_filtered:
                        matched_reply = random.choice(replies_filtered)
                    else:
                        self.log.info(f"[{traceid}] 用户 {user_name} 无法使用预设关键词 {keyword} 的回复（全部包含主人），继续走 LLM")
                        matched_reply = None
                    break

            if matched_reply:
                self.log.info(f'[{traceid}] 命中预设关键词"{matched_keyword}"，回复: {matched_reply}')
                jsonStr = {
                    "voiceType": "chat",
                    "traceid": traceid,
                    "chatStatus": "end",
                    "question": queryExtract,
                    "text": matched_reply,
                    "lanuage": "AutoChange",
                    "seg_index": 0,
                    "total_segments": 1
                }
                self.llmData.AnswerList.put(jsonStr)
                uid_str = str(uid)
                memory = self._ensure_memory_manager(uid_str, user_name)
                if memory:
                    memory.add_user_message(queryExtract, user_name)
                    memory.add_assistant_message(matched_reply)
                self._write_chat_record(user_name, queryExtract, user_name)
                self._write_chat_record(user_name, matched_reply, self.llmData.Ai_Name)
                return True
            else:
                self._write_chat_record(user_name, queryExtract, user_name)

            # 正常 LLM 流程（包含 Agent 模式）
            llm_json = {"traceid": traceid, "prompt": queryExtract, "uid": uid, "username": user_name}
            self.llmData.QuestionList.put(llm_json)
            return True
        return False

    def add_system_message(self, text, username="主人", uid=0):
        traceid = str(uuid.uuid4())
        llm_json = {
            "traceid": traceid,
            "prompt": text,
            "uid": uid,
            "username": username
        }
        self.llmData.QuestionList.put(llm_json)
        self.log.info(f"[{traceid}] 系统主动消息: {text}")

    def get_recent_conversations(self, uid_str, rounds=None):
        if rounds is None:
            rounds = getattr(self, 'memory_short_term_rounds', 3)
        manager = self.mem0_managers.get(uid_str)
        if manager and hasattr(manager, 'short_term_memory'):
            messages = manager.short_term_memory[-rounds*2:]
            formatted = []
            for msg in messages:
                if msg['role'] == 'user':
                    formatted.append(f"用户: {msg['content']}")
                elif msg['role'] == 'assistant':
                    formatted.append(f"喵呜: {msg['content']}")
            return formatted
        return []