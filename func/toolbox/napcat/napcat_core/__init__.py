# -*- coding: utf-8 -*-
# func/toolbox/napcat/napcat_core/__init__.py
# NapCat 核心门面：组合连接 / 发送 / 缓冲 / 事件处理，对外暴露 TBNapCatCore

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.config import TBNapCatConfig

from func.toolbox.napcat.napcat_core.connection import TBNapCatConnection
from func.toolbox.napcat.napcat_core.api_client import TBNapCatApiClient
from func.toolbox.napcat.napcat_core.buffer import TBNapCatBuffer
from func.toolbox.napcat.napcat_core.event_handler import TBNapCatEventHandler


@singleton
class TBNapCatCore:
    """NapCat 控制核心门面：组合各子模块，保持对外接口与旧 napcat_core.py 一致。

    子模块：
    - connection：WS 连接 / 收事件 / echo 队列；
    - api_client：send_* / call_action_sync；
    - buffer：私聊缓冲 + 群聊 @ 缓冲；
    - event_handler：私聊 / 群聊 / 戳一戳业务路由。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self.enabled = self.config.enabled

        # 连接层（唯一持有 loop / ws / echo / pending）
        self.connection = TBNapCatConnection(self.log, self.config)
        # 发送层
        self.api_client = TBNapCatApiClient(self.log, self.config, self.connection)

        # 消息解析与历史拉取
        from func.toolbox.napcat.message.get_message import TBGetMessage
        from func.toolbox.napcat.message.get_record import TBGetRecord
        from func.toolbox.napcat.groupchat.get_group_message import TBGetGroupMessage
        self.get_message = TBGetMessage()
        self.get_record = TBGetRecord()
        self.get_group_message = TBGetGroupMessage()

        # 缓冲层
        self.buffer = TBNapCatBuffer(self.log, self.config, self.get_record)
        # 事件处理层
        self.event_handler = TBNapCatEventHandler(
            self.log, self.config,
            self.get_message, self.get_record, self.get_group_message,
            self.api_client, self.buffer,
        )

        # 绑定事件回调与停止清理到连接层
        self.connection.on_private_message = self.event_handler._handle_private_message
        self.connection.on_group_message = self.event_handler._handle_group_message
        self.connection.on_poke = self.event_handler._handle_poke
        self.connection.dump_event = self.event_handler._dump_event
        self.connection.on_stop_cleanup = self._stop_cleanup

    def _stop_cleanup(self):
        """停止时清理所有缓冲定时器"""
        self.buffer._clear_buffers()
        self.buffer._clear_group_buffers()

    # ==================== 回调属性（转发到连接层，保持旧接口可注入） ====================
    @property
    def on_private_message(self):
        return self.connection.on_private_message

    @on_private_message.setter
    def on_private_message(self, value):
        self.connection.on_private_message = value

    @property
    def on_group_message(self):
        return self.connection.on_group_message

    @on_group_message.setter
    def on_group_message(self, value):
        self.connection.on_group_message = value

    @property
    def on_poke(self):
        return self.connection.on_poke

    @on_poke.setter
    def on_poke(self, value):
        self.connection.on_poke = value

    # ==================== 生命周期 ====================
    def start(self):
        """启动后台线程（未启用则直接返回）"""
        self.connection.start()

    def stop(self):
        """停止后台线程"""
        self.connection.stop()

    # ==================== 发送 API ====================
    def send_private_text(self, user_id, text: str):
        self.api_client.send_private_text(user_id, text)

    def send_private_image(self, user_id, file_path: str):
        self.api_client.send_private_image(user_id, file_path)

    def send_group_text(self, group_id, text: str):
        self.api_client.send_group_text(group_id, text)

    def send_group_image(self, group_id, file_path: str):
        self.api_client.send_group_image(group_id, file_path)

    def send_group_file(self, group_id, file_path: str):
        self.api_client.send_group_file(group_id, file_path)

    def send_private_voice(self, user_id, file_path: str):
        self.api_client.send_private_voice(user_id, file_path)

    def send_group_voice(self, group_id, file_path: str):
        self.api_client.send_group_voice(group_id, file_path)

    def call_action_sync(self, action: str, params: dict, timeout: float = 5.0):
        return self.api_client.call_action_sync(action, params, timeout)

    # ==================== 群聊 @ 缓冲协调 ====================
    def group_buffer_exists(self, group_id, user_id) -> bool:
        return self.buffer.group_buffer_exists(group_id, user_id)

    def buffer_group_at(self, parsed: dict) -> dict:
        return self.buffer.buffer_group_at(parsed)

    def add_group_buffer_text(self, parsed: dict):
        self.buffer.add_group_buffer_text(parsed)

    def take_group_buffer(self, group_id, user_id) -> dict:
        return self.buffer.take_group_buffer(group_id, user_id)
