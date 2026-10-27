"""
跳一跳 - 纯CV算法版（运行在TF环境中）

使用经典 wechat_jump 算法：
  - 棋子：逐行扫描 RGB 特征色，取平均 X 和最大 Y
  - 目标：从屏幕顶部往下扫描，找第一个非背景色行，精确计算方块中心

通过 stdout 输出 JSON 动作指令给主进程。
支持 Ctrl+C 或收到 stop 信号时优雅退出。
"""
import os
import sys
import time
import json
import random
import math
import signal
from PIL import Image

# ========== 配置 ==========
SCREENSHOT_FILE = "current_screenshot.png"
SCREENSHOT_REQUEST_FILE = "screenshot_request.flag"  # 截图请求标志文件
PRESS_COEFF = 1.15       # 按压系数（毫秒/像素）
MAX_PRESS_MS = 2500
MIN_DISTANCE = 50
MAX_DISTANCE = 2000

CONFIG = {
    "piece_r": (50, 60),
    "piece_g": (53, 63),
    "piece_b": (95, 110),
    "piece_bottom_offset": 20,
    "scan_top_ratio": 0.25,
    "scan_bottom_ratio": 0.70,
    "bg_diff_threshold": 10,
}


# ========== 全局状态 ==========
running = True  # 脚本运行标志

def signal_handler(signum, frame):
    """处理停止信号"""
    global running
    print("\n[jump_jump_tf] 🛑 收到停止信号，正在退出...", file=sys.stderr)
    running = False

# 注册信号处理器
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill 命令


