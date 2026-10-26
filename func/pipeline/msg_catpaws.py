from func.log.default_log import DefaultLog


class MsgCatPawsBridge:
    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_catpaws(self, text, meowid="", source="msg"):
        if not text or not str(text).strip():
            return False
        try:
            from func.catpaws.core import CWCatPawsCore
            return bool(CWCatPawsCore().receive(str(text).strip(), meowid, source))
        except Exception:
            self.log.exception("msg → catpaws 处理异常")
            return False
