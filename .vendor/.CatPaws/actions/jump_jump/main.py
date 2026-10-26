import math
import random
import time

import cw_script

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


def is_piece(r, g, b):
    return (PIECE_R[0] <= r <= PIECE_R[1]) and (PIECE_G[0] <= g <= PIECE_G[1]) \
        and (PIECE_B[0] <= b <= PIECE_B[1])


def find_piece(image):
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


def find_target(image, piece_x, piece_y):
    width, height = image.size
    pixels = image.load()
    scan_top = int(height * SCAN_TOP_RATIO)
    scan_bottom = piece_y - 50
    body_width = 80
    if scan_bottom <= scan_top:
        return None
    top_y = 0
    for y in range(scan_top, scan_bottom):
        bg = pixels[10, y][:3]
        non_bg = 0
        x_count = 0
        for x in range(10, width - 10):
            if abs(x - piece_x) < body_width:
                continue
            px = pixels[x, y][:3]
            if abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2]) > BG_DIFF_THRESHOLD:
                non_bg += 1
                x_count += 1
        if non_bg > 20 and x_count >= 15:
            top_y = y
            break
    if not top_y:
        return None
    bg = pixels[10, top_y][:3]
    left = None
    right = None
    for x in range(10, width - 10):
        if abs(x - piece_x) < body_width:
            continue
        px = pixels[x, top_y][:3]
        if abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2]) > BG_DIFF_THRESHOLD:
            left = x
            break
    if left is None:
        return None
    for x in range(width - 11, 9, -1):
        if abs(x - piece_x) < body_width:
            continue
        px = pixels[x, top_y][:3]
        if abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2]) > BG_DIFF_THRESHOLD:
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


def run():
    options = cw_script.params()
    rounds = int(options.get("rounds", 20))
    coeff = float(options.get("press_coeff", 1.15))
    max_press = int(options.get("max_press_ms", MAX_PRESS_MS))
    for index in range(rounds):
        if cw_script.should_stop():
            cw_script.done(False, "用户停止")
            return
        raw = cw_script.observe_image()
        if not raw:
            cw_script.log("截图失败")
            time.sleep(0.8)
            continue
        try:
            image = cw_script.image_from_bytes(raw)
        except Exception as exc:
            cw_script.log("截图解码失败：%s" % exc)
            time.sleep(0.8)
            continue
        piece = find_piece(image)
        if piece is None:
            cw_script.log("棋子未找到")
            time.sleep(0.8)
            continue
        target = find_target(image, piece[0], piece[1])
        if target is None:
            cw_script.log("目标未找到")
            time.sleep(0.8)
            continue
        distance = math.hypot(piece[0] - target[0], piece[1] - target[1])
        if distance < MIN_DISTANCE or distance > MAX_DISTANCE:
            cw_script.log("距离异常：%.0fpx" % distance)
            time.sleep(0.8)
            continue
        press = min(int(distance * coeff), max_press)
        cw_script.log("第 %d 跳：棋子(%s,%s) → 目标(%s,%s) 距离 %.0f 按压 %dms"
                      % (index + 1, piece[0], piece[1], target[0], target[1], distance, press))
        cw_script.long_press(piece[0], piece[1], press)
        cw_script.wait(int(press + 2300 + random.uniform(0, 200)))
    cw_script.done(True, "完成 %d 跳" % rounds)


run()
