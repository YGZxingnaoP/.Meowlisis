from func.log.default_log import DefaultLog
from func.pipeline.id_signup import IdSignupBridge
from func.toolbox.danmaku.identity.bili_send import TBDanmakuIdentitySend
from func.tools.singleton_mode import singleton


@singleton
class TBDanmakuIdentityCmd:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.bridge = IdSignupBridge()
        self.sender = TBDanmakuIdentitySend()

    def is_command(self, text):
        """判断一条弹幕是不是绑定指令"""
        return self.bridge.is_command(text)

    def handle(self, uid, uname, text):
        """处理一条弹幕指令：命中就用文字弹幕回，不进 TTS"""
        text = str(text or "").strip()
        if not text or not self.bridge.is_command(text):
            return False
        uid = str(uid or "").strip()
        self.bridge.set_current("bili", uid, uname)
        hit, reply = self.bridge.handle_command(text, "bili", uid, name=uname)
        if not hit:
            return False
        self.sender.send(self._help_hint(reply))
        self.log.info(f"[Identity] 弹幕绑定指令已处理: {text[:20]}")
        return True

    def _help_hint(self, reply):
        """帮助这类长回复弹幕发不下，改成指引去 QQ 私聊查"""
        text = str(reply or "")
        if "用法" not in text and "帮助" not in text:
            return text
        return f"用法太长弹幕发不下，请在 QQ 私聊发「{self.bridge.prefix()} 帮助」查看"

    def handle_queue(self, receiver):
        """扫一遍弹幕与 SC 队列：处理掉指令并从队列移除，返回是否处理过"""
        handled = False
        for item in receiver.snapshot_danmaku():
            text = str(item.get("content") or "")
            if not self.bridge.is_command(text):
                continue
            self.handle(item.get("uid"), item.get("username"), text)
            receiver.remove_danmaku(item)
            handled = True
        for item in receiver.snapshot_sc():
            text = str(item.get("content") or "")
            if not self.bridge.is_command(text):
                continue
            self.handle(item.get("uid"), item.get("username"), text)
            receiver.remove_sc(item)
            handled = True
        return handled
