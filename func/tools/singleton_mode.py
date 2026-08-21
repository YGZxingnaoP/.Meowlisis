# -*- coding: utf-8 -*-
# func/tools/singleton_mode.py
# 单例装饰器（元类实现，保持类名是真类，避免类属性访问报错）

import threading


class SingletonMeta(type):
    """单例元类：拦截 __call__，同一类始终返回同一实例。

    - 懒加载 + 双重检查锁（线程安全）；
    - 实例缓存在元类内部 dict，按类对象区分；
    - 提供 reset_instance() 类方法用于显式重置（测试/重新初始化）。
    """

    _instances = {}
    # 可重入锁：单例的 __init__ 内可能再实例化其它单例（如 ConfigReader），
    # 若用不可重入 Lock 会在同线程嵌套获取时死锁。
    _lock = threading.RLock()

    def __call__(cls, *args, **kwargs):
        if cls not in SingletonMeta._instances:
            with SingletonMeta._lock:
                if cls not in SingletonMeta._instances:
                    SingletonMeta._instances[cls] = super().__call__(*args, **kwargs)
        return SingletonMeta._instances[cls]

    @classmethod
    def reset_instance(mcls, cls):
        """重置某个单例类的实例（下次调用重新创建）"""
        with mcls._lock:
            SingletonMeta._instances.pop(cls, None)


def singleton(cls):
    """单例装饰器：把类改造为带 SingletonMeta 元类的真类。

    - 保持类名、基类、命名空间、__module__ 等元信息不变；
    - 调用方仍使用 ClassName() 获取单例；
    - 类名保持为真类，类属性访问（ClassName.ATTR）、isinstance 均正常。
    """
    return SingletonMeta(cls.__name__, cls.__bases__, dict(cls.__dict__))
