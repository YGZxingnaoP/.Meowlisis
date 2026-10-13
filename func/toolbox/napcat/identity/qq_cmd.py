from func.log.default_log import DefaultLog
from func.pipeline.id_signup import IdSignupBridge
from func.toolbox.napcat.identity.qq_send import TBNapcatIdentitySend
from func.tools.singleton_mode import singleton


@singleton
class TBNapcatIdentityCmd:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.bridge = IdSignupBridge()
        self.sender = TBNapcatIdentitySend()

    def handle_private(self, user_id, text, nickname=""):
        """私聊绑定指令：命中就回结果并吃掉这条消息"""
        user_id = str(user_id or "").strip()
        text = str(text or "").strip()
        if not user_id or not text:
            return False
        self.bridge.set_current("qq", user_id, nickname)
        if not self.bridge.is_command(text):
            return False
        hit, reply = self.bridge.handle_command(text, "qq", user_id, name=nickname)
        if not hit:
            return False
        self.sender.send_private(user_id, reply)
        self.log.info(f"[Identity] 私聊绑定指令已处理: {text[:20]}")
        return True

    def handle_group(self, user_id, group_id, text, nickname="", at_self=False):
        """群聊只在被 @ 时处理，且只放开查看与绑定类指令"""
        user_id = str(user_id or "").strip()
        group_id = str(group_id or "").strip()
        text = str(text or "").strip()
        if not at_self or not user_id or not group_id or not text:
            return False
        self.bridge.set_current("qq", user_id, nickname)
        if not self.bridge.is_command(text):
            return False
        hit, reply = self.bridge.handle_command(text, "qq", user_id, name=nickname, group=True)
        if not hit:
            return False
        self.sender.send_group(group_id, user_id, reply)
        self.log.info(f"[Identity] 群绑定指令已处理: {text[:20]}")
        return True
