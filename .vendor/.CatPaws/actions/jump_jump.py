# actions/jump_jump_tf.py
"""
基于 TensorFlow 目标检测的跳一跳自动游玩
适配 CatPaws 框架（WDA 截图 + 长按动作）
"""
import asyncio
import json
import os
import sys
sys.path.insert(0, r"D:\.CatPaws\actions\object_detection")
sys.path.insert(0, r"D:\.CatPaws\actions\slim")
import numpy as np
import tensorflow as tf
from PIL import Image
import cv2

# 添加 utils 目录到 Python 路径（确保能导入）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'utils'))

from utils import label_map_util
from utils import visualization_utils as vis_util

from screen import get_screenshot

# ---------- 模型配置 ----------
PATH_TO_CKPT = os.path.join(os.path.dirname(__file__), 'frozen_inference_graph.pb')
PATH_TO_LABELS = os.path.join(os.path.dirname(__file__), 'wechat_jump_label_map.pbtxt')
NUM_CLASSES = 7

# 加载模型
detection_graph = tf.Graph()
with detection_graph.as_default():
    od_graph_def = tf.GraphDef()
    with tf.gfile.GFile(PATH_TO_CKPT, 'rb') as fid:
        od_graph_def.ParseFromString(fid.read())
        tf.import_graph_def(od_graph_def, name='')

# 加载标签
label_map = label_map_util.load_labelmap(PATH_TO_LABELS)
categories = label_map_util.convert_label_map_to_categories(
    label_map, max_num_classes=NUM_CLASSES, use_display_name=True)
category_index = label_map_util.create_category_index(categories)

# 按压系数（像素距离 → 毫秒）
PRESS_COEFF = 1.45   # 根据实测调整（增大跳更远，减小跳更近）
MAX_PRESS_MS = 2500

def preprocess_image(pil_img):
    """PIL Image → 模型输入 (9, H, W, 3) 及数据增强"""
    image_np = np.array(pil_img.convert('RGB'))
    H, W = image_np.shape[:2]
    images = np.ones((9, H, W, 3), dtype=np.uint8) * 255
    images[0, :int(0.95*H), :int(0.95*W), :] = image_np[int(0.05*H):, int(0.05*W):, :]
    images[1, :int(0.95*H), :, :] = image_np[int(0.05*H):, :, :]
    images[2, :int(0.95*H), int(0.05*W):, :] = image_np[int(0.05*H):, :int(0.95*W), :]
    images[3, :, :int(0.95*W), :] = image_np[:, int(0.05*W):, :]
    images[4, :, :, :] = image_np[:, :, :]
    images[5, :, int(0.05*W):, :] = image_np[:, :int(0.95*W), :]
    images[6, int(0.05*H):, :int(0.95*W), :] = image_np[:int(0.95*H), int(0.05*W):, :]
    images[7, int(0.05*H):, :, :] = image_np[:int(0.95*H), :, :]
    images[8, int(0.05*H):, int(0.05*W):, :] = image_np[:int(0.95*H), :int(0.95*W), :]
    return image_np, images, W, H

def process_boxes(boxes):
    """还原数据增强的平移偏移"""
    for i in range(boxes.shape[1]):
        boxes[0, i, 0] += 0.05; boxes[0, i, 1] += 0.05; boxes[0, i, 2] += 0.05; boxes[0, i, 3] += 0.05
        boxes[1, i, 0] += 0.05; boxes[1, i, 2] += 0.05
        boxes[2, i, 0] += 0.05; boxes[2, i, 1] -= 0.05; boxes[2, i, 2] += 0.05; boxes[2, i, 3] -= 0.05
        boxes[3, i, 1] += 0.05; boxes[3, i, 3] += 0.05
        boxes[5, i, 1] -= 0.05; boxes[5, i, 3] -= 0.05
        boxes[6, i, 0] -= 0.05; boxes[6, i, 1] += 0.05; boxes[6, i, 2] -= 0.05; boxes[6, i, 3] += 0.05
        boxes[7, i, 0] -= 0.05; boxes[7, i, 2] -= 0.05
        boxes[8, i, 0] -= 0.05; boxes[8, i, 1] -= 0.05; boxes[8, i, 2] -= 0.05; boxes[8, i, 3] -= 0.05
    return boxes

def get_positions(boxes, classes, scores, category_index):
    """从检测结果中提取棋子（chess）和最靠上的目标块"""
    chess_box = None
    target_box = None
    min_score = 0.5
    for i in range(len(scores)):
        if scores[i] < min_score:
            continue
        cat_name = category_index[classes[i]]['name']
        if cat_name == 'chess':
            chess_box = boxes[i]
        else:
            # 目标块：取最上方的（ymin 最小）
            if target_box is None or boxes[i][0] < target_box[0]:
                target_box = boxes[i]
    return chess_box, target_box

async def run(send=None):
    if send is None:
        print("❌ 没有 send 回调")
        return

    print("📲 激活微信跳一跳")
    await send(json.dumps({
        "type": "action",
        "action": "activate_app",
        "params": {"bundle_id": "com.tencent.xin"}
    }))
    await asyncio.sleep(2.0)
    print("🎮 TensorFlow 目标检测跳一跳启动")

    with detection_graph.as_default():
        with tf.Session(graph=detection_graph) as sess:
            image_tensor = detection_graph.get_tensor_by_name('image_tensor:0')
            detection_boxes = detection_graph.get_tensor_by_name('detection_boxes:0')
            detection_scores = detection_graph.get_tensor_by_name('detection_scores:0')
            detection_classes = detection_graph.get_tensor_by_name('detection_classes:0')
            num_detections = detection_graph.get_tensor_by_name('num_detections:0')

            while True:
                pil_img = get_screenshot()
                if pil_img is None:
                    print("❌ 截图失败")
                    await asyncio.sleep(1)
                    continue

                _, images, W, H = preprocess_image(pil_img)

                boxes, scores, classes, num = sess.run(
                    [detection_boxes, detection_scores, detection_classes, num_detections],
                    feed_dict={image_tensor: images}
                )
                boxes = process_boxes(boxes)
                boxes = np.reshape(boxes, (-1, boxes.shape[-1]))
                scores = np.reshape(scores, (-1))
                classes = np.reshape(classes, (-1)).astype(np.int32)

                chess_box, target_box = get_positions(boxes, classes, scores, category_index)
                if chess_box is None or target_box is None:
                    print("⚠️ 未检测到棋子或目标，重试")
                    await asyncio.sleep(0.8)
                    continue

                chess_x = (chess_box[1] + chess_box[3]) / 2.0
                target_x = (target_box[1] + target_box[3]) / 2.0
                dist_px = abs(chess_x - target_x) * W
                press_ms = int(dist_px * PRESS_COEFF)
                press_ms = min(press_ms, MAX_PRESS_MS)
                press_sec = press_ms / 1000.0

                print(f"🏃 距离 {dist_px:.0f}px → 按压 {press_sec:.3f}s")

                # 计算按压点（棋子底部中心）
                piece_y = int(chess_box[2] * H - 20)   # 底部上方20px
                piece_x = int(chess_x * W)
                action = {
                    "type": "action",
                    "action": "long_press",
                    "params": {
                        "x": piece_x,
                        "y": piece_y,
                        "duration": press_sec
                    }
                }
                await send(json.dumps(action))

                await asyncio.sleep(press_sec + 1.5 + np.random.uniform(0, 0.2))