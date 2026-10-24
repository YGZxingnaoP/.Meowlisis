"""
WDA 原生客户端
直接使用 WDA 标准 W3C Actions API 发送手势，无需手机端自定义代码。

坐标说明：
    WDA 使用逻辑点（point），非像素。
    像素 → 逻辑点: point = pixel / scale
    本模块提供 tap_pixel/swipe_pixel/long_press_pixel 等便捷方法，自动转换。
"""
import base64
import io
import requests
from typing import Optional, Tuple
from PIL import Image
from screen import coord_system, receiver


class WDANativeClient:
    """
    WDA 原生客户端，通过标准 HTTP 接口控制 iOS 设备。

    用法：
        client = WDANativeClient("192.168.1.100")
        client.create_session()
        client.tap(200, 300)          # 逻辑点坐标
        client.tap_pixel(600, 900)    # 像素坐标（自动转换）
    """

    def __init__(self, phone_ip: str, port: int = 8100):
        self.phone_ip = phone_ip
        self.port = port
        self.base_url = f"http://{phone_ip}:{port}"
        self.session_id: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.timeout = 5

    # ---- 会话管理 ----

    def create_session(self) -> bool:
        """创建 WDA 会话（必须在使用手势前调用一次）"""
        try:
            resp = self.session.post(
                f"{self.base_url}/session",
                json={"capabilities": {}},
                timeout=self.timeout
            )
            if resp.status_code == 200:
                data = resp.json()
                self.session_id = data.get("sessionId") or data.get("value", {}).get("sessionId")
                print(f"✅ WDA 会话已创建: {self.session_id}")
                # 注册截图 provider，让 screen 模块的 get_screenshot() 可用
                from screen import set_screenshot_provider
                set_screenshot_provider(self.screenshot)
                # 自动检测 scale
                self._detect_scale()
                return True
            else:
                print(f"❌ 创建会话失败: {resp.text}")
                return False
        except Exception as e:
            print(f"❌ 创建会话异常: {e}")
            return False

    def _detect_scale(self):
        """通过 WDA 获取逻辑尺寸，结合截图尺寸自动计算 scale"""
        try:
            w, h = self.get_screen_size()
            if w and w > 0:
                sw, sh = receiver.get_dimensions()
                if sw > 0:
                    scale = round(sw / w, 1)
                    receiver.set_scale(scale)
                    print(f"📐 WDA 原生检测: 逻辑 {w}x{h}pt, scale={scale}x")
                else:
                    print(f"📐 WDA 逻辑尺寸: {w}x{h}pt（等待截图以计算 scale）")
        except Exception as e:
            print(f"⚠️ scale 检测失败: {e}")

    @property
    def is_available(self) -> bool:
        """检查 WDA 是否可达"""
        try:
            resp = self.session.get(f"{self.base_url}/status", timeout=1)
            return resp.status_code == 200
        except Exception:
            return False

    @property
    def has_session(self) -> bool:
        """是否已有活跃会话"""
        return self.session_id is not None

    # ---- 屏幕信息 ----

    def get_screen_size(self) -> Tuple[Optional[int], Optional[int]]:
        """获取屏幕逻辑尺寸 (width, height) 单位：point"""
        try:
            resp = self.session.get(f"{self.base_url}/window/size", timeout=2)
            if resp.status_code == 200:
                size = resp.json()["value"]
                return size["width"], size["height"]
        except Exception as e:
            print(f"⚠️ 获取屏幕尺寸失败: {e}")
        return None, None

    def screenshot(self, retries: int = 2) -> Optional[Image.Image]:
        """
        截图，返回 PIL Image。
        兼容两种响应格式，遇到快照错误自动重试。
        """
        import time
        url = f"{self.base_url}/screenshot"
        for attempt in range(retries + 1):
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code != 200:
                    print(f"⚠️ 截图失败: HTTP {resp.status_code}")
                    if attempt < retries:
                        time.sleep(0.5)
                    continue

                data = resp.json()

                # 兼容两种响应格式
                img_b64 = None
                if 'value' in data:
                    img_b64 = data['value']
                    # 如果 value 是字典且包含 data 字段，则取 data
                    if isinstance(img_b64, dict) and 'data' in img_b64:
                        img_b64 = img_b64['data']

                if not img_b64:
                    print(f"⚠️ 截图响应无数据")
                    if attempt < retries:
                        time.sleep(0.5)
                    continue

                img_data = base64.b64decode(img_b64)
                return Image.open(io.BytesIO(img_data))

            except Exception as e:
                print(f"❌ 截图异常: {e}")
                if attempt < retries:
                    time.sleep(0.5)
        return None

    # ---- W3C Actions 手势（逻辑点坐标） ----

    def _send_actions(self, actions_list: list) -> bool:
        """发送 W3C Actions 到 WDA"""
        if not self.session_id:
            print("❌ 请先调用 create_session()")
            return False
        url = f"{self.base_url}/session/{self.session_id}/actions"
        payload = {"actions": actions_list}
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            if resp.status_code == 200:
                return True
            print(f"⚠️ Actions 失败: HTTP {resp.status_code} - {resp.text[:100]}")
            return False
        except Exception as e:
            print(f"❌ Actions 异常: {e}")
            return False

    def _pointer_actions(self, action_steps: list) -> list:
        """构造标准 pointer actions 列表"""
        return [{
            "id": "finger",
            "type": "pointer",
            "parameters": {"pointerType": "touch"},
            "actions": action_steps
        }]

    def tap(self, x: int, y: int) -> bool:
        """点击（逻辑点坐标）"""
        steps = [
            {"type": "pointerMove", "x": x, "y": y},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerUp", "button": 0}
        ]
        return self._send_actions(self._pointer_actions(steps))

    def long_press(self, x: int, y: int, duration: float) -> bool:
        """长按（逻辑点坐标，duration 单位：秒）"""
        steps = [
            {"type": "pointerMove", "x": x, "y": y},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": int(duration * 1000)},
            {"type": "pointerUp", "button": 0}
        ]
        return self._send_actions(self._pointer_actions(steps))

    def swipe(self, from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.5) -> bool:
        """滑动（逻辑点坐标，duration 单位：秒）"""
        steps_count = max(int(duration * 60), 5)  # 60fps 采样
        steps = [
            {"type": "pointerMove", "x": from_x, "y": from_y},
            {"type": "pointerDown", "button": 0}
        ]
        for i in range(1, steps_count + 1):
            ix = int(from_x + (to_x - from_x) * i / steps_count)
            iy = int(from_y + (to_y - from_y) * i / steps_count)
            steps.append({"type": "pointerMove", "x": ix, "y": iy})
        steps.append({"type": "pointerUp", "button": 0})
        return self._send_actions(self._pointer_actions(steps))

    def repeated_tap(self, x: int, y: int, times: int, interval: float) -> bool:
        """连续点击"""
        import time
        for i in range(times):
            if not self.tap(x, y):
                return False
            if i < times - 1:
                time.sleep(interval)
        return True

    # ---- 像素坐标便捷方法（自动转换） ----

    def tap_pixel(self, px: int, py: int) -> bool:
        """点击（像素坐标，自动转为逻辑点）"""
        lx, ly = coord_system.to_point(px, py)
        return self.tap(lx, ly)

    def long_press_pixel(self, px: int, py: int, duration: float) -> bool:
        """长按（像素坐标）"""
        lx, ly = coord_system.to_point(px, py)
        return self.long_press(lx, ly, duration)

    def swipe_pixel(self, fx: int, fy: int, tx: int, ty: int, duration: float = 0.5) -> bool:
        """滑动（像素坐标）"""
        lfx, lfy = coord_system.to_point(fx, fy)
        ltx, lty = coord_system.to_point(tx, ty)
        return self.swipe(lfx, lfy, ltx, lty, duration)

    # ---- 应用管理 ----

    def launch_app(self, bundle_id: str) -> bool:
        """启动应用，如 'com.apple.calculator'"""
        # 尝试多个可能的端点
        endpoints = [
            f"{self.base_url}/wda/apps/launch",
        ]
        if self.session_id:
            endpoints.insert(0, f"{self.base_url}/session/{self.session_id}/wda/apps/launch")

        for url in endpoints:
            try:
                resp = self.session.post(url, json={"bundleId": bundle_id}, timeout=self.timeout)
                if resp.status_code == 200:
                    print(f"✅ 已启动应用: {bundle_id}")
                    return True
            except Exception:
                pass

        print(f"⚠️ 无法通过 WDA 启动应用 {bundle_id}，请手动打开")
        return False

    def activate_app(self, bundle_id: str) -> bool:
        """
        激活应用（确保在前台）。
        尝试多种 WDA 端点，全部失败时仅警告不报错。
        """
        # 尝试多个可能的端点
        endpoints = [
            f"{self.base_url}/wda/apps/activate",
            f"{self.base_url}/wda/apps/launch",
        ]
        if self.session_id:
            endpoints.insert(0, f"{self.base_url}/session/{self.session_id}/wda/apps/activate")
            endpoints.insert(1, f"{self.base_url}/session/{self.session_id}/wda/apps/launch")

        for url in endpoints:
            try:
                resp = self.session.post(url, json={"bundleId": bundle_id}, timeout=self.timeout)
                if resp.status_code == 200:
                    print(f"✅ 已激活应用: {bundle_id}")
                    return True
            except Exception:
                pass

        print(f"⚠️ WDA 不支持应用激活接口，请确保 {bundle_id} 已在前台")
        return True  # 返回 True 不阻断脚本执行

    # ---- 资源管理 ----

    def delete_session(self):
        """删除 WDA 会话"""
        if self.session_id:
            try:
                self.session.delete(
                    f"{self.base_url}/session/{self.session_id}",
                    timeout=2
                )
                print(f"🗑️ WDA 会话已删除: {self.session_id}")
            except Exception:
                pass
            self.session_id = None

    def close(self):
        """关闭客户端"""
        self.delete_session()
        self.session.close()