def request_screenshot():
    """请求主进程截图（通过创建标志文件）"""
    try:
        # 删除旧的标志文件（如果存在）
        if os.path.exists(SCREENSHOT_REQUEST_FILE):
            os.remove(SCREENSHOT_REQUEST_FILE)
        
        # 创建新的标志文件，包含时间戳
        with open(SCREENSHOT_REQUEST_FILE, 'w') as f:
            f.write(str(time.time()))
        
        # 等待主进程完成截图（最多等2秒）
        for _ in range(40):  # 40次 * 50ms = 2秒
            time.sleep(0.05)
            if os.path.exists(SCREENSHOT_FILE):
                # 检查截图是否是新创建的
                screenshot_mtime = os.path.getmtime(SCREENSHOT_FILE)
                if time.time() - screenshot_mtime < 1:  # 1秒内创建的
                    return True
        
        print(f"[jump_jump_tf] WARNING: Screenshot timeout after request", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[jump_jump_tf] ERROR: Failed to request screenshot: {e}", file=sys.stderr)
        return False


def get_screenshot_from_file():
    """从主进程保存的文件读取截图（带重试和时间戳检查）"""
    max_wait = 10
    waited = 0
    while not os.path.exists(SCREENSHOT_FILE) and waited < max_wait:
        time.sleep(0.1)
        waited += 0.1
    
    if not os.path.exists(SCREENSHOT_FILE):
        return None
    
    for retry in range(3):
        try:
            # 检查文件修改时间，确保是最新的（5秒内）
            file_mtime = os.path.getmtime(SCREENSHOT_FILE)
            current_time = time.time()
            if current_time - file_mtime > 5:
                print(f"[jump_jump_tf] WARNING: Screenshot is too old ({current_time - file_mtime:.1f}s)", file=sys.stderr)
            
            img = Image.open(SCREENSHOT_FILE)
            img.load()  # 触发完整性检查
            return img
        except Exception as e:
            if retry < 2:
                time.sleep(0.1)  # 缩短重试间隔
                continue
            else:
                print(f"[jump_jump_tf] ❌ 读取截图失败: {e}", file=sys.stderr)
                return None


def _is_piece_pixel(r, g, b):
    """判断像素是否为棋子颜色"""
    pr = CONFIG["piece_r"]
    pg = CONFIG["piece_g"]
    pb = CONFIG["piece_b"]
    return (pr[0] <= r <= pr[1]) and (pg[0] <= g <= pg[1]) and (pb[0] <= b <= pb[1])


def _rgb2hsv(r, g, b):
    """RGB转HSV色彩空间"""
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    df = mx - mn
    if mx == mn:
        h = 0
    elif mx == r:
        h = (60 * ((g - b) / df) + 360) % 360
    elif mx == g:
        h = (60 * ((b - r) / df) + 120) % 360
    elif mx == b:
        h = (60 * ((r - g) / df) + 240) % 360
    if mx == 0:
        s = 0
    else:
        s = df / mx
    v = mx
    return h, s, v


def _hsv2rgb(h, s, v):
    """HSV转RGB色彩空间"""
    h = float(h)
    s = float(s)
    v = float(v)
    h60 = h / 60.0
    h60f = math.floor(h60)
    hi = int(h60f) % 6
    f = h60 - h60f
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = 0, 0, 0
    if hi == 0:
        r, g, b = v, t, p
    elif hi == 1:
        r, g, b = q, v, p
    elif hi == 2:
        r, g, b = p, v, t
    elif hi == 3:
        r, g, b = p, q, v
    elif hi == 4:
        r, g, b = t, p, v
    elif hi == 5:
        r, g, b = v, p, q
    r, g, b = int(r * 255), int(g * 255), int(b * 255)
    return r, g, b


def find_piece(img: Image.Image):
    """
    逐行扫描找棋子底部中心。
    返回 (x, y) 像素坐标，失败返回 (0, 0)。
    """
    w, h = img.size
    pixels = img.load()

    scan_top = int(h * CONFIG["scan_top_ratio"])
    scan_bottom = int(h * CONFIG["scan_bottom_ratio"])
    x_border = int(w / 8)

    piece_x_sum = 0
    piece_x_count = 0
    piece_y_max = 0

    for y in range(scan_top, scan_bottom):
        for x in range(x_border, w - x_border):
            r, g, b = pixels[x, y][:3]
            if _is_piece_pixel(r, g, b):
                piece_x_sum += x
                piece_x_count += 1
                piece_y_max = max(piece_y_max, y)

    if piece_x_count == 0:
        return (0, 0)

    piece_x = piece_x_sum / piece_x_count
    piece_y = piece_y_max - CONFIG["piece_bottom_offset"]
    return (int(piece_x), int(piece_y))


def find_target(img: Image.Image, piece_x, piece_y):
    """
    从屏幕顶部往下逐行扫描，找到第一个非背景色像素的行（即下一个方块顶面）。
    排除棋子所在列，避免误检棋子本身。
    然后计算方块左右边界取中心 X，并向下找到方块底面取中心 Y。
    返回 (x, y) 像素坐标，失败返回 (0, 0)。
    """
    w, h = img.size
    pixels = img.load()

    scan_top = int(h * CONFIG["scan_top_ratio"])
    scan_bottom = piece_y - 50
    piece_body_width = 80

    if scan_bottom <= scan_top:
        return (0, 0)

    # 从顶部往下扫描，找第一个有色变行
    target_top_y = 0
    for y in range(scan_top, scan_bottom):
        bg = pixels[10, y][:3]

        non_bg_count = 0
        x_sum = 0
        x_count = 0

        for x in range(10, w - 10):
            if abs(x - piece_x) < piece_body_width:
                continue

            px = pixels[x, y][:3]
            diff = abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2])
            if diff > CONFIG["bg_diff_threshold"]:
                non_bg_count += 1
                x_sum += x
                x_count += 1

        # 该行有足够多的非背景像素 → 这是目标方块顶面
        # 关键改进：提高阈值，避免检测到间隔区域
        if non_bg_count > 20 and x_count > 0:  # 从30降到20，放宽条件
            # 额外检查：目标宽度必须合理（至少15像素）
            if x_count >= 15:  # 从20降到15
                target_top_y = y
                break

    if target_top_y == 0:
        return (0, 0)

    # 计算目标 X 中心 - 简单背景色检测
    bg = pixels[10, target_top_y][:3]
    left_edge = None
    right_edge = None
    
    # 从左到右扫描找左边缘
    for x in range(10, w - 10):
        if abs(x - piece_x) < piece_body_width:
            continue
        px = pixels[x, target_top_y][:3]
        diff = abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2])
        if diff > CONFIG["bg_diff_threshold"]:
            left_edge = x
            break
    
    # 从右到左扫描找右边缘
    if left_edge is not None:
        for x in range(w - 11, 9, -1):
            if abs(x - piece_x) < piece_body_width:
                continue
            px = pixels[x, target_top_y][:3]
            diff = abs(px[0] - bg[0]) + abs(px[1] - bg[1]) + abs(px[2] - bg[2])
            if diff > CONFIG["bg_diff_threshold"]:
                right_edge = x
                break

    if left_edge is None or right_edge is None:
        return (0, 0)

    target_x = int((left_edge + right_edge) / 2)
    block_width = right_edge - left_edge
    
    # 关键改进：检查方块宽度是否合理（太小可能是误检）
    if block_width < 15 or block_width > 200:
        print(f"[jump_jump_tf] WARNING: Target width abnormal: {block_width}px", file=sys.stderr)
        return (0, 0)

    # 使用对称中心投影法计算目标 Y 坐标
    # 参考经典 wechat_jump 算法，基于游戏透视角度
    center_x = w / 2 + (24 / 1080) * w
    center_y = h / 2 + (17 / 1920) * h
    slope = 25.5 / 43.5  # 约 0.586，接近 tan(30°)
    
    if piece_x > center_x:
        target_center_y = round(slope * (target_x - center_x) + center_y)
    else:
        target_center_y = round(-slope * (target_x - center_x) + center_y)

    return (target_x, target_center_y)


