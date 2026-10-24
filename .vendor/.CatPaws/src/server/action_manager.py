import os
import importlib
import asyncio
import traceback
import json
import subprocess
from pathlib import Path

from .wda_native_client import get_wda_client

# actions 文件夹相对于项目根目录的位置（server.py 启动时 cwd 是根目录）
ACTIONS_DIR = "actions"

# TensorFlow 脚本配置：需要独立 Python 环境的脚本列表
TF_SCRIPTS = {
    "jump_jump_tf": {  # 脚本名 → 配置
        "python_exe": None,  # 将在运行时从 env_config 读取
        "screenshot_file": "current_screenshot.png",
    },
    "jump_jump_tf_simple": {  # 简化版（不需要 object_detection）
        "python_exe": None,
        "screenshot_file": "current_screenshot.png",
    },
    "jump_jump_tf_cv": {  # 纯CV算法版（推荐）
        "python_exe": None,
        "screenshot_file": "current_screenshot.png",
    }
}

# 运行中的子进程管理
_running_processes = {}  # {script_name: subprocess_handle}


def list_actions():
    """返回所有可执行动作脚本的文件名（不含扩展名）"""
    if not os.path.isdir(ACTIONS_DIR):
        return []
    files = [f[:-3] for f in os.listdir(ACTIONS_DIR)
             if f.endswith(".py") and not f.startswith("_")]
    return sorted(files)


def _dispatch_wda(cmd: dict) -> bool:
    """
    将标准指令解析并转发给 WDA 原生客户端。
    cmd 格式: {"type": "action", "action": "tap", "params": {"x": 200, "y": 300}}
    """
    client = get_wda_client()
    if not client:
        print("❌ WDA 客户端未初始化")
        return False

    action = cmd.get("action", "")
    params = cmd.get("params", {})

    # 调试：打印坐标系统信息
    from screen import coord_system
    print(f"🔍 [坐标系统] scale={coord_system.scale}, screenshot={coord_system.screenshot_size}, logical={coord_system.logical_size}")

    if action == "tap":
        lx, ly = coord_system.to_point(params["x"], params["y"])
        print(f"📍 [坐标转换] pixel({params['x']},{params['y']}) -> logical({lx},{ly})")
        return client.tap(lx, ly)
    elif action == "long_press":
        lx, ly = coord_system.to_point(params["x"], params["y"])
        print(f"📍 [坐标转换] pixel({params['x']},{params['y']}) -> logical({lx},{ly}), duration={params.get('duration', 1.0)}")
        return client.long_press(lx, ly, params.get("duration", 1.0))
    elif action == "swipe":
        lfx, lfy = coord_system.to_point(params["from_x"], params["from_y"])
        ltx, lty = coord_system.to_point(params["to_x"], params["to_y"])
        return client.swipe(lfx, lfy, ltx, lty, params.get("duration", 0.5))
    elif action == "repeated_tap":
        return client.repeated_tap(
            params.get("x", 0), params.get("y", 0),
            params.get("times", 1), params.get("interval", 0.3)
        )
    elif action == "activate_app":
        return client.activate_app(params["bundle_id"])
    elif action == "launch_app":
        return client.launch_app(params["bundle_id"])
    else:
        print(f"⚠️ WDA 未知动作: {action}")
        return False


async def run_action(name: str, ws_send_queue=None):
    """
    动态加载并异步执行 actions/name.py 中的 main() 或 run() 函数。
    通过 WDA 原生 W3C Actions API 发送手势。
    对于 TensorFlow 脚本，使用子进程隔离运行。
    """
    try:
        # 检查是否为需要子进程的脚本
        if name in TF_SCRIPTS:
            await _run_subprocess_action(name)
            return

        # 原有逻辑：普通脚本通过 importlib 运行
        import sys
        if ACTIONS_DIR not in sys.path:
            sys.path.insert(0, ACTIONS_DIR)
        mod = importlib.import_module(name)

        # 优先查找 main() 协程，其次查找 run() 协程
        entry = None
        if hasattr(mod, "main") and asyncio.iscoroutinefunction(mod.main):
            entry = mod.main
        elif hasattr(mod, "run") and asyncio.iscoroutinefunction(mod.run):
            entry = mod.run

        if entry is not None:
            async def wda_send(json_str: str):
                """将 JSON 字符串解析为 dict 并通过 WDA 发送"""
                try:
                    cmd = json.loads(json_str)
                    success = _dispatch_wda(cmd)
                    if not success:
                        print(f"⚠️ 动作发送失败: {cmd.get('action', '?')}")
                except Exception as e:
                    print(f"❌ 动作解析/发送错误: {e}")

            # 兼容 asyncio.Queue 接口的包装器
            class _SendQueueWrapper:
                async def put(self, json_str: str):
                    await wda_send(json_str)

            send_queue = _SendQueueWrapper()

            param_names = entry.__code__.co_varnames[:entry.__code__.co_argcount]
            if "send" in param_names:
                await entry(send=wda_send)
            elif "send_queue" in param_names:
                await entry(send_queue)
            else:
                await entry()
        else:
            print(f"[!] {name}.py 中没有异步 main() 或 run() 函数")
    except Exception:
        traceback.print_exc()


