import json

import requests

from cw.geometry import CWScreen
from cw.protocol import CWErrorCode, CWProtocolError

CW_DEVICE_ERRORS = {
    401: CWErrorCode.UNAUTHORIZED,
    404: CWErrorCode.NOT_FOUND,
}


class CWDeviceError(CWProtocolError):
    pass


class CWDeviceClient:
    is_mock = False

    def __init__(self, host, port, token="", timeout=8.0):
        self.host = host
        self.port = int(port)
        self.base = "http://%s:%d/cw/v1" % (host, self.port)
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
        self.headers = {"Accept": "application/json"}
        if token:
            self.headers["Authorization"] = "Bearer %s" % token
        self._screen = None
        self._info = {}

    def _url(self, path):
        return self.base + path

    def _request(self, method, path, params=None, payload=None, raw=False):
        try:
            response = self.session.request(method, self._url(path), params=params, json=payload,
                                            headers=self.headers, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise CWDeviceError(CWErrorCode.TIMEOUT, "设备响应超时")
        except requests.exceptions.RequestException as exc:
            raise CWDeviceError(CWErrorCode.UNAVAILABLE, "设备不可达：%s" % exc)
        if raw:
            if response.status_code != 200:
                code = CW_DEVICE_ERRORS.get(response.status_code, CWErrorCode.INTERNAL)
                raise CWDeviceError(code, "截图失败 HTTP %s" % response.status_code)
            return response
        if response.status_code != 200:
            code = CW_DEVICE_ERRORS.get(response.status_code, CWErrorCode.INTERNAL)
            raise CWDeviceError(code, "设备返回 HTTP %s" % response.status_code)
        try:
            body = response.json()
        except json.JSONDecodeError:
            raise CWDeviceError(CWErrorCode.INTERNAL, "设备返回非 JSON")
        if not isinstance(body, dict):
            raise CWDeviceError(CWErrorCode.INTERNAL, "设备返回格式错误")
        if not body.get("ok", False):
            raise CWDeviceError(body.get("code") or CWErrorCode.INTERNAL,
                                body.get("message") or "设备操作失败",
                                body.get("data") or {})
        return body.get("data") or {}

    def ping(self):
        return self._request("GET", "/ping")

    def device_info(self, refresh=False):
        if refresh or not self._info:
            self._info = self._request("GET", "/device")
            self._screen = CWScreen.from_device(self._info)
        return self._info

    def screen(self, refresh=False):
        if refresh or self._screen is None:
            self.device_info(refresh=refresh)
        return self._screen

    def capabilities(self):
        info = self.device_info()
        return list(info.get("capabilities") or [])

    def ensure_session(self):
        info = self.ping()
        if info.get("session"):
            return True
        self._request("POST", "/session", payload={})
        return True

    def drop_session(self):
        try:
            self._request("DELETE", "/session")
        except CWDeviceError:
            return False
        return True

    def run_steps(self, steps, delay_ms=None):
        payload = {"steps": list(steps)}
        if delay_ms is not None:
            payload["delay_ms"] = int(delay_ms)
        return self._request("POST", "/actions", payload=payload)

    def stop(self):
        return self._request("POST", "/stop", payload={})

    def screenshot(self, max_edge=None, fmt="png", quality=None):
        params = {"format": fmt}
        if max_edge:
            params["max_edge"] = int(max_edge)
        if quality:
            params["quality"] = int(quality)
        response = self._request("GET", "/screenshot", params=params, raw=True)
        return response.content

    def ocr(self, region=None):
        payload = {}
        if region:
            payload["region"] = list(region)
        return self._request("POST", "/ocr", payload=payload)

    def paste(self, text, submit=False):
        return self._request("POST", "/paste", payload={"text": text, "submit": bool(submit)})

    def source(self):
        return self._request("GET", "/source")

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass
