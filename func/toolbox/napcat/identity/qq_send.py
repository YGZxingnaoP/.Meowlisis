from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class TBNapcatIdentitySend:
    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_private(self, user_id, text):
        """私聊发文字回复，不进缓冲也不进大模型"""
        if not text:
            return False
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            TBNapCatCore().send_private_text(str(user_id), text)
            return True
        except Exception:
            self.log.exception("[Identity] 私聊绑定回复发送失败")
            return False

    def send_group(self, group_id, user_id, text):
        """群里发文字回复并 @ 发起人"""
        if not text:
            return False
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            TBNapCatCore().send_group_at_text(str(group_id), str(user_id), text)
            return True
        except Exception:
            self.log.exception("[Identity] 群绑定回复发送失败")
            return False
