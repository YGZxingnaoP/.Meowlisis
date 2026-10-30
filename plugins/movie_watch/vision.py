# -*- coding: utf-8 -*-
"""视觉端口：看一帧画面，返回 {scene, comment}。

完全自包含，不 import 主项目任何代码：
- 视觉来源 `meowvision`（默认）：直接读主程序 config.yml 的 meowvision 节点（只取 key/模型等数据）；
- 视觉来源 `custom`：用插件自己的平台/key/模型配置。
"""

import base64
import json
import mimetypes
import re

import yaml

from .prompts import RECORD_TOOL, RECORD_TOOL_NAME

PRESETS = {
    "aliyun": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-vl-max"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-flash"),
}

# 兜底解析用的行首标记：(标记, 是否属于画面)
LINE_MARKS = (("画面", True), ("场景", True), ("感想", False),
              ("吐槽", False), ("评价", False), ("想法", False))


def read_project_config(path):
    """按 YAML 读主程序配置（只读数据，不引用其代码）"""
    try:
        with open(str(path), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class MovieVision:
    """视觉观察器：每次 observe 只描述一张画面，失败返回 None。"""

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.mode = "none"          # aliyun / gemini / openai / deepseek / none
        self.detail = ""
        self._client = None
        self._model = ""
        self._extra_body = None
        self._init()

    # ==================== 初始化 ====================
    def _init(self):
        source = self._resolve()
        if not source:
            return
        self.mode = source["mode"]
        self._model = source["model"]
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=source["api_key"], base_url=source["base_url"])
        except Exception as e:
            self.mode = "none"
            self.detail = f"客户端初始化失败：{e}"
            return
        if self.mode == "aliyun":
            self._extra_body = {"enable_thinking": bool(self.config.vision_thinking)}
        self.detail = f"{self.mode}（{self._model}）"
        if self.mode == "aliyun" and self.config.vision_thinking:
            self.detail += " +思考"

    def _resolve(self):
        """解析接口来源：插件独立配置优先，否则读主程序 meowvision 节点"""
        if self.config.vision_source == "custom":
            provider = self.config.vision_provider
            api_key = self.config.vision_api_key
            if not api_key:
                self.detail = "未配置 vision.api_key"
                return None
            base, model = PRESETS.get(provider, PRESETS["aliyun"])
            return {"mode": provider,
                    "api_key": api_key,
                    "base_url": self.config.vision_base_url or base,
                    "model": self.config.vision_model or model}

        node = read_project_config(self.config.project_config).get("meowvision") or {}
        if not isinstance(node, dict):
            node = {}
        llm_type = str(node.get("llm_type") or "aliyun").lower()
        if llm_type == "gemini":
            gem = node.get("gemini") if isinstance(node.get("gemini"), dict) else {}
            key = str(gem.get("api_key") or "")
            if not key:
                self.detail = "主程序 meowvision.gemini.api_key 未配置"
                return None
            return {"mode": "gemini", "api_key": key,
                    "base_url": str(gem.get("base_url") or PRESETS["gemini"][0]),
                    "model": str(gem.get("model") or PRESETS["gemini"][1])}
        key = str(node.get("api_key") or "")
        if not key:
            self.detail = "主程序 meowvision.api_key 未配置"
            return None
        return {"mode": "aliyun", "api_key": key,
                "base_url": str(node.get("base_url") or PRESETS["aliyun"][0]),
                "model": str(node.get("model") or PRESETS["aliyun"][1])}

    def available(self):
        return self.mode != "none"

    # ==================== 观察 ====================
    def observe(self, image_path, system_prompt, user_prompt):
        """看一张画面，返回 {"scene": str, "comment": str}；失败返回 None"""
        if not self.available() or not image_path:
            return None
        try:
            resp = self._request(image_path, system_prompt, user_prompt)
        except Exception:
            self.log.exception("[movie_watch] 视觉调用异常")
            return None
        result = self._parse(resp)
        if not result or not (result.get("scene") or result.get("comment")):
            self.log.warning("[movie_watch] 视觉返回无法解析")
            return None
        return result

    def _request(self, image_path, system_prompt, user_prompt, retry=True):
        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        with open(image_path, "rb") as f:
            payload = base64.b64encode(f.read()).decode("utf-8")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{payload}"}},
            {"type": "text", "text": user_prompt},
        ]})
        params = {
            "model": self._model,
            "messages": messages,
            "temperature": self.config.vision_temperature,
            "max_tokens": self.config.vision_max_tokens,
            "tools": RECORD_TOOL,
        }
        if self._extra_body:
            params["extra_body"] = self._extra_body
        try:
            return self._client.chat.completions.create(**params)
        except Exception:
            if not retry or not self._extra_body:
                raise
            # 网关不认 enable_thinking：去掉重试一次，之后本场都不再带
            self.log.warning("[movie_watch] 视觉接口不接受 enable_thinking，已去掉该参数重试")
            self._extra_body = None
            return self._request(image_path, system_prompt, user_prompt, retry=False)

    # ==================== 解析 ====================
    @classmethod
    def _parse(cls, resp):
        if not resp or not getattr(resp, "choices", None):
            return None
        message = resp.choices[0].message
        for call in (getattr(message, "tool_calls", None) or []):
            try:
                if call.function.name != RECORD_TOOL_NAME:
                    continue
                args = json.loads(call.function.arguments or "{}")
            except Exception:
                continue
            scene = cls._clean(args.get("scene", ""))
            comment = cls._clean(args.get("comment", ""))
            if scene or comment:
                return {"scene": scene, "comment": comment}
        return cls._split(str(getattr(message, "content", "") or ""))

    @classmethod
    def _split(cls, text):
        """兜底解析：优先按「画面：/ 感想：」行首标记，其次多行取首行为画面。"""
        text = cls._strip_think(str(text or "")).strip()
        if not text:
            return None
        scene = ""
        comment = ""
        plain = []
        for raw in text.splitlines():
            line = raw.strip().lstrip("-*· ").strip()
            if not line:
                continue
            hit = False
            for mark, is_scene in LINE_MARKS:
                for sep in ("：", ":"):
                    prefix = mark + sep
                    if line.startswith(prefix):
                        value = line[len(prefix):].strip()
                        if is_scene:
                            scene = value
                        else:
                            comment = value
                        hit = True
                        break
                if hit:
                    break
            if not hit:
                plain.append(line)
        if plain:
            if scene or comment:
                comment = " ".join([comment] + plain).strip()
            elif len(plain) >= 2:
                scene = plain[0]
                comment = " ".join(plain[1:])
            else:
                comment = plain[0]
        if not scene and not comment:
            comment = text
        return {"scene": cls._clean(scene), "comment": cls._clean(comment)}

    @staticmethod
    def _strip_think(text):
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
        return text

    @classmethod
    def _clean(cls, text):
        text = cls._strip_think(str(text or ""))
        text = re.sub(r"【[^】]*】", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