# ---- 全局单例 ----
_wda_client: Optional[WDANativeClient] = None


def get_wda_client() -> Optional[WDANativeClient]:
    """获取全局 WDA 原生客户端"""
    return _wda_client


def init_wda_client(phone_ip: str, port: int = 8100) -> bool:
    """初始化 WDA 原生客户端并创建会话"""
    global _wda_client
    if _wda_client:
        _wda_client.close()
    _wda_client = WDANativeClient(phone_ip, port)
    if _wda_client.create_session():
        print(f"✅ WDA 原生客户端已初始化: {_wda_client.base_url}")
        return True
    print(f"❌ WDA 原生客户端初始化失败")
    return False


def wda_tap(x: int, y: int) -> bool:
    """便捷：点击（像素坐标，自动转换）"""
    if _wda_client:
        return _wda_client.tap_pixel(x, y)
    return False


def wda_long_press(x: int, y: int, duration: float) -> bool:
    """便捷：长按（像素坐标）"""
    if _wda_client:
        return _wda_client.long_press_pixel(x, y, duration)
    return False


def wda_swipe(fx: int, fy: int, tx: int, ty: int, duration: float = 0.5) -> bool:
    """便捷：滑动（像素坐标）"""
    if _wda_client:
        return _wda_client.swipe_pixel(fx, fy, tx, ty, duration)
    return False


def wda_screenshot() -> Optional[Image.Image]:
    """便捷：截图"""
    if _wda_client:
        return _wda_client.screenshot()
    return None


def wda_launch_app(bundle_id: str) -> bool:
    """便捷：启动应用"""
    if _wda_client:
        return _wda_client.launch_app(bundle_id)
    return False


def wda_activate_app(bundle_id: str) -> bool:
    """便捷：激活应用（确保在前台）"""
    if _wda_client:
        return _wda_client.activate_app(bundle_id)
    return False

