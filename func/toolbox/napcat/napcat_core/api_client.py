# -*- coding: utf-8 -*-
# func/toolbox/napcat/napcat_core/api_client.py
# NapCat 发送 API 封装：send_* / call_action_sync / _to_file_uri

import asyncio


class TBNapCatApiClient:
    """NapCat 发送层：把文本/图片/文件/语音封装为 OneBot action 提交到事件循环。

    依赖 TBNapCatConnection 提供 loop / ws / echo / pending 等底层能力。
    """

    def __init__(self, log, config, connection):
        self.log = log
        self.config = config
        self.conn = connection

    # ==================== 发送 API ====================
    def send_private_text(self, user_id, text: str):
        """发送私聊文本（线程安全，异步发送并记录结果）"""
        if not text or not self.conn.enabled:
            return
        if not self.conn._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过发送")
            return
        self.log.info(f"[NapCat] 发送文本 → {user_id}: {text[:40]}")
        self._submit_send("send_private_msg", {
            "user_id": int(user_id),
            "message": [{"type": "text", "data": {"text": text}}],
        }, "文本")

    def send_private_image(self, user_id, file_path: str):
        """发送私聊图片（用于 gif 表情，线程安全）"""
        if not file_path or not self.conn.enabled:
            return
        if not self.conn._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过发送")
            return
        self.log.info(f"[NapCat] 发送图片 → {user_id}: {file_path}")
        self._submit_send("send_private_msg", {
            "user_id": int(user_id),
            "message": [{"type": "image", "data": {"file": self._to_file_uri(file_path)}}],
        }, "图片")

    def send_group_text(self, group_id, text: str):
        """发送群聊文本（线程安全，异步发送）"""
        if not text or not self.conn.enabled:
            return
        if not self.conn._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过群发送")
            return
        self.log.info(f"[NapCat] 发送群文本 → {group_id}: {text[:40]}")
        self._submit_send("send_group_msg", {
            "group_id": int(group_id),
            "message": [{"type": "text", "data": {"text": text}}],
        }, "群文本")

    def send_group_at_text(self, group_id, at_qq, text: str):
        """发送群聊 @ 某人文本（构造独立 at 段，线程安全）

        at_qq 为目标 QQ 号；text 为空时仅 @ 不附带文字。
        """
        if not self.conn.enabled:
            return
        if not self.conn._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过群@发送")
            return
        message = [{"type": "at", "data": {"qq": str(at_qq)}}]
        if text:
            # @ 与文字之间留一个空格，避免客户端显示粘连
            message.append({"type": "text", "data": {"text": " " + text}})
        self.log.info(f"[NapCat] 发送群@文本 → {group_id} @{at_qq}: {(text or '')[:40]}")
        self._submit_send("send_group_msg", {
            "group_id": int(group_id),
            "message": message,
        }, "群@文本")

    def send_group_image(self, group_id, file_path: str):
        """发送群聊图片（线程安全）"""
        if not file_path or not self.conn.enabled:
            return
        if not self.conn._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过群图片发送")
            return
        self.log.info(f"[NapCat] 发送群图片 → {group_id}: {file_path}")
        self._submit_send("send_group_msg", {
            "group_id": int(group_id),
            "message": [{"type": "image", "data": {"file": self._to_file_uri(file_path)}}],
        }, "群图片")

    def send_group_file(self, group_id, file_path: str):
        """发送群聊文件（线程安全）"""
        if not file_path or not self.conn.enabled:
            return
        if not self.conn._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过群文件发送")
            return
        self.log.info(f"[NapCat] 发送群文件 → {group_id}: {file_path}")
        self._submit_send("send_group_msg", {
            "group_id": int(group_id),
            "message": [{"type": "file", "data": {"file": file_path}}],
        }, "群文件")

    def send_private_voice(self, user_id, file_path: str):
        """发送私聊语音（record 段，线程安全）"""
        if not file_path or not self.conn.enabled:
            return
        if not self.conn._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过私聊语音发送")
            return
        self.log.info(f"[NapCat] 发送私聊语音 → {user_id}: {file_path}")
        self._submit_send("send_private_msg", {
            "user_id": int(user_id),
            "message": [{"type": "record", "data": {"file": self._to_file_uri(file_path)}}],
        }, "私聊语音")

    def send_group_voice(self, group_id, file_path: str):
        """发送群聊语音（record 段，线程安全）"""
        if not file_path or not self.conn.enabled:
            return
        if not self.conn._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过群语音发送")
            return
        self.log.info(f"[NapCat] 发送群语音 → {group_id}: {file_path}")
        self._submit_send("send_group_msg", {
            "group_id": int(group_id),
            "message": [{"type": "record", "data": {"file": self._to_file_uri(file_path)}}],
        }, "群语音")

    # ==================== 发送基础设施 ====================
    def _submit_send(self, action: str, params: dict, label: str):
        """提交发送协程到事件循环，异常与结果在协程内部记录（避免静默吞掉）"""
        try:
            asyncio.run_coroutine_threadsafe(
                self._send_and_log(action, params, label), self.conn.loop
            )
        except Exception:
            self.log.exception(f"提交发送{label}失败")

    async def _send_and_log(self, action: str, params: dict, label: str):
        """发送 OneBot action 并等待响应，记录成功/失败与 retcode"""
        try:
            echo = self.conn._next_echo()
            resp = await self.conn._call_action(echo, action, params)
        except Exception as e:
            self.log.exception(f"[NapCat] 发送{label}异常: {e}")
            return
        if resp is None:
            self.log.warning(f"[NapCat] 发送{label}无响应（超时或连接已断开）")
            return
        retcode = resp.get("retcode")
        if retcode not in (0, "0", None):
            msg = resp.get("msg") or resp.get("wording") or resp.get("message") or str(resp)
            self.log.error(f"[NapCat] 发送{label}失败: retcode={retcode}, {msg}")
        else:
            mid = (resp.get("data") or {}).get("message_id", "")
            self.log.info(f"[NapCat] 发送{label}成功 message_id={mid}")

    def call_action_sync(self, action: str, params: dict, timeout: float = 5.0):
        """同步调用 OneBot API（供 get_friendlist 等主动获取用）"""
        if not self.conn.enabled:
            return None
        if not self.conn._wait_loop_ready(timeout=timeout):
            self.log.warning(f"NapCat 事件循环未就绪，调用失败: {action}")
            return None
        echo = self.conn._next_echo()
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self.conn._call_action(echo, action, params), self.conn.loop
            )
            return fut.result(timeout=timeout)
        except Exception:
            self.log.exception(f"调用 NapCat API 失败: {action}")
            return None

    @staticmethod
    def _to_file_uri(file_path: str) -> str:
        """本地文件路径转 file URI（供 NapCat image 段发送）

        绝对路径和相对路径都转成 file:/// 绝对路径，避免 NapCat 无法识别相对路径。
        """
        import pathlib
        if "://" in file_path or file_path.startswith("data:"):
            return file_path
        path = pathlib.Path(file_path)
        if not path.is_absolute():
            path = path.resolve()
        return path.as_uri()
