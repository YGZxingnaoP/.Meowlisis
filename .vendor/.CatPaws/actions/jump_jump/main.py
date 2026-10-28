import math
import time

import cw_script
from PIL import ImageChops, ImageStat

PIECE_R = (50, 60)
PIECE_G = (53, 63)
PIECE_B = (95, 110)
PIECE_BOTTOM_OFFSET = 20
SCAN_TOP_RATIO = 0.25
SCAN_BOTTOM_RATIO = 0.70
BG_DIFF_THRESHOLD = 10
MIN_DISTANCE = 50
MAX_DISTANCE = 2000
MAX_PRESS_MS = 2500
BOARD_WIDTH = 80
# 落地后不再盲等固定毫秒：连续两帧差不多一样就算动画停了，比固定等待快一倍以上
# 实测落地镜头推到静止约 320~500ms，所以首次等待直接给 380ms，多数局拍两张就能确认
SETTLE_MIN_MS = 380
SETTLE_MAX_MS = 2600
SETTLE_POLL_MS = 60
STABLE_DELTA = 2.5


def clamp(value, low, high):
    """把参数夹到安全区间"""
    return max(low, min(high, value))


def is_piece(r, g, b):
    """棋子底座的 RGB 特征（跳一跳经典配色）"""
    return (PIECE_R[0] <= r <= PIECE_R[1]) and (PIECE_G[0] <= g <= PIECE_G[1]) \
        and (PIECE_B[0] <= b <= PIECE_B[1])


def find_piece(image):
    """找棋子：扫描中段区域，取特征色平均 X 与最下沿 Y"""
    width, height = image.size
    pixels = image.load()
    scan_top = int(height * SCAN_TOP_RATIO)
    scan_bottom = int(height * SCAN_BOTTOM_RATIO)
    border = int(width / 8)
    x_sum = 0
    count = 0
    y_max = 0
    for y in range(scan_top, scan_bottom):
        for x in range(border, width - border):
            r, g, b = pixels[x, y][:3]
            if is_piece(r, g, b):
                x_sum += x
                count += 1
                if y > y_max:
                    y_max = y
    if not count:
        return None
    return int(x_sum / count), int(y_max - PIECE_BOTTOM_OFFSET)


def find_target(image, piece):
    """找目标方块：从上往下找第一行「非背景」像素，再左右扫出方块中心"""
    width, height = image.size
    pixels = image.load()
    piece_x, piece_y = piece
    scan_top = int(height * SCAN_TOP_RATIO)
    scan_bottom = min(piece_y - 50, height)
    if scan_bottom <= scan_top:
        return None
    top_y = 0
    for y in range(scan_top, scan_bottom):
        background = pixels[10, y][:3]
        hits = 0
        for x in range(10, width - 10):
            if abs(x - piece_x) < BOARD_WIDTH:
                continue
            px = pixels[x, y][:3]
            if abs(px[0] - background[0]) + abs(px[1] - background[1]) \
                    + abs(px[2] - background[2]) > BG_DIFF_THRESHOLD:
                hits += 1
        if hits > 20:
            top_y = y
            break
    if not top_y:
        return None
    background = pixels[10, top_y][:3]
    left = None
    right = None
    for x in range(10, width - 10):
        if abs(x - piece_x) < BOARD_WIDTH:
            continue
        px = pixels[x, top_y][:3]
        if abs(px[0] - background[0]) + abs(px[1] - background[1]) \
                + abs(px[2] - background[2]) > BG_DIFF_THRESHOLD:
            left = x
            break
    if left is None:
        return None
    for x in range(width - 11, 9, -1):
        if abs(x - piece_x) < BOARD_WIDTH:
            continue
        px = pixels[x, top_y][:3]
        if abs(px[0] - background[0]) + abs(px[1] - background[1]) \
                + abs(px[2] - background[2]) > BG_DIFF_THRESHOLD:
            right = x
            break
    if right is None:
        return None
    block_width = right - left
    if block_width < 15 or block_width > 200:
        return None
    target_x = int((left + right) / 2)
    center_x = width / 2 + (24 / 1080) * width
    center_y = height / 2 + (17 / 1920) * height
    slope = 25.5 / 43.5
    if piece_x > center_x:
        target_y = round(slope * (target_x - center_x) + center_y)
    else:
        target_y = round(-slope * (target_x - center_x) + center_y)
    return target_x, target_y


def press_duration(distance, coeff, max_press):
    """把两点距离换算成长按毫秒数"""
    return int(min(max(distance * coeff, 100), max_press))


def frame_grab():
    """截一帧图；失败返回 None"""
    try:
        raw = cw_script.observe_image()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return cw_script.image_from_bytes(raw)
    except Exception:
        return None


