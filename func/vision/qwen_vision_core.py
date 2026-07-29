# -*- coding: utf-8 -*-
import threading
import time
import io
import base64
import os
from openai import OpenAI
from PIL import ImageGrab, Image
from func.log.default_log import DefaultLog
from func.config.default_config import defaultConfig


class QwenVisionCore:
    """
    仅负责截图并使用 Qwen 视觉模型生成图片描述。
    描述文本经优化后，通过 llm_core 发送给 LLM 进行统一回复处理。
    """
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = defaultConfig().get_config()
        vision_config = self.config.get('vision', {})
        qwen_config = vision_config.get('qwen', {})

        self.enabled = qwen_config.get('enabled', False)
        self.api_key = qwen_config.get('api_key', os.getenv("DASHSCOPE_API_KEY", ""))
        self.base_url = qwen_config.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model = qwen_config.get('model', "qwen-vl-max")
        self.prompt = qwen_config.get('prompt', "描述一下图片内容，简洁精准")
        self.max_tokens = qwen_config.get('max_tokens', 200)
        self.temperature = qwen_config.get('temperature', 0.6)

        # 触发关键词
        self.keywords = qwen_config.get('keywords', [
            "主人在干什么", "看看主人的电脑界面", "看看主人的屏幕",
            "看看屏幕", "看屏幕", "看一下屏幕"
        ])
        self.cooldown = qwen_config.get('cooldown', 10)
        self.last_trigger_time = 0
        self._task_running = False
        self._lock = threading.Lock()

        # 优化配置
        optimize_config = vision_config.get('optimize', {})
        self.optimize_enabled = optimize_config.get('enabled', False)
        self.optimize_api_key = optimize_config.get('api_key', self.api_key)
        self.optimize_base_url = optimize_config.get('base_url', self.base_url)
        self.optimize_model = optimize_config.get('model', 'qwen-plus')
        self.optimize_prompt_template = optimize_config.get('prompt_template',
            "把如下内容整合成简短准确的口语化概述，客观实际，不要有任何主观内容：\n{description}，60字左右。")
        self.optimize_max_tokens = optimize_config.get('max_tokens', 300)
        self.optimize_temperature = optimize_config.get('temperature', 0.5)

        # 外部引用
        self.llm_core = None   # 在 LLmCore 初始化时设置
        self.username = None
        self.uid = None

        # 初始化客户端
        self.client = self._create_client(self.api_key, self.base_url, 30.0)
        self.optimize_client = None
        if self.optimize_enabled:
            if self.optimize_api_key == self.api_key and self.optimize_base_url == self.base_url:
                self.optimize_client = self.client
            else:
                self.optimize_client = self._create_client(
                    self.optimize_api_key, self.optimize_base_url, 45.0
                )

    def _create_client(self, api_key, base_url, timeout):
        if not api_key:
            return None
        try:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
            self.log.info(f"视觉客户端已创建, base_url={base_url}")
            return client
        except Exception as e:
            self.log.error(f"创建视觉客户端失败: {e}")
            return None

    def get_screenshot_base64(self):
        """截图并缩放到 1024x1024，返回 data URI"""
        try:
            screenshot = ImageGrab.grab()
            screenshot.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            img_byte_arr = io.BytesIO()
            screenshot.save(img_byte_arr, format='JPEG', quality=85)
            img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
            return f"data:image/jpeg;base64,{img_base64}"
        except Exception as e:
            self.log.error(f"截图失败: {e}")
            return None

    def call_qwen_vision(self, image_data_uri):
        """调用 Qwen 视觉模型返回图片描述"""
        if not self.client:
            return None
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_uri}},
                        {"type": "text", "text": self.prompt}
                    ]
                }],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            return completion.choices[0].message.content
        except Exception as e:
            self.log.error(f"调用 Qwen 视觉模型异常: {e}")
            return None

    def optimize_text(self, text):
        """调用优化模型精简描述"""
        if not self.optimize_client:
            return text
        prompt = self.optimize_prompt_template.format(description=text)
        try:
            completion = self.optimize_client.chat.completions.create(
                model=self.optimize_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.optimize_max_tokens,
                temperature=self.optimize_temperature
            )
            optimized = completion.choices[0].message.content
            self.log.info(f"优化后描述: {optimized}")
            return optimized
        except Exception as e:
            self.log.error(f"优化失败: {e}")
            return text

    def run_once(self, traceid=None, original_query=None):
        """
        执行一次视觉任务：
        1. 截图
        2. Qwen VL 描述
        3. 优化（可选）
        4. 将描述包装为消息发送给 LLmCore 处理
        """
        if not self.llm_core:
            self.log.error("llm_core 未设置，无法发送消息")
            return

        # 缓冲提示语
        self.llm_core.ttsCore.tts_say("让喵呜看看～")

        img_uri = self.get_screenshot_base64()
        if not img_uri:
            return

        caption = self.call_qwen_vision(img_uri)
        if not caption:
            self.log.warning("未获取到视觉描述")
            return

        self.log.info(f"Qwen 描述: {caption}")

        if self.optimize_enabled:
            caption = self.optimize_text(caption)

        # 构造消息，交给 LLM 处理
        if original_query:
            msg = f"[视觉触发] 用户问：{original_query}\n屏幕内容：{caption}"
        else:
            msg = f"[视觉触发] 屏幕内容：{caption}"

        # 通过 add_system_message 将消息交给 LLM（会走 Agent 等完整流程）
        username = self.username or "系统"
        uid = self.uid if self.uid is not None else 0
        self.llm_core.add_system_message(msg, username=username, uid=uid)
        self.log.info(f"视觉描述已发送给 LLM: {msg[:100]}...")

    def _execute_task(self, traceid=None, original_query=None):
        """线程包装，带运行锁"""
        try:
            self.run_once(traceid, original_query)
        except Exception as e:
            self.log.exception("视觉任务执行异常")
        finally:
            with self._lock:
                self._task_running = False

    def check_and_trigger(self, user_message, traceid=None):
        """
        检查消息是否包含触发关键词，若包含且冷却结束，则在子线程中执行视觉任务。
        返回 True 表示已触发任务
        """
        if not self.enabled or not user_message:
            return False

        if not any(kw in user_message for kw in self.keywords):
            return False

        now = time.time()
        if now - self.last_trigger_time < self.cooldown:
            self.log.debug("视觉触发冷却中")
            return False

        with self._lock:
            if self._task_running:
                self.log.debug("视觉任务正在执行，忽略")
                return False
            self._task_running = True

        self.last_trigger_time = now
        threading.Thread(
            target=self._execute_task,
            args=(traceid, user_message),
            daemon=True
        ).start()
        self.log.info(f"已触发视觉任务，用户消息: {user_message}")
        return True