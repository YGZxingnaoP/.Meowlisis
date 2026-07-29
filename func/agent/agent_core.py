# -*- coding: utf-8 -*-
# 文件位置: func/agent/agent_core.py
import os
import glob
import random
import uuid
import threading
from datetime import datetime
from pathlib import Path

from func.log.default_log import DefaultLog
from func.config.default_config import defaultConfig
from func.tools.singleton_mode import singleton
from func.vtuber.action_oper import ActionOper
from func.sing.sing_core import SingCore
from func.llm.llm_core import LLmCore  # 单例，用于访问记忆等
from func.memory.character import CharacterCard


@singleton
class AgentCore:
    """
    新 Agent 模块：
    - 不持有独立 LLM 客户端
    - 不进行主动决策循环（由 AutoLLM 替代）
    - 仅负责解析 LLM 返回的首行工具指令，并执行对应的工具动作
    - 提供 speak 方法供工具内部使用，将文本推入 TTS 队列并写入记忆
    """
    log = DefaultLog().getLogger()
    config = defaultConfig().get_config()
    agent_config = config.get('agent', {})

    def __init__(self):
        self.enabled = self.agent_config.get('enabled', False)
        if not self.enabled:
            self.log.info("Agent模块未启用")
            return

        # 加载角色卡（工具内部可能会用到角色名称等）
        character_path = self.agent_config.get('character_path', './character/MiaoWu.yaml')
        self.character = self._load_character(character_path)
        if not self.character:
            self.log.error("无法加载角色卡，Agent模块停止")
            self.enabled = False
            return

        # 依赖模块（通过单例获取）
        self.llm_core = LLmCore()
        self.vision_core = self.llm_core.vision_core
        self.action_oper = ActionOper()
        self.sing_core = SingCore()

        # 目标用户（Agent 发言写入此用户的记忆）
        self.target_uid = self.agent_config.get('target_uid', 'littleYGZ')

        # 节日列表（硬编码保留）
        self.holidays = {
            "01-01": "元旦", "02-14": "情人节", "03-08": "妇女节",
            "05-01": "劳动节", "06-01": "儿童节", "08-01": "建军节",
            "09-10": "教师节", "10-01": "国庆节", "11-11": "光棍节",
            "12-25": "圣诞节"
        }

        self.log.info("AgentCore 已初始化（仅工具执行模式）")

    def _load_character(self, path: str) -> CharacterCard:
        """加载角色卡，失败时返回 None"""
        try:
            card = CharacterCard(path)
            self.log.info(f"加载角色卡: {card.name}")
            return card
        except Exception as e:
            self.log.error(f"加载角色卡失败: {e}")
            return None

    # ========== 外部接口：由 LLmCore 调用 ==========
    def execute_tool(self, tool_name: str):
        """
        根据首行解析出的工具名，执行对应的工具逻辑。
        工具名可能为 'none' 或未知名称，此时直接返回。
        """
        if not tool_name or tool_name == "none":
            return
        tool_name = tool_name.strip().lower()
        self.log.info(f"Agent 接收工具指令: {tool_name}")

        try:
            if tool_name == "memory_recall":
                self._tool_memory_recall()
            elif tool_name == "sing":
                self._tool_sing()
            elif tool_name == "screenshot_and_describe":
                self._tool_screenshot()
            elif tool_name == "change_scene":
                self._tool_change_scene()
            elif tool_name == "change_clothes":
                self._tool_change_clothes()
            elif tool_name == "sleep_reminder":
                self._tool_sleep_reminder()
            elif tool_name == "meal_reminder":
                self._tool_meal_reminder()
            elif tool_name == "holiday_greeting":
                self._tool_holiday_greeting()
            elif tool_name == "talk":
                # talk 工具不需要额外动作，LLM 已经生成了回复
                pass
            else:
                self.log.warning(f"未知工具: {tool_name}")
        except Exception as e:
            self.log.exception(f"执行工具 {tool_name} 失败: {e}")

    # ========== 内部工具实现 ==========
    def _tool_memory_recall(self):
        """回忆某一天的聊天记录，并让 LLM 生成一句分享语"""
        # 随机选择一天，或由 LLM 在上下文中指定日期（简化：随机）
        date_str = None
        content, used_date = self._recall_memory_by_date(date_str)
        if used_date and content:
            # 构造提示，让 LLM 生成回复（使用 llm_core 的非流式接口）
            prompt = f"你回忆起了 {used_date} 的聊天记录，内容摘要如下：\n{content}\n请用亲切自然的一句话分享这个回忆（不要直接复制原文）。"
            # 使用 LLmCore 中的 aliyun_llm 进行简单生成，避免重入流式逻辑
            try:
                reply = self.llm_core.aliyun_llm.chat([
                    {"role": "system", "content": self.character.build_system_prompt()},
                    {"role": "user", "content": prompt}
                ])
                reply = reply.strip()
            except:
                reply = "喵呜好像想起了一点什么，但说不清楚喵~"
            self._speak(reply)
        else:
            self._speak("喵呜暂时没找到记忆喵，下次再试试吧~")

    def _tool_sing(self):
        """唱歌工具：随机选一首歌并播放，播放前用 TTS 告知歌名"""
        songname = ""
        from func.sing.sing_config import SONG_CACHE_DIR
        covers = glob.glob(f"{SONG_CACHE_DIR}/[喵呜翻唱]*.mp3")
        if covers:
            song_path = random.choice(covers)
            songname = os.path.basename(song_path).replace("[喵呜翻唱]", "").replace(".mp3", "")
        else:
            mp3s = glob.glob(f"{SONG_CACHE_DIR}/*.mp3")
            mp3s = [f for f in mp3s if not os.path.basename(f).startswith("[喵呜翻唱]")]
            if mp3s:
                song_path = random.choice(mp3s)
                songname = os.path.basename(song_path).replace(".mp3", "")
            else:
                self._speak(f"{self.character.name}现在没有学会任何歌曲呢，下次再唱给你听喵～")
                return
        # 告知歌名
        self._speak(f"{self.character.name}给大家唱一首《{songname}》喵～")
        # 异步播放
        def sing_task():
            self.sing_core.sing(songname, "主人", uid=0)
        threading.Thread(target=sing_task, daemon=True).start()

    def _tool_screenshot(self):
        """截图并描述（不发送图片给 LLM，仅触发视觉模块）"""
        self.vision_core.username = self.character.name
        self.vision_core.uid = 0
        def task():
            traceid = str(uuid.uuid4())
            self.vision_core.run_once(traceid)
        threading.Thread(target=task, daemon=True).start()

    def _tool_change_scene(self):
        """切换场景（需要从 LLM 上下文中获取场景名，此处简化用默认值）"""
        # 实际场景名应由 LLM 在首行中携带，但当前设计未传递参数。
        # 简化：随机选择一个场景，或通过硬编码预设场景。
        scene = "默认场景"  # 可配置
        self.action_oper.changeScene(scene)
        # 不额外说话，LLM 的衔接回复会说明

    def _tool_change_clothes(self):
        """换装（类似场景，需参数，简化处理）"""
        clothes = "默认服装"  # 可配置
        self.action_oper.emoteOper.emote_ws(1, 0, clothes)
        # 不额外说话

    def _tool_sleep_reminder(self):
        """睡觉提醒：用 LLM 生成一句关心话并说出"""
        try:
            prompt = "现在是晚上时间，你应该提醒主人早点睡觉。请说一句关心的话。"
            reply = self.llm_core.aliyun_llm.chat([
                {"role": "system", "content": self.character.build_system_prompt()},
                {"role": "user", "content": prompt}
            ]).strip()
            self._speak(reply)
        except:
            self._speak("主人，该睡觉了哦，喵呜一直在这里陪着你~")

    def _tool_meal_reminder(self):
        """吃饭提醒"""
        now = datetime.now()
        hour = now.hour
        if 12 <= hour <= 13:
            meal = "午饭"
        elif 17 <= hour <= 18:
            meal = "晚饭"
        else:
            return  # 不在饭点
        try:
            prompt = f"现在是{meal}时间，提醒主人该吃饭了。请用温柔的语气说一句话。"
            reply = self.llm_core.aliyun_llm.chat([
                {"role": "system", "content": self.character.build_system_prompt()},
                {"role": "user", "content": prompt}
            ]).strip()
            self._speak(reply)
        except:
            self._speak(f"主人，{meal}时间到啦，要好好吃饭喵~")

    def _tool_holiday_greeting(self):
        """节日祝福"""
        today = datetime.now().strftime("%m-%d")
        holiday = self.holidays.get(today, "节日")
        try:
            prompt = f"今天是{holiday}，请对主人说一句节日祝福，要可爱且符合{self.character.name}风格。"
            reply = self.llm_core.aliyun_llm.chat([
                {"role": "system", "content": self.character.build_system_prompt()},
                {"role": "user", "content": prompt}
            ]).strip()
            self._speak(reply)
        except:
            self._speak(f"今天是{holiday}，喵呜祝你开开心心喵~")

    # ========== 记忆相关辅助函数 ==========
    def _recall_memory_by_date(self, date_str=None):
        chat_dir = "./chatrecords"
        if not os.path.exists(chat_dir):
            return "还没有任何聊天记录喵。", None
        files = [f for f in os.listdir(chat_dir) if f.endswith(".txt")]
        if not files:
            return "暂无历史记忆喵。", None

        file_dates = []
        for f in files:
            try:
                date_part = f.replace(".txt", "")
                date_obj = datetime.strptime(date_part, "%Y-%m-%d")
                file_dates.append((date_obj, f))
            except:
                continue
        if not file_dates:
            return "没有可用的记忆文件喵。", None

        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d")
                target_file = None
                for d, f in file_dates:
                    if d.date() == target_date.date():
                        target_file = f
                        break
                if not target_file:
                    return f"没有找到 {date_str} 的记忆喵。", None
                filepath = os.path.join(chat_dir, target_file)
            except:
                return "日期格式错误，请用 YYYY-MM-DD 格式喵。", None
        else:
            selected = random.choice(file_dates)
            target_date, target_file = selected
            filepath = os.path.join(chat_dir, target_file)
            date_str = target_date.strftime("%Y-%m-%d")

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > 2000:
            content = content[:2000] + "...(已截断)"
        return content, date_str

    # ========== 语音输出接口 ==========
    def _speak(self, text: str, username: str = None):
        """
        供工具内部直接发送文本到 TTS 队列，并记录到记忆和聊天记录。
        如果 LLM 已经生成了衔接回复，工具不应该额外说话，
        此方法仅用于确实需要补充语音的场景（如唱歌前告知歌名、回忆摘要等）。
        """
        if not text:
            return
        if username is None:
            username = self.character.name
        traceid = str(uuid.uuid4())

        # 推送到 TTS 队列
        json_msg = {
            "voiceType": "chat",
            "traceid": traceid,
            "chatStatus": "end",
            "question": "",
            "text": text,
            "lanuage": "AutoChange",
            "seg_index": 0,
            "total_segments": 1
        }
        self.llm_core.llmData.AnswerList.put(json_msg)
        self.log.info(f"[{traceid}] Agent 发言: {text}")

        # 写入短期记忆（assistant 角色）
        uid_str = str(self.target_uid)
        memory = self.llm_core._ensure_memory_manager(uid_str, username)
        if memory:
            if hasattr(memory, 'short_term_memory'):   # Mem0Manager
                memory.short_term_memory.append({"role": "assistant", "content": text})
            elif hasattr(memory, 'short_term_buffer'): # MemoryManager
                memory.short_term_buffer.append({"role": "assistant", "content": text})

        # 写入聊天记录文件
        self.llm_core._write_chat_record(username, text, self.llm_core.llmData.Ai_Name)