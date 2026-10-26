import requests


class CWWDAError(Exception):
    pass


class CWWDA:
    CHAINS = ("**/XCUIElementTypeTextView", "**/XCUIElementTypeTextField",
              "**/XCUIElementTypeSearchField")

    def __init__(self, config):
        self.base = "http://%s:%d" % (config.device_ip, config.device_port)
        self.timeout = max(8.0, float(config.device_timeout))
        self._sid = ""

    def _session(self):
        if self._sid:
            return self._sid
        try:
            data = requests.get(self.base + "/status", timeout=self.timeout).json()
        except Exception as exc:
            raise CWWDAError("取不到 WDA 会话：%s" % exc)
        sid = str(data.get("sessionId") or "")
        if not sid:
            raise CWWDAError("WDA 没有返回 sessionId")
        self._sid = sid
        return sid

    def _ids(self, chain):
        sid = self._session()
        try:
            response = requests.post("%s/session/%s/elements" % (self.base, sid),
                                     json={"using": "class chain", "value": chain},
                                     timeout=self.timeout)
        except Exception as exc:
            raise CWWDAError("查询控件失败：%s" % exc)
        if response.status_code != 200:
            return []
        try:
            items = response.json().get("value") or []
        except ValueError:
            return []
        ids = []
        for item in items:
            if not isinstance(item, dict):
                continue
            element_id = item.get("ELEMENT") or item.get("element-6066-11e4-a52e-4f735466cecf")
            if element_id:
                ids.append(element_id)
        return ids

    def _rect(self, element_id):
        sid = self._session()
        try:
            data = requests.get("%s/session/%s/element/%s/rect" % (self.base, sid, element_id),
                                timeout=self.timeout).json()
        except Exception:
            return None
        value = data.get("value")
        return value if isinstance(value, dict) else None

    def _attribute(self, element_id, name):
        sid = self._session()
        try:
            data = requests.get("%s/session/%s/element/%s/attribute/%s"
                                % (self.base, sid, element_id, name),
                                timeout=self.timeout).json()
        except Exception:
            return ""
        value = data.get("value")
        return "" if value is None else str(value)

    def fields(self):
        found = []
        for chain in self.CHAINS:
            for element_id in self._ids(chain):
                rect = self._rect(element_id)
                if not rect:
                    continue
                found.append({"id": element_id, "chain": chain, "rect": rect,
                              "value": self._attribute(element_id, "value")})
        return found

    def set_text(self, text, lowest=True):
        fields = self.fields()
        if not fields:
            raise CWWDAError("这个界面没有可写的输入控件（应用没把输入框暴露给无障碍）")
        fields.sort(key=lambda item: item["rect"].get("y", 0), reverse=lowest)
        sid = self._session()
        errors = []
        for item in fields[:4]:
            try:
                response = requests.post(
                    "%s/session/%s/element/%s/value" % (self.base, sid, item["id"]),
                    json={"text": text}, timeout=self.timeout)
            except Exception as exc:
                errors.append("写入异常：%s" % exc)
                continue
            if response.status_code != 200:
                errors.append("写入返回 %s" % response.status_code)
                continue
            got = self._attribute(item["id"], "value")
            if got == text or (text == "" and not got):
                return True, {"rect": item["rect"], "value": got, "errors": errors}
            errors.append("写入后读回是 %r" % got[:20])
        raise CWWDAError("写入没成功：%s" % "；".join(errors[:3]))