async def _run_subprocess_action(name: str):
    """
    使用独立 Python 环境运行特定脚本（如 TensorFlow 1.x 脚本）。
    子进程通过 stdout 输出 JSON 动作指令，主进程捕获并转发给 WDA。
    """
    config = TF_SCRIPTS.get(name)
    if not config:
        print(f"❌ 未找到脚本 {name} 的子进程配置")
        return

    # 获取 Python 解释器路径
    python_exe = config.get("python_exe")
    if not python_exe or not os.path.exists(python_exe):
        print(f"❌ Python 解释器不存在: {python_exe}")
        print(f"💡 请在 src/server/env_config.py 中配置正确的路径")
        return

    script_path = os.path.join(ACTIONS_DIR, f"{name}.py")
    if not os.path.exists(script_path):
        print(f"❌ 脚本文件不存在: {script_path}")
        return

    screenshot_file = config.get("screenshot_file", "current_screenshot.png")
    project_root = os.getcwd()

    print(f"🚀 启动子进程: {python_exe} {script_path}")

    # 【关键修复】启动子进程前先获取一次初始截图
    print(f"📸 [初始化] 获取初始截图...")
    from .wda_native_client import get_wda_client
    wda = get_wda_client()
    if wda and wda.has_session:
        try:
            img = wda.screenshot()
            if img:
                final_path = os.path.join(project_root, screenshot_file)
                img.save(final_path, format='PNG')
                print(f"✅ [初始化] 初始截图已保存 ({img.size[0]}x{img.size[1]})")
                
                # 【关键】强制设置 scale
                from screen import coord_system, receiver
                if coord_system.scale == 1.0 and img.size[0] > 0:
                    logical_w, logical_h = wda.get_screen_size()
                    if logical_w and logical_w > 0:
                        scale = round(img.size[0] / logical_w, 1)
                        receiver.set_scale(scale)
                        print(f"📐 [强制设置] scale={scale}x (screenshot={img.size[0]}x{img.size[1]}, logical={logical_w}x{logical_h})")
            else:
                print(f"⚠️ [初始化] WDA 截图返回 None")
        except Exception as e:
            print(f"⚠️ [初始化] 截图失败: {e}")
    else:
        print(f"⚠️ [初始化] WDA 客户端未就绪")

    # 启动截图更新任务（响应式）
    async def update_screenshot():
        """定期保存最新截图供子进程读取（原子写入避免截断）"""
        from .wda_native_client import get_wda_client
        temp_file = screenshot_file + ".tmp"
        request_flag_file = "screenshot_request.flag"
        loop_count = 0
        error_count = 0
        while True:
            try:
                # 【关键】检查是否有截图请求
                request_flag_path = os.path.join(project_root, request_flag_file)
                if not os.path.exists(request_flag_path):
                    # 没有请求，等待50ms再检查
                    await asyncio.sleep(0.05)
                    continue
                
                print(f"📥 [截图任务] 检测到截图请求")
                
                # 有请求，执行截图
                wda = get_wda_client()
                if not wda:
                    print(f"⚠️ [截图任务] WDA 客户端未初始化")
                    error_count += 1
                    await asyncio.sleep(0.1)
                    continue
                    
                if not wda.has_session:
                    print(f"⚠️ [截图任务] WDA 会话不存在")
                    error_count += 1
                    await asyncio.sleep(0.1)
                    continue
                    
                img = wda.screenshot()
                if not img:
                    print(f"⚠️ [截图任务] WDA 截图返回 None")
                    error_count += 1
                    await asyncio.sleep(0.1)
                    continue
                
                # 成功截图，重置错误计数
                error_count = 0
                
                # 【关键修复】强制设置 scale，确保坐标转换正确
                from screen import coord_system, receiver
                if coord_system.scale == 1.0 and img.size[0] > 0:
                    # 第一次成功截图，立即计算 scale
                    logical_w, logical_h = wda.get_screen_size()
                    if logical_w and logical_w > 0:
                        scale = round(img.size[0] / logical_w, 1)
                        receiver.set_scale(scale)
                        print(f"📐 [强制设置] scale={scale}x (screenshot={img.size[0]}x{img.size[1]}, logical={logical_w}x{logical_h})")
                
                # 先写入临时文件
                temp_path = os.path.join(project_root, temp_file)
                final_path = os.path.join(project_root, screenshot_file)
                
                # 写入临时文件
                img.save(temp_path, format='PNG')
                
                # 【关键修复】确保临时文件完全写入后再重命名
                import time as time_module
                time_module.sleep(0.01)  # 等待10ms确保磁盘写入完成
                
                # 尝试原子替换，失败则直接覆盖
                try:
                    if os.path.exists(final_path):
                        os.remove(final_path)  # 先删除旧文件
                        time_module.sleep(0.01)  # 等待删除完成
                    os.rename(temp_path, final_path)
                    time_module.sleep(0.01)  # 等待重命名完成
                except (PermissionError, OSError):
                    # 如果删除失败，直接覆盖（可能有短暂不一致）
                    try:
                        img.save(final_path, format='PNG')
                        time_module.sleep(0.01)
                    except:
                        pass  # 忽略覆盖失败
                
                # 删除请求标志文件，表示截图已完成
                try:
                    os.remove(request_flag_path)
                    print(f"✅ [截图任务] 标志文件已删除，截图完成")
                except Exception as e:
                    print(f"⚠️ [截图任务] 删除标志文件失败: {e}")
                
                loop_count += 1
                if loop_count % 10 == 0:  # 每10次打印一次
                    print(f"📸 [截图任务] 截图已更新 #{loop_count} ({img.size[0]}x{img.size[1]})")
                    
            except Exception as e:
                print(f"❌ [截图任务] 异常: {e}")
                import traceback
                traceback.print_exc()
                error_count += 1
            await asyncio.sleep(0.05)  # 快速轮询请求标志

    screenshot_task = asyncio.create_task(update_screenshot())

    # 设置环境变量，确保子进程能找到 object_detection
    env = os.environ.copy()
    actions_dir = os.path.join(project_root, ACTIONS_DIR)
    if actions_dir not in env.get('PYTHONPATH', ''):
        env['PYTHONPATH'] = actions_dir + os.pathsep + env.get('PYTHONPATH', '')

    # 启动子进程
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            python_exe,
            script_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=project_root,
            env=env
        )
        
        # 记录运行中的进程
        _running_processes[name] = proc
        print(f"✅ 子进程已启动，PID: {proc.pid}")

        # 异步读取 stdout（JSON 动作指令）
        async def read_stdout():
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore').strip()
                if not line_str:
                    continue
                print(f"📨 [收到子进程指令] {line_str[:150]}")  # 调试日志
                try:
                    cmd = json.loads(line_str)
                    print(f"📤 [执行WDA动作] action={cmd.get('action')}, params={cmd.get('params')}")
                    success = _dispatch_wda(cmd)
                    if success:
                        print(f"✅ [WDA动作成功] {cmd.get('action')}")
                    else:
                        print(f"❌ [WDA动作失败] {cmd.get('action')}")
                except json.JSONDecodeError:
                    print(f"⚠️ 子进程输出不是有效 JSON: {line_str[:100]}")
                except Exception as e:
                    print(f"❌ 处理子进程动作失败: {e}")
                    import traceback
                    traceback.print_exc()

        # 异步读取 stderr（日志输出）
        async def read_stderr():
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                print(f"[{name}] {line.decode('utf-8', errors='ignore').rstrip()}")

        # 并发读取输出并等待进程结束
        await asyncio.gather(read_stdout(), read_stderr(), proc.wait())
        print(f"✅ 子进程已退出，返回码: {proc.returncode}")

    except Exception as e:
        print(f"❌ 子进程启动失败: {e}")
        traceback.print_exc()
    finally:
        # 从运行列表中移除
        if name in _running_processes:
            del _running_processes[name]
        
        # 取消截图任务
        screenshot_task.cancel()
        try:
            await screenshot_task
        except asyncio.CancelledError:
            pass


def stop_action(name: str) -> bool:
    """
    停止正在运行的动作脚本。
    对于子进程脚本，发送 SIGTERM 信号优雅退出。
    返回 True 如果成功停止，False 如果脚本未运行。
    """
    if name not in _running_processes:
        print(f"⚠️ 脚本 {name} 未在运行")
        return False
    
    proc = _running_processes[name]
    try:
        print(f"🛑 正在停止脚本 {name} (PID: {proc.pid})...")
        proc.terminate()  # 发送 SIGTERM
        print(f"✅ 已发送停止信号到 {name}")
        return True
    except Exception as e:
        print(f"❌ 停止脚本失败: {e}")
        return False


def get_running_actions() -> list:
    """
    获取当前正在运行的动作列表。
    """
    running = []
    for name, proc in _running_processes.items():
        # 检查进程是否还在运行
        if proc.returncode is None:  # returncode=None 表示还在运行
            running.append(name)
        else:
            # 清理已结束的进程
            del _running_processes[name]
    return running
