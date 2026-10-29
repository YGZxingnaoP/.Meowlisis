# -*- coding: utf-8 -*-
# func/llm_active/active_core.py
# 主动回复模块编排入口：计时检测 + 触发次数统计 + 策略分流

from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.pipeline.llm_timer import LLMTimerBridge
from func.llm_active.config import AutoActiveConfig
from func.llm_active.timer import AutoTimer
from func.llm_active.inherit.inherit_core import AutoInheritCore
from func.llm_active.origin.origin_core import AutoOriginCore


@singleton
class AutoActiveCore:
    """主动回复核心：空闲计时、连续触发计数与 inherit/origin 策略分流"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = AutoActiveConfig()
        self.timer = AutoTimer(self.config.cold_time)
        self.llm = self._create_llm()
        self.inherit = AutoInheritCore(self.llm)
        self.origin = AutoOriginCore(self.llm)
        # 连续空闲触发次数
        self._n = 0
        self._running = False

        # 导演模块：每轮回复后的无聊判官 / 触发时接管表演（失败不影响原主动回复）
        self.director = None
        try:
            from func.llm_active.director.core import DirectorCore
            self.director = DirectorCore()
        except Exception:
            self.log.exception("初始化导演模块失败，主动回复按原逻辑运行")

        # 注册到 llm_timer 桥接：llm 活动时重置计时
        LLMTimerBridge().register(
            on_user_message=self._on_user_message,
            on_ai_reply=self._on_ai_reply,
        )

        # 启动 B站内容收集后台线程（origin 视频素材池，缓存满自动停补）
        try:
            from func.llm_active.origin.web_browse.browse_core import AutoBrowseCore
            AutoBrowseCore().start()
        except Exception:
            self.log.exception("启动 B站内容收集线程失败")

    def _create_llm(self):
        """根据 llm 后端类型创建主动回复 LLM 客户端"""
        if self.config.llm_type == "meowllm":
            from func.llm_active.port.meowllm import AutoMeowLLM
            return AutoMeowLLM()
        if self.config.llm_type == "gemini":
            from func.llm_active.port.gemini import AutoGeminiLLM
            return AutoGeminiLLM()
        if self.config.llm_type == "aliyun":
            from func.llm_active.port.aliyun import AutoAliyunLLM
            return AutoAliyunLLM()
        from func.llm_active.port.deepseek import AutoDeepSeekLLM
        return AutoDeepSeekLLM()

    def rebuild(self):
        """配置热重载：换掉主动回复的 LLM 客户端，刷新冷时间计时。

        只换引用，不重建 inherit/origin：
        - 它们只持有 self.llm 与若干无状态辅助对象，换个引用就够；
        - LLMTimerBridge 注册的是 AutoActiveCore 的绑定方法，重建子对象反而没意义。
        正在触发中也照换：赋值是原子的，在途调用握着自己的端口引用，旧 client 由
        close_port_later 延迟关闭，不会掐断。
        """
        from func.llm.port import close_port_later
        old = getattr(self, "llm", None)
        self.llm = self._create_llm()
        if old is not None and old is not self.llm:
            close_port_later(old)
        self.inherit.llm = self.llm
        self.origin.llm = self.llm
        self.timer.cold_time = self.config.cold_time
        # 导演模块的端口也要跟着换（配置项由各自的 config 单例刷新）
        if self.director is not None:
            try:
                self.director.rebuild()
            except Exception:
                self.log.exception("导演模块热重载失败")

    def _on_user_message(self):
        """llm 收到用户消息：重置计时并清零连续触发次数"""
        self.timer.reset()
        self._n = 0

    def _on_ai_reply(self, source="llm"):
        """llm 完成回复：重置计时"""
        self.timer.reset()

    def pause(self):
        """暂停主动回复计时（唱歌期间调用）"""
        self.timer.pause()

    def resume(self):
        """恢复主动回复计时（唱歌结束后调用）"""
        self.timer.resume()

    def check_active(self):
        """周期轮询：计时到期则异步触发主动回复（插件占用时让位）"""
        if not self._allow_active_reply():
            return
        if self._running or not self.timer.is_due():
            return
        self._running = True
        Thread(target=self._trigger_safe).start()

    def trigger_now(self, reason="bored"):
        """跳过 cold_time 立即触发一次主动回复（导演判官用）"""
        if not self._allow_active_reply():
            return False
        if self._running:
            return False
        self._running = True
        Thread(target=self._trigger_safe, kwargs={"reason": reason}).start()
        return True

    @staticmethod
    def _allow_active_reply():
        """插件状态总线：有插件声明「暂停主动回复」时让位"""
        try:
            from func.pipeline.plugins_state import PluginsStateBridge, CAP_ACTIVE_REPLY
            return PluginsStateBridge().allow(CAP_ACTIVE_REPLY)
        except Exception:
            return True

    def _trigger_safe(self, reason=None):
        try:
            self._trigger(reason)
        except Exception:
            self.log.exception("主动回复异常")
        finally:
            self._running = False

    def _trigger(self, reason=None):
        """触发主动回复：导演优先接管；否则按连续次数在 inherit/origin 间分流"""
        self._n += 1
        if self.director is not None:
            try:
                if self.director.on_idle_trigger(forced=bool(reason), reason=str(reason or "")):
                    self.timer.reset()
                    return
            except Exception:
                self.log.exception("导演模块接管失败，回落原主动回复")
        if self._n <= self.config.strategy_threshold:
            continued = self.inherit.run()
            if not continued:
                self.origin.run()
        else:
            self.origin.run()
        # 触发结束后重置计时，等待下一轮空闲
        self.timer.reset()
