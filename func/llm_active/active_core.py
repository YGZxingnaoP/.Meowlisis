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
        if self.config.llm_type == "aliyun":
            from func.llm_active.port.aliyun import AutoAliyunLLM
            return AutoAliyunLLM()
        from func.llm_active.port.deepseek import AutoDeepSeekLLM
        return AutoDeepSeekLLM()

    def _on_user_message(self):
        """llm 收到用户消息：重置计时并清零连续触发次数"""
        self.timer.reset()
        self._n = 0

    def _on_ai_reply(self):
        """llm 完成回复：重置计时"""
        self.timer.reset()

    def pause(self):
        """暂停主动回复计时（唱歌期间调用）"""
        self.timer.pause()

    def resume(self):
        """恢复主动回复计时（唱歌结束后调用）"""
        self.timer.resume()

    def check_active(self):
        """周期轮询：计时到期则异步触发主动回复"""
        if self._running or not self.timer.is_due():
            return
        self._running = True
        Thread(target=self._trigger_safe).start()

    def _trigger_safe(self):
        try:
            self._trigger()
        except Exception:
            self.log.exception("主动回复异常")
        finally:
            self._running = False

    def _trigger(self):
        """触发主动回复：连续次数 +1 并按阈值分流策略"""
        self._n += 1
        if self._n <= self.config.strategy_threshold:
            continued = self.inherit.run()
            if not continued:
                self.origin.run()
        else:
            self.origin.run()
        # 触发结束后重置计时，等待下一轮空闲
        self.timer.reset()
