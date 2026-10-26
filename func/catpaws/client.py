import requests

from func.catpaws.config import CWCatPawsConfig


class CWCatPawsClient:
    def __init__(self, config=None):
        self.config = config or CWCatPawsConfig()

    def _request(self, method, path, payload=None):
        url = self.config.base_url() + path
        try:
            response = requests.request(method, url, json=payload, headers=self.config.headers(),
                                        timeout=self.config.timeout)
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "code": "E_UNAVAILABLE", "message": str(exc)}
        try:
            body = response.json()
        except ValueError:
            return {"ok": False, "code": "E_BAD_RESPONSE", "message": response.text[:200]}
        if not isinstance(body, dict):
            return {"ok": False, "code": "E_BAD_RESPONSE", "message": "返回格式错误"}
        return body

    def health(self):
        return self._request("GET", "/cw/config")

    def status(self):
        return self._request("GET", "/cw/status")

    def start(self, goal):
        return self._request("POST", "/cw/start", {"goal": goal})

    def stop(self, reason="user"):
        return self._request("POST", "/cw/stop", {"reason": reason})

    def answer(self, text):
        return self._request("POST", "/cw/answer", {"text": text})

    def ops(self, limit=120):
        return self._request("GET", "/cw/ops?limit=%d" % int(limit))

    def shot(self, max_edge=720):
        url = self.config.base_url() + "/cw/screenshot?max_edge=%d" % int(max_edge)
        try:
            response = requests.get(url, timeout=self.config.timeout)
        except requests.exceptions.RequestException as exc:
            return None, str(exc)
        if response.status_code != 200:
            return None, "HTTP %s" % response.status_code
        return response.content, ""
