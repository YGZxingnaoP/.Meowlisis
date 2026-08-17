# func/minecraft/logreader.py
import os
import re
import threading
import time
import uuid
import chardet
from func.log.default_log import DefaultLog
from func.config.default_config import defaultConfig
from func.gobal.data import LLmData

class MinecraftLogReader:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = defaultConfig().get_config()
        self.llm_data = LLmData()
        self.enabled = False
        self.log_path = ""
        self.encoding = "utf-8"          # 默认编码，可配置
        self.check_interval = 5.0
        self.last_position = 0
        self.thread = None
        self.running = False
        self.last_sent_msg = None          # 记录上次发送的消息，用于去重

    def load_config(self):
        mc_cfg = self.config.get('minecraft', {})
        self.enabled = mc_cfg.get('enabled', False)
        self.log_path = mc_cfg.get('log_path', '')
        self.encoding = mc_cfg.get('encoding', 'utf-8')
        self.check_interval = mc_cfg.get('check_interval', 5.0)
        self.use_player_name = mc_cfg.get('use_player_name', False)
        self.username_fixed = mc_cfg.get('username_fixed', 'MinecraftSever')
        self.include_player_name_in_prompt = mc_cfg.get('include_player_name_in_prompt', True)
        self.filter_players = mc_cfg.get('filter_players', [])
        self.ignore_self_messages = mc_cfg.get('ignore_self_messages', False)
        if self.log_path and not os.path.exists(self.log_path):
            self.log.warning(f"Minecraft 日志文件不存在: {self.log_path}")
            self.enabled = False

    def start(self):
        if not self.enabled or not self.log_path:
            self.log.info("Minecraft 日志读取未启用")
            return
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()
        self.log.info(f"Minecraft 日志读取已启动，文件：{self.log_path}，编码：{self.encoding}")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

    def _detect_encoding(self, raw_data):
        """自动检测编码（备用方案）"""
        result = chardet.detect(raw_data)
        return result['encoding'] or 'utf-8'

    def _monitor(self):
        # 初始化文件位置到末尾
        try:
            with open(self.log_path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                self.last_position = f.tell()
        except OSError as e:
            self.log.error(f"初始化日志文件失败: {e}")
            self.last_position = 0  # 出错时从开头开始

        while self.running:
            try:
                with open(self.log_path, 'rb') as f:
                    f.seek(self.last_position)
                    raw_data = f.read()
                    self.last_position = f.tell()

                if not raw_data:
                    time.sleep(self.check_interval)
                    continue

                # 解码
                try:
                    content = raw_data.decode(self.encoding)
                except UnicodeDecodeError:
                    detected_enc = self._detect_encoding(raw_data)
                    self.log.warning(f"解码失败，自动检测为 {detected_enc}，将使用此编码")
                    content = raw_data.decode(detected_enc)
                    self.encoding = detected_enc

                lines = content.splitlines()
                # 处理所有新行（按时间顺序）
                for line in lines:
                    self._process_line(line)

            except OSError as e:
                # 捕获文件相关的错误（如文件被替换、删除、权限变化等）
                self.log.error(f"读取 Minecraft 日志时发生 OSError: {e}，将重置文件指针并重试")
                self.last_position = 0  # 重置指针
                time.sleep(self.check_interval)  # 稍等片刻再重试
            except Exception as e:
                self.log.error(f"读取 Minecraft 日志失败: {e}")
                time.sleep(self.check_interval)

    def _process_line(self, line):
        if '[CHAT]' not in line:
            return

        chat_part = line.split('[CHAT]', 1)[1].strip()
        if chat_part.startswith('<') and '>' in chat_part:
            player_end = chat_part.find('>')
            player_name = chat_part[1:player_end].strip()
            message = chat_part[player_end+1:].strip()
        else:
            player_name = "System Message"
            message = chat_part

        # 过滤：如果 filter_players 非空且玩家不在列表中，则忽略
        if self.filter_players and player_name not in self.filter_players:
            self.log.debug(f"忽略不在白名单的玩家: {player_name}")
            return

        # 忽略自己发送的消息
        if self.ignore_self_messages and player_name == self.username_fixed:
            self.log.debug(f"忽略自己发送的消息: {player_name}")
            return

        self._send_message(message, player_name)

    def _send_message(self, msg, player_name):
        if msg == self.last_sent_msg:
            self.log.info(f"Minecraft 重复事件，忽略: {msg}")
            return
        self.last_sent_msg = msg

        # 根据配置决定 username（使用玩家名或固定用户名）
        username = player_name if self.use_player_name else self.username_fixed

        # 构造 prompt
        if self.include_player_name_in_prompt:
            full_msg = f"主人在玩Minecraft的时候，{player_name}说：{msg}"
        else:
            full_msg = f"主人在玩Minecraft的时候，{msg}"

        traceid = str(uuid.uuid4())
        llm_json = {
            "traceid": traceid,
            "prompt": full_msg,
            "username": username
        }
        self.llm_data.QuestionList.put(llm_json)
        self.log.info(f"[{traceid}] Minecraft 事件: {full_msg}")