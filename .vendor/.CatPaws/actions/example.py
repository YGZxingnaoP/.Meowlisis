"""
示例动作脚本：依次点击、滑动、长按
通过 WDA 原生 W3C Actions API 发送手势。

入口函数：main(send=...) 回调风格
send: 异步回调，传入 JSON 字符串发送动作到手机
"""
import asyncio
import json


async def main(send=None):
    if send is None:
        print("没有执行器连接，无法发送动作")
        return

    print("🎬 示例动作序列开始")

    # 点击 (200, 300) —— 像素坐标，后端自动转换为逻辑点
    await send(json.dumps({
        "type": "action", "action": "tap",
        "params": {"x": 200, "y": 300}
    }))
    print("  ✅ tap(200, 300)")
    await asyncio.sleep(0.5)

    # 滑动
    await send(json.dumps({
        "type": "action", "action": "swipe",
        "params": {"from_x": 100, "from_y": 500, "to_x": 300, "to_y": 500, "duration": 0.3}
    }))
    print("  ✅ swipe(100,500 → 300,500)")
    await asyncio.sleep(0.3)

    # 长按 1.5 秒
    await send(json.dumps({
        "type": "action", "action": "long_press",
        "params": {"x": 250, "y": 400, "duration": 1.5}
    }))
    print("  ✅ long_press(250, 400, 1.5s)")
    await asyncio.sleep(0.5)

    print("🎬 示例动作序列执行完成")
