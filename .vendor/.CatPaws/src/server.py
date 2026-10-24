import sys
import os
import asyncio
import webbrowser
from threading import Thread

# 路径处理
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, 'src')
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, SRC_DIR)

from server.http_server import start_http_server_background, set_event_loop, get_local_ip, HTTP_PORT


def _run_event_loop(loop):
    """在后台线程中运行 asyncio 事件循环"""
    asyncio.set_event_loop(loop)
    loop.run_forever()


if __name__ == "__main__":
    # 1. 创建 asyncio 事件循环（用于调度动作脚本协程）
    loop = asyncio.new_event_loop()
    set_event_loop(loop)
    loop_thread = Thread(target=_run_event_loop, args=(loop,), daemon=True)
    loop_thread.start()

    # 2. 启动 HTTP 服务（控制面板、状态、屏幕控制台）
    start_http_server_background()

    # 3. 获取本机 IP，打开控制面板
    local_ip = get_local_ip()
    control_ui_url = f"http://{local_ip}:{HTTP_PORT}"

    # 4. 自动打开浏览器（由主项目启动器托管时 stdout 被重定向，不弹窗）
    if sys.stdout.isatty():
        webbrowser.open_new_tab(control_ui_url)

    print("🐾 CatPaws WDA 模式已启动")
    print(f"🌐 控制面板: {control_ui_url}")
    print("💡 请在控制面板中输入手机 IP 并连接 WDA")

    try:
        # 保持程序运行
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 CatPaws 已退出")
