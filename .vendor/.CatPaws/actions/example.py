import time

import cw_script


def tap_center():
    """点屏幕正中：最基础的一步，用来确认脚本链路通了"""
    screen = cw_script.screen()
    pixel = screen.get("pixel") or [0, 0]
    cw_script.tap(pixel[0] // 2, pixel[1] // 2)


def run():
    """示例 action：点一下 → 看文字 → 汇报；真正写脚本时按这个骨架改"""
    options = cw_script.params()
    text = str(options.get("target_text") or "")
    if cw_script.should_stop():
        cw_script.done(False, "还没开始就被叫停了")
        return
    if text:
        found = cw_script.ocr_find(text)
        if not found:
            cw_script.log("屏幕上没看到「%s」" % text)
            cw_script.done(False, "没找到目标文字")
            return
        cw_script.tap(found[0], found[1])
    else:
        tap_center()
    cw_script.wait(600)
    cw_script.log("观察到的文字：%s" % " / ".join(
        str(item.get("text") or "") for item in cw_script.observe_texts()[:8]))
    cw_script.done(True, "示例跑完了，用时 %d ms" % int(time.time() * 1000 % 100000))


if __name__ == "__main__":
    run()
