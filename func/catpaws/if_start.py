from func.catpaws.config import CWCatPawsConfig
from func.tools.singleton_mode import singleton


@singleton
class CWCatPawsIfStart:
    def __init__(self, config=None):
        self.config = config or CWCatPawsConfig()

    def decide(self, text):
        body = str(text or "").strip()
        if not body:
            return False, ""
        for prefix in self.config.start_prefixes:
            if prefix and body.startswith(prefix):
                return True, self._strip(body, prefix)
        for keyword in self.config.intent_keywords:
            if keyword and keyword in body:
                return True, body
        if self._app_hit(body):
            return True, body
        return False, ""

    def is_stop(self, text):
        body = str(text or "").strip()
        if not body:
            return False
        return any(keyword and keyword in body for keyword in self.config.stop_keywords)

    def _app_hit(self, body):
        app = next((name for name in self.config.trigger_apps if name and name in body), "")
        if not app:
            return False
        return any(word and word in body for word in self.config.action_words)

    @staticmethod
    def _strip(body, prefix):
        rest = body[len(prefix):].lstrip("：:，,。!！ ")
        return rest.strip()
