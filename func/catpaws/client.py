# -*- coding: utf-8 -*-
# func/catpaws/client.py
# catpaws 服务端 HTTP 客户端：.vendor/.CatPaws/src/cw/server.py 的接口封装
import requests

from func.catpaws.config import CWCatPawsConfig
from func.log.default_log import DefaultLog


class CWCatPawsClient:
    """与 CatPaws 服务端通信（状态/启动/停止/回答/回复流/操作记录）"""

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = config or CWCatPawsConfig()

    def _request(self, method, path, payload=None, timeout=None):
        url = self.config.base_url() + path
        try:
            response = requests.request(method, url, json=payload, headers=self.config.headers(),
                                        timeout=timeout or self.config.timeout)
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "code": "E_UNAVAILABLE", "message": str(exc)}
        try:
            body = response.json()
        except ValueError:
            return {"ok": False, "code": "E_BAD_RESPONSE", "message": response.text[:200]}
        if not isinstance(body, dict):
            return {"ok": False, "code": "E_BAD_RESPONSE", "message": "返回格式错误"}
        return body

    def status(self):
        return self._request("GET", "/cw/status")

    def health(self):
        return self._request("GET", "/cw/config")

    def start(self, payload):
        return self._request("POST", "/cw/start", payload)

    def stop(self, reason="user"):
        return self._request("POST", "/cw/stop", {"reason": reason})

    def answer(self, text):
        return self._request("POST", "/cw/answer", {"text": text})

    def replies(self, since=0, limit=200):
        return self._request("GET", "/cw/replies?since=%d&limit=%d" % (int(since), int(limit)))

    def ops(self, limit=200):
        return self._request("GET", "/cw/ops?limit=%d" % int(limit))

    def stream(self, on):
        return self._request("POST", "/cw/stream", {"on": bool(on)})

    def screenshot(self, max_edge=720):
        url = self.config.base_url() + "/cw/screenshot?max_edge=%d" % int(max_edge)
        try:
            response = requests.get(url, timeout=self.config.timeout)
        except requests.exceptions.RequestException as exc:
            return None, str(exc)
        if response.status_code != 200:
            return None, "HTTP %s" % response.status_code
        return response.content, ""
