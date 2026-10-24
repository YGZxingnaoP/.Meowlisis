"""
Python 环境配置文件

运行环境与主项目共用（<项目根>/runtime/311），不再依赖本目录 env/python。
个别脚本需要独立解释器时，把 PYTHON_ENVS 里的值改成绝对路径即可。
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))
RUNTIME_PYTHON = os.path.join(PROJECT_DIR, "runtime", "311", "python.exe")
if not os.path.exists(RUNTIME_PYTHON):
    RUNTIME_PYTHON = sys.executable

# ========== 配置区域 ==========

PYTHON_ENVS = {
    # 脚本名: Python 解释器绝对路径
    "jump_jump_tf_cv": RUNTIME_PYTHON,  # 纯CV算法版

    # 示例：其他需要特殊环境的脚本
    # "some_other_script": r"C:\Python37\python.exe",
}

# ========== 自动加载到 action_manager ==========

def apply_to_action_manager():
    """将配置应用到 action_manager.TF_SCRIPTS"""
    try:
        from . import action_manager
        for script_name, python_path in PYTHON_ENVS.items():
            if script_name in action_manager.TF_SCRIPTS:
                action_manager.TF_SCRIPTS[script_name]["python_exe"] = python_path
                print(f"✅ 已配置 {script_name} → {python_path}")
            else:
                print(f"⚠️ 脚本 {script_name} 未在 TF_SCRIPTS 中注册")
    except ImportError as e:
        print(f"❌ 无法导入 action_manager: {e}")


# 模块导入时自动应用配置
apply_to_action_manager()