def frame_delta(a, b):
    """两帧的平均像素差，完全一样是 0"""
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    stat = ImageStat.Stat(diff)
    return sum(stat.mean) / 3.0


def settled_image(min_ms, max_ms, poll_ms):
    """等画面不再动，返回那一帧。

    落地后镜头还会推一段，盲等固定毫秒要么太短（拍到半路）要么太长（每跳白等 2 秒）；
    这里改成连续两帧几乎一样就算停了，慢的局多等、快的局立刻走。
    """
    cw_script.wait(min_ms)
    spent = min_ms
    shots = 1
    shot_ms = 0.0
    at = time.time()
    prev = frame_grab()
    shot_ms += (time.time() - at) * 1000
    while spent < max_ms:
        cw_script.wait(poll_ms)
        spent += poll_ms
        shots += 1
        at = time.time()
        cur = frame_grab()
        shot_ms += (time.time() - at) * 1000
        if prev is not None and cur is not None and frame_delta(prev, cur) <= STABLE_DELTA:
            return cur, spent, shots, shot_ms
        if cur is not None:
            prev = cur
    return prev, spent, shots, shot_ms


def jump_once(index, coeff, max_press, settle_min, settle_max, poll_ms):
    """跳一次：等静止 → 找棋子与目标 → 长按；成功返回 True"""
    started = time.time()
    image, waited, shots, shot_ms = settled_image(settle_min, settle_max, poll_ms)
    if image is None:
        cw_script.log("第 %d 跳：截图失败" % (index + 1))
        return False
    width, height = image.size
    screen = cw_script.screen() or {}
    pixel = screen.get("pixel") or [width, height]
    kx = float(pixel[0]) / float(width)
    ky = float(pixel[1]) / float(height)
    piece = find_piece(image)
    if piece is None:
        cw_script.log("第 %d 跳：没找到棋子" % (index + 1))
        return False
    target = find_target(image, piece)
    if target is None:
        cw_script.log("第 %d 跳：没找到目标方块" % (index + 1))
        return False
    distance = math.hypot((piece[0] - target[0]) * kx, (piece[1] - target[1]) * ky)
    if distance < MIN_DISTANCE or distance > MAX_DISTANCE:
        cw_script.log("第 %d 跳：距离异常 %.0fpx" % (index + 1, distance))
        return False
    press = press_duration(distance, coeff, max_press)
    tap_x = int(round(piece[0] * kx))
    tap_y = int(round(piece[1] * ky))
    press_at = time.time()
    cw_script.long_press(tap_x, tap_y, press)
    total = (time.time() - started) * 1000
    cw_script.log("第 %d 跳：图(%d,%d)→(%d,%d) 设备(%d,%d) 距离 %.0fpx(设备) 按压 %dms 等静止 %dms/%d张(截图 %.0fms) 长按 %.0fms 本跳 %.0fms"
                  % (index + 1, piece[0], piece[1], target[0], target[1],
                     tap_x, tap_y, distance, press, waited, shots, shot_ms,
                     (time.time() - press_at) * 1000, total))
    return True


def run():
    """按参数反复跳：连续三次没找到棋子/目标就收手，随时响应停止"""
    options = cw_script.params()
    rounds = int(clamp(int(options.get("rounds", 20)), 1, 500))
    coeff = clamp(float(options.get("press_coeff", 1.15)), 0.5, 3.0)
    max_press = int(clamp(int(options.get("max_press_ms", MAX_PRESS_MS)), 100, 5000))
    settle_min = int(clamp(int(options.get("settle_min_ms", SETTLE_MIN_MS)), 0, 3000))
    settle_max = int(clamp(int(options.get("settle_max_ms", SETTLE_MAX_MS)), settle_min, 8000))
    poll_ms = int(clamp(int(options.get("settle_poll_ms", SETTLE_POLL_MS)), 20, 500))
    jumps = 0
    misses = 0
    started = time.time()
    for index in range(rounds):
        if cw_script.should_stop():
            cw_script.done(False, "主人喊停了，已跳 %d 下" % jumps)
            return
        if jump_once(index, coeff, max_press, settle_min, settle_max, poll_ms):
            jumps += 1
            misses = 0
            continue
        misses += 1
        if misses >= 3:
            cw_script.done(False, "连续 3 次没找到棋子/目标，先停")
            return
        cw_script.wait(300)
    elapsed = time.time() - started
    cw_script.done(True, "跳完了，共 %d 下，平均 %.2f 秒/下" % (jumps, elapsed / max(jumps, 1)))


if __name__ == "__main__":
    run()
