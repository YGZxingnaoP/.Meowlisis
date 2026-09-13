# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/sender.py
# 主动发送框架：发送文本/链接/图片/文件/聊天记录，D盘搜索文件，校验链接，供 AI 调用

import os
import re
import time
import urllib.request
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.toolbox.napcat.active_sender.get_friendlist import TBGetFriendList
from func.toolbox.napcat.active_sender.get_grouplist import TBGetGroupList


class TBSender:
    """主动发送工具：提供 tool schema 与发送/搜索/校验实现（受 toolcalls 控制）"""

    # D 盘文件搜索限制
    SEARCH_ROOT = "D:\\"
    SEARCH_MAX_RESULTS = 30
    SEARCH_MAX_SECONDS = 6

    # 主动发送冷却时间戳（类变量，所有实例共享，运行时内存态，不落盘）
    _last_active_send = 0.0

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.get_friendlist = TBGetFriendList()
        self.get_grouplist = TBGetGroupList()

    # ==================== 主动发送开关与冷却 ====================
    def check_active_send(self) -> str:
        """检查主动发送是否允许（开关 + 冷却），返回错误信息（空串表示允许）"""
        from func.toolbox.napcat.config import TBNapCatConfig
        cfg = TBNapCatConfig()
        if not cfg.active_send_enabled:
            return "主动发送未启用（active_sender.enabled=false）"
        cooldown = int(cfg.active_send_cooldown or 0)
        if cooldown > 0:
            elapsed = time.time() - TBSender._last_active_send
            if elapsed < cooldown:
                return f"主动发送冷却中，还需 {int(cooldown - elapsed)} 秒"
        return ""

    @classmethod
    def mark_active_send(cls):
        """记录本次主动发送时间（用于冷却）"""
        cls._last_active_send = time.time()

    # ==================== tool schema ====================
    def build_tools(self) -> List[Dict]:
        """返回主动发送工具 schema（供父级 toolcalls 展开注册）"""
        target_type = {"type": "string", "enum": ["friend", "group"],
                       "description": "目标类型：friend 好友 / group 群聊"}
        return [
            {
                "type": "function",
                "function": {
                    "name": "send_qq_message",
                    "description": "通过 QQ 给指定好友或群聊主动发送文本消息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_type": target_type,
                            "target_id": {"type": "string", "description": "目标 QQ 号或群号"},
                            "text": {"type": "string", "description": "要发送的文本内容"},
                        },
                        "required": ["target_type", "target_id", "text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_qq_link",
                    "description": "通过 QQ 给指定好友或群聊发送链接",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_type": target_type,
                            "target_id": {"type": "string", "description": "目标 QQ 号或群号"},
                            "url": {"type": "string", "description": "要发送的链接 URL"},
                            "desc": {"type": "string", "description": "链接说明（可空）"},
                        },
                        "required": ["target_type", "target_id", "url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_qq_image",
                    "description": "通过 QQ 给指定好友或群聊发送本地图片",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_type": target_type,
                            "target_id": {"type": "string", "description": "目标 QQ 号或群号"},
                            "file_path": {"type": "string", "description": "本地图片绝对路径"},
                        },
                        "required": ["target_type", "target_id", "file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_qq_file",
                    "description": "通过 QQ 给指定好友或群聊发送文件",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_type": target_type,
                            "target_id": {"type": "string", "description": "目标 QQ 号或群号"},
                            "file_path": {"type": "string", "description": "本地文件绝对路径"},
                        },
                        "required": ["target_type", "target_id", "file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_qq_chat_record",
                    "description": "通过 QQ 给指定好友或群聊发送聊天记录文本（格式化文本，非合并转发卡片）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_type": target_type,
                            "target_id": {"type": "string", "description": "目标 QQ 号或群号"},
                            "record_text": {"type": "string", "description": "聊天记录文本内容"},
                        },
                        "required": ["target_type", "target_id", "record_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_file",
                    "description": "在整个 D 盘按文件名关键词搜索目标文件，返回匹配的绝对路径列表",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string", "description": "文件名关键词"},
                        },
                        "required": ["keyword"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_link",
                    "description": "校验链接是否可访问（是否 404 等），返回状态码与是否可用",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "要校验的链接 URL"},
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_friend_list",
                    "description": "获取 QQ 好友列表，用于选择发送目标用户",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_group_list",
                    "description": "获取 QQ 群聊列表，用于选择发送目标群",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    # ==================== 执行分发 ====================
    def dispatch(self, name: str, arguments: Dict) -> str:
        """按工具名执行主动发送/搜索/校验"""
        if name == "send_qq_message":
            return self.send_text(arguments.get("target_type"), arguments.get("target_id"),
                                  arguments.get("text", ""))
        if name == "send_qq_link":
            return self.send_link(arguments.get("target_type"), arguments.get("target_id"),
                                  arguments.get("url", ""), arguments.get("desc", ""))
        if name == "send_qq_image":
            return self.send_image(arguments.get("target_type"), arguments.get("target_id"),
                                   arguments.get("file_path", ""))
        if name == "send_qq_file":
            return self.send_file(arguments.get("target_type"), arguments.get("target_id"),
                                  arguments.get("file_path", ""))
        if name == "send_qq_chat_record":
            return self.send_text(arguments.get("target_type"), arguments.get("target_id"),
                                  arguments.get("record_text", ""))
        if name == "search_file":
            return self.search_file(arguments.get("keyword", ""))
        if name == "check_link":
            return self.check_link(arguments.get("url", ""))
        if name == "get_friend_list":
            return self.list_friends()
        if name == "get_group_list":
            return self.list_groups()
        return f"错误：未知工具 {name}"

    # ==================== 列表获取 ====================
    def list_friends(self) -> str:
        friends = self.get_friendlist.get()
        if not friends:
            return "未获取到好友列表（可能未登录或连接异常）"
        lines = [f"{f.get('nickname') or ''}({f.get('remark') or ''}): {f.get('user_id')}" for f in friends]
        return "好友列表：\n" + "\n".join(lines)

    def list_groups(self) -> str:
        groups = self.get_grouplist.get()
        if not groups:
            return "未获取到群聊列表（可能未登录或连接异常）"
        lines = [f"{g.get('group_name') or ''}: {g.get('group_id')}" for g in groups]
        return "群聊列表：\n" + "\n".join(lines)

    # ==================== 基础发送 ====================
    def _action_and_key(self, target_type: str):
        return ("send_group_msg", "group_id") if target_type == "group" else ("send_private_msg", "user_id")

    def _group_target(self, target_type, target_id):
        """群目标解析：群号(纯数字)直通；群名按在线群列表解析。返回 (id, err)。"""
        if str(target_type or "") != "group":
            return str(target_id or "").strip(), ""
        raw = str(target_id or "").strip().strip("\"'")
        if not raw:
            return None, "目标群为空"
        if re.fullmatch(r"\d+", raw):
            return raw, ""
        try:
            from func.toolbox.napcat.active_sender.get_grouplist import TBGetGroupList
            return TBGetGroupList().resolve_id(raw)
        except Exception as e:
            return None, f"解析群名失败: {e}"

    @staticmethod
    def _project_root() -> str:
        """项目根目录（本文件上溯：文件→active_sender→napcat→toolbox→func→根，共5级）"""
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))))

    def _resolve_existing_path(self, raw: str) -> str:
        """本地文件路径智能解析：LLM 拼接路径常出错（隐藏目录 .Meowlisis 前缀丢失、
        凭空加 .image.png 尾巴、盘符/斜杠变形等）。依次尝试多种候选，返回首个真实存在的
        文件绝对路径；全部失败返回空串。"""
        raw = (raw or "").strip().strip("\"'")
        if not raw:
            return ""
        root = self._project_root()
        candidates = []

        def _add(p):
            if p:
                p = os.path.normpath(p)
                if p not in candidates:
                    candidates.append(p)

        _add(raw)
        _add(raw.replace("\\", "/"))
        _add(raw.replace("/", "\\"))

        base = os.path.basename(raw.replace("\\", "/"))
        # ① 隐藏目录前缀丢失：任意盘符的 Meowlisis / .Meowlisis → 项目根（不再写死 D 盘）
        m = re.match(r"^([A-Za-z]):[\\/]+\.?Meowlisis[\\/]+(.*)$", raw)
        if m:
            _add(os.path.join(root, m.group(2)))
        # ② LLM 常给存档名凭空加 .image(.png) 尾巴（真实存档无扩展名）
        no_ext = re.sub(r"\.image(\.(png|jpg|jpeg|webp|gif|bmp))?$", "", base, flags=re.IGNORECASE)
        if no_ext and no_ext != base:
            for cand in list(candidates):
                _add(os.path.join(os.path.dirname(cand), no_ext))
        # ③ 相对/裸文件名 → 挂到项目根
        if not re.match(r"^[A-Za-z]:[\\/]", raw):
            _add(os.path.join(root, raw.replace("\\", "/")))
        _add(os.path.join(root, base))
        if no_ext and no_ext != base:
            _add(os.path.join(root, no_ext))
        # ④ 兜底：按时间戳在画作存档目录(character/paints)前缀匹配（LLM 文件名常带错后缀/缺目录）。
        #    存档结构可能为 会话目录(内含 image.png/meta.json) 或 单文件；目录命中则取其内部图片。
        ts = re.search(r"(\d{8}-\d{6})", raw.replace("\\", "/"))
        if ts:
            prefix = ts.group(1)
            img_names = ("image.png", "image.jpg", "image.jpeg")
            for dirname_ in ("character/paints", "character", ".temp/flux_paint"):
                d = os.path.join(root, dirname_)
                if not os.path.isdir(d):
                    continue
                try:
                    names = os.listdir(d)
                except Exception:
                    continue
                for fn in names:
                    if not fn.startswith(prefix):
                        continue
                    sub = os.path.join(d, fn)
                    if os.path.isdir(sub):
                        # 会话目录：取其内部主图
                        try:
                            for inner in os.listdir(sub):
                                ip = os.path.join(sub, inner)
                                if inner.lower() in img_names or inner.lower().endswith(
                                        (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                                    _add(ip)
                        except Exception:
                            pass
                    elif os.path.isfile(sub):
                        _add(sub)
        # 返回首个存在
        for cand in candidates:
            try:
                if os.path.isfile(cand):
                    return cand
            except Exception:
                continue
        return ""

    def send_text(self, target_type: str, target_id, text: str) -> str:
        if not text or not target_id:
            return "发送失败：缺少目标或内容"
        gid, err = self._group_target(target_type, target_id)
        if not gid:
            return f"发送失败：{err}"
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            action, key = self._action_and_key(target_type)
            TBNapCatCore().call_action_sync(action, {
                key: int(gid),
                "message": [{"type": "text", "data": {"text": text}}],
            })
            return f"已发送：{text[:30]}"
        except Exception:
            self.log.exception("主动发送文本失败")
            return "发送失败"

    def send_group_at(self, group_id, at_qq, text: str = "") -> str:
        """主动 @ 群成员发送（at_qq 为目标 QQ 号，text 为空时仅 @）"""
        if not group_id or not at_qq:
            return "发送失败：缺少群号或 @ 目标"
        gid, err = self._group_target("group", group_id)
        if not gid:
            return f"发送失败：{err}"
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            TBNapCatCore().send_group_at_text(gid, at_qq, text)
            return f"已 @ 发送：{text[:30] if text else '(仅@)'}"
        except Exception:
            self.log.exception("主动 @ 发送失败")
            return "发送失败"

    def send_link(self, target_type: str, target_id, url: str, desc: str = "") -> str:
        if not url or not target_id:
            return "发送失败：缺少目标或链接"
        text = f"{desc}: {url}" if desc else url
        return self.send_text(target_type, target_id, text)

    def send_image(self, target_type: str, target_id, file_path: str) -> str:
        if not file_path or not target_id:
            return "发送失败：缺少目标或图片路径"
        gid, err = self._group_target(target_type, target_id)
        if not gid:
            return f"发送失败：{err}"
        path = self._resolve_existing_path(file_path)
        if not path:
            return f"发送失败：文件不存在（已尝试多种路径解析仍找不到）{file_path}"
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            core = TBNapCatCore()
            action, key = self._action_and_key(target_type)
            core.call_action_sync(action, {
                key: int(gid),
                "message": [{"type": "image",
                             "data": {"file": core.api_client._to_file_uri(path)}}],
            })
            return f"已发送图片：{path}"
        except Exception:
            self.log.exception("主动发送图片失败")
            return "发送失败"

    def send_file(self, target_type: str, target_id, file_path: str) -> str:
        """发送文件：私聊走 NapCat upload_private_file（QQ 私聊不支持 file 段消息），
        群聊走 upload_group_file（比 file 段消息更稳定，直接入群文件）。"""
        if not file_path or not target_id:
            return "发送失败：缺少目标或文件路径"
        gid, err = self._group_target(target_type, target_id)
        if not gid:
            return f"发送失败：{err}"
        path = self._resolve_existing_path(file_path)
        if not path:
            return f"发送失败：文件不存在（已尝试多种路径解析仍找不到）{file_path}"
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            core = TBNapCatCore()
            name = os.path.basename(path)
            if str(target_type) == "group":
                core.call_action_sync("upload_group_file", {
                    "group_id": int(gid), "file": path, "name": name})
            else:
                core.call_action_sync("upload_private_file", {
                    "user_id": int(gid), "file": path, "name": name})
            return f"已发送文件：{path}"
        except Exception:
            self.log.exception("主动发送文件失败")
            return "发送失败"

    # ==================== D 盘搜索与链接校验 ====================
    def search_file(self, keyword: str) -> str:
        """在 D 盘按关键词搜索文件，返回匹配路径列表"""
        keyword = (keyword or "").strip().lower()
        if not keyword:
            return "搜索失败：缺少关键词"
        root = self.SEARCH_ROOT
        if not os.path.isdir(root):
            return f"搜索失败：根目录不存在 {root}"
        results = []
        start = time.time()
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                if time.time() - start > self.SEARCH_MAX_SECONDS:
                    break
                # 跳过明显系统/隐藏目录，加快搜索
                dirnames[:] = [d for d in dirnames if not d.startswith(("$", "System Volume Information", "WindowsApps"))]
                for fn in filenames:
                    if keyword in fn.lower():
                        results.append(os.path.join(dirpath, fn))
                        if len(results) >= self.SEARCH_MAX_RESULTS:
                            return "搜索到以下文件：\n" + "\n".join(results)
        except Exception:
            self.log.exception("D盘搜索文件失败")
            return "搜索文件失败"
        if not results:
            return f"未在 D 盘搜索到包含关键词「{keyword}」的文件"
        return "搜索到以下文件：\n" + "\n".join(results)

    def check_link(self, url: str) -> str:
        """校验链接是否可访问（是否 404）"""
        url = (url or "").strip()
        if not url:
            return "校验失败：缺少链接"
        if not url.lower().startswith(("http://", "https://")):
            return f"校验失败：无效链接 {url}"
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            try:
                resp = urllib.request.urlopen(req, timeout=8)
                code = resp.getcode()
            except Exception:
                # HEAD 失败回退 GET
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=8)
                code = resp.getcode()
            if code == 404:
                return f"链接不可用（404）：{url}"
            return f"链接可用（状态码 {code}）：{url}"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return f"链接不可用（404）：{url}"
            return f"链接返回状态码 {e.code}：{url}"
        except Exception as e:
            self.log.warning(f"链接校验失败: {url} {e}")
            return f"链接校验失败：{url}（{e}）"