def send_action(action_dict):
    """输出 JSON 动作到 stdout"""
    print(json.dumps(action_dict))
    sys.stdout.flush()


def main():
    """主循环"""
    global running
    print("[jump_jump_tf] CV jump script started", file=sys.stderr)
    print("[jump_jump_tf] Press Ctrl+C or send SIGTERM to stop", file=sys.stderr)
    
    loop_count = 0
    while running:
        loop_start_time = time.time()
        
        pil_img = get_screenshot_from_file()
        if pil_img is None:
            print("[jump_jump_tf] WARNING: No screenshot, waiting...", file=sys.stderr)
            time.sleep(0.5)
            continue
        
        W, H = pil_img.size
        
        # 1. 找棋子
        piece_x, piece_y = find_piece(pil_img)
        if piece_x == 0:
            print(f"[jump_jump_tf] WARNING: Piece not found (W={W}, H={H})", file=sys.stderr)
            time.sleep(0.8)
            continue
        
        # 2. 找目标
        target_x, target_y = find_target(pil_img, piece_x, piece_y)
        if target_x == 0:
            print(f"[jump_jump_tf] WARNING: Target not found (piece at {piece_x},{piece_y})", file=sys.stderr)
            time.sleep(0.8)
            continue
        
        # 3. 计算距离（欧几里得距离）
        dist_px = math.sqrt((piece_x - target_x)**2 + (piece_y - target_y)**2)
        if dist_px < MIN_DISTANCE or dist_px > MAX_DISTANCE:
            print(f"[jump_jump_tf] WARNING: Distance abnormal: {dist_px:.0f}px", file=sys.stderr)
            time.sleep(0.8)
            continue
        
        # 4. 计算按压时间
        press_ms = int(dist_px * PRESS_COEFF)
        press_ms = min(press_ms, MAX_PRESS_MS)
        press_sec = press_ms / 1000.0
        
        loop_elapsed = time.time() - loop_start_time
        print(f"[jump_jump_tf] Jump #{loop_count+1}: piece({piece_x},{piece_y}) -> target({target_x},{target_y}) dist={dist_px:.0f}px press={press_sec:.3f}s (loop={loop_elapsed:.2f}s)", file=sys.stderr)
        loop_count += 1
        
        # 5. 发送长按动作
        action = {
            "type": "action",
            "action": "long_press",
            "params": {
                "x": int(piece_x),
                "y": int(piece_y),
                "duration": float(press_sec)
            }
        }
        send_action(action)
        
        # 等待跳跃落地 + 动画结束
        # press_sec: 按压时间
        # 1.8s: 跳跃飞行时间（从起跳到完全落地）
        # 0.5s: 额外缓冲，确保游戏完全静止
        # random: 轻微随机化避免节奏过于机械
        wait_time = press_sec + 1.8 + 0.5 + random.uniform(0, 0.2)
        print(f"[jump_jump_tf] Waiting {wait_time:.2f}s for jump animation...", file=sys.stderr)
        time.sleep(wait_time)
        
        # 【关键】落地冷却时间：额外等待2秒，确保游戏完全静止
        cooldown_time = 2.0
        print(f"[jump_jump_tf] Cooldown: waiting {cooldown_time:.1f}s before screenshot...", file=sys.stderr)
        time.sleep(cooldown_time)
        
        # 冷却完成后，请求新的截图（带重试）
        screenshot_ok = False
        for retry in range(3):  # 最多重试3次
            print(f"[jump_jump_tf] Requesting new screenshot (attempt {retry+1})...", file=sys.stderr)
            if request_screenshot():
                screenshot_ok = True
                break
            else:
                print(f"[jump_jump_tf] WARNING: Screenshot request failed, retrying...", file=sys.stderr)
                time.sleep(1.0)  # 重试前等待1秒
        
        if not screenshot_ok:
            print(f"[jump_jump_tf] ERROR: Failed to get new screenshot after 3 retries, exiting...", file=sys.stderr)
            sys.exit(1)  # 退出脚本，避免使用旧图


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[jump_jump_tf] User interrupted, exiting", file=sys.stderr)
    except Exception as e:
        print(f"[jump_jump_tf] ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
    finally:
        # 清理资源
        print("[jump_jump_tf] Script stopped", file=sys.stderr)
        sys.exit(0)
