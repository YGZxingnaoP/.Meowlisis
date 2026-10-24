# -*- coding: utf-8 -*-
# func/config/hot_reload.py
# 配置热重载：把 config.yml 的改动原地推给已在运行的配置单例
#
# 原理：全项目访问配置都是 `XxxConfig().attr`，拿到的是同一个单例实例。
# 原地重跑该单例的 __init__，则所有调用点（约 268 处）与所有缓存了
# `self.config = XxxConfig()` 的对象（约 160 处）立刻看到新值，无需改任何调用点。
#
# 注意：**不要**用 SingletonMeta.reset_instance —— 那会丢掉实例，
# 让缓存了旧实例的地方静默读到旧值。

import os
import threading
import time

from func.config.default_config import CONFIG_FILE
from func.log.default_log import DefaultLog
from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import SingletonMeta

_LOCK = threading.RLock()
_last_mtime = 0.0
_last_report = {}


# ==================== 内部工具 ====================

def _log():
    """取日志器；日志系统未就绪时退化为标准 logging，保证热重载自身不会抛异常"""
    try:
        return DefaultLog().getLogger()
    except Exception:
        import logging
        return logging.getLogger("hot_reload")


def _get(cls):
    """已实例化的单例；未实例化的返回 None（不主动创建，避免意外副作用）"""
    return SingletonMeta._instances.get(cls)


def _config_singletons():
    """已在内存里的配置单例。

    识别规则：类所在模块名以 .config / .app_config 结尾。
    未实例化过的不用管 —— 它们下次构造时直接读新的 _root，本来就是热的。
    """
    return [c for c in list(SingletonMeta._instances)
            if c.__module__.endswith((".config", ".app_config"))]


# ==================== 重建钩子：值被拷出配置实例的地方 ====================

def _hook_sensevoice():
    """语音识别总开关：常驻线程 + 开关采集设备/识别会话"""
    from func.sensevoice.host import SenseVoiceHost
    host = _get(SenseVoiceHost)
    if host is not None:
        host.apply()


def _hook_llm_core():
    """主对话 LLM：api_key/model/温度在端口对象 __init__ 里被拷走，必须重建"""
    from func.llm.llm_core import LLmCore
    obj = _get(LLmCore)
    if obj is not None:
        obj.rebuild_llm()


def _hook_llm_active():
    """主动回复：LLM 客户端 + 冷时间计时 + 派生的 token 上限"""
    from func.llm_active.active_core import AutoActiveCore
    obj = _get(AutoActiveCore)
    if obj is not None:
        obj.rebuild()


def _hook_tts():
    """TTS：GPT-SoVITS 地址 + 打断按键/模式"""
    from func.tts.tts_core import TTsCore
    obj = _get(TTsCore)
    if obj is not None:
        obj.rebuild()


_HOOKS = (
    ("sensevoice", _hook_sensevoice),
    ("llm_core", _hook_llm_core),
    ("llm_active", _hook_llm_active),
    ("tts", _hook_tts),
)

# 运行期注册的额外钩子：持有配置值但不便从模块拿到的对象（如 Minecraft 日志读取器）
_extra_hooks = {}


def register(name, fn):
    """注册热重载钩子（幂等覆盖；fn 无参，异常会被吞掉并记日志）"""
    if name and callable(fn):
        _extra_hooks[str(name)] = fn


def unregister(name):
    _extra_hooks.pop(str(name), None)


# ==================== 主入口 ====================

def reload_all(trigger="manual") -> dict:
    """全量热重载。**永不向外抛异常**：读盘失败就保留旧配置继续跑。"""
    global _last_report
    report = {"trigger": trigger, "refreshed": 0, "failed": {}}
    log = _log()

    with _LOCK:
        # ① 重新读盘，原子换掉 _root（读失败则整体放弃，旧配置继续用）
        try:
            ConfigReader().reload()
        except Exception as e:
            log.exception("[热重载] 读取 config.yml 失败，保留旧配置")
            report["failed"]["config.yml"] = repr(e)
            _last_report = report
            return report

        # ② 原地重跑各配置单例的 __init__。
        #    跑两遍：第二遍让「派生节点」吃到新值
        #    （AutoActiveConfig.__init__ 里又读了 LLMConfig().local_llm_type / max_tokens）
        for _ in range(2):
            for cls in _config_singletons():
                obj = SingletonMeta._instances.get(cls)
                if obj is None:
                    continue
                try:
                    cls.__init__(obj)        # 原地重跑，不新建实例
                    report["refreshed"] += 1
                except Exception as e:
                    report["failed"][cls.__name__] = repr(e)
                    log.exception(f"[热重载] 刷新配置单例失败: {cls.__name__}")

        # ③ 重建被拷出去的对象 / 起停子系统
        for name, fn in list(_HOOKS) + list(_extra_hooks.items()):
            try:
                fn()
            except Exception as e:
                report["failed"][name] = repr(e)
                log.exception(f"[热重载] 钩子执行失败: {name}")

    if report["failed"]:
        log.warning(f"[热重载] 完成（{trigger}），{len(report['failed'])} 项失败: "
                    f"{list(report['failed'])}")
    else:
        log.info(f"[热重载] 完成（{trigger}），已刷新 {report['refreshed']} 个配置节点")
    _last_report = report
    return report


def last_report() -> dict:
    """最近一次热重载的结果（供 HTTP 接口回执）"""
    return dict(_last_report)


# ==================== 文件监听 ====================

def _config_mtime():
    try:
        return os.path.getmtime(CONFIG_FILE)
    except OSError:
        return None


def check_once() -> bool:
    """比对 config.yml 修改时间，有变化则热重载一次。返回是否发生了重载"""
    global _last_mtime
    m = _config_mtime()
    if m is None or m == _last_mtime:
        return False
    with _LOCK:
        if m == _last_mtime:
            return False
        _last_mtime = m
        reload_all(trigger="watch")
    return True


def start_watcher(interval=2.0):
    """起一个守护线程轮询 config.yml（手改文件、外部工具写文件都能生效）"""
    global _last_mtime
    _last_mtime = _config_mtime() or 0.0

    def _loop():
        while True:
            time.sleep(interval)
            try:
                check_once()
            except Exception:
                _log().exception("[热重载] 文件监听异常")

    t = threading.Thread(target=_loop, daemon=True, name="config-watcher")
    t.start()
    return t
