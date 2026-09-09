# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/config.py
# SVG 绘画模块全部配置项统一管理（完全独立，不与其它模块共用模型 / api key）

import os

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBSvgPainterConfig:
    """集中管理 config.yml 的 svg_painter 节点（GUI 工具箱「绘画」配置球读写同一处）"""

    def __init__(self):
        cfg = ConfigReader().get('svg_painter', {})

        # ========== 总开关 / 服务端口 ==========
        self.enabled = bool(cfg.get('enabled', False))
        self.http_port = int(cfg.get('http_port', 8090))
        self.ws_port = int(cfg.get('ws_port', 8767))

        # ========== 画布规格（两种预设供 AI 在 start_session 时选择） ==========
        # 兜底默认（start_session 未指定 canvas 时使用）
        self.canvas_width = int(cfg.get('canvas_width', 600))
        self.canvas_height = int(cfg.get('canvas_height', 800))
        # 画布底色：默认 none=透明（画板卡片浅色兜底）；可填 #ffffff 等
        self.canvas_bg = str(cfg.get('canvas_bg', 'none') or 'none')

        # ========== 绘画模型（独立配置，deepseek / aliyun 二选一） ==========
        self.llm_type = str(cfg.get('llm_type', 'deepseek'))
        self.thinking_enabled = bool(cfg.get('thinking_enabled', True))
        self.temperature = float(cfg.get('temperature', 0.8))
        self.max_tokens = int(cfg.get('max_tokens', 8192))
        # 方案A：绘画蓝图（把用户模糊需求 → 结构化坐标/细节设计稿）
        # 新绘画会话首轮会用一次「关思考」的快调用生成蓝图；失败自动降级为直接用原文
        self.planning_enabled = bool(cfg.get('planning_enabled', True))
        # 0 = 无限步（默认）；>0 为单轮绘制最大工具调用次数（护栏）
        self.max_steps_per_round = int(cfg.get('max_steps_per_round', 0))
        # 单片段文本长度上限（字符，0 = 不限制）
        self.max_fragment_chars = int(cfg.get('max_fragment_chars', 6000))

        # DeepSeek（独立 key / 模型）
        ds = cfg.get('deepseek', {})
        self.deepseek_api_key = str(ds.get('api_key', '') or '')
        self.deepseek_base_url = str(ds.get('base_url', 'https://api.deepseek.com/v1') or '')
        self.deepseek_model = str(ds.get('model', 'deepseek-chat') or 'deepseek-chat')

        # 阿里云百炼（独立 key / 模型）
        al = cfg.get('aliyun', {})
        self.aliyun_api_key = str(al.get('api_key', '') or '')
        self.aliyun_base_url = str(
            al.get('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1') or
            'https://dashscope.aliyuncs.com/compatible-mode/v1'
        )
        self.aliyun_model = str(al.get('model', 'qwen-max') or 'qwen-max')

        # ========== 存档 ==========
        # 进行中会话（.temp），会话结束才归档进 backup_dir
        self.temp_dir = str(cfg.get('temp_dir', os.path.join('.temp', 'svg_paint')) or
                            os.path.join('.temp', 'svg_paint'))
        self.backup_dir = str(cfg.get('backup_dir', os.path.join('character', 'svg_paints')) or
                              os.path.join('character', 'svg_paints'))
        # 归档目录保留最近 N 个会话文件夹（0 = 全部保留）
        self.keep_last_sessions = int(cfg.get('keep_last_sessions', 0))

        # ========== QQ 发图 ==========
        # 每轮收笔后把成品渲染成 png 发给该 QQ 会话用户（群聊 @ 发起人，私聊直接发）
        self.qq_send_image = bool(cfg.get('qq_send_image', True))
        # 渲染倍率（输出 png 尺寸 = 画布 × scale）
        self.render_scale = max(1, min(int(cfg.get('render_scale', 2)), 4))

    # 画布预设（供 AI 在 paint.start_session 的 canvas 参数中选择）
    CANVAS_PRESETS = {
        "600x800": (600, 800),      # 竖版
        "1080x1960": (1080, 1960),  # 竖版长图/海报
    }

    def resolve_canvas(self, key=None):
        """把 canvas 参数解析为 (宽, 高)；未知/空则回退默认 600×800"""
        k = str(key or "").strip().lower()
        if k not in self.CANVAS_PRESETS:
            return (self.canvas_width, self.canvas_height)
        return self.CANVAS_PRESETS[k]

    def active_llm(self) -> dict:
        """返回当前生效绘画模型的连接参数 {api_key, base_url, model, llm_type}"""
        if self.llm_type == 'aliyun':
            return {
                'llm_type': 'aliyun',
                'api_key': self.aliyun_api_key,
                'base_url': self.aliyun_base_url,
                'model': self.aliyun_model,
            }
        return {
            'llm_type': 'deepseek',
            'api_key': self.deepseek_api_key,
            'base_url': self.deepseek_base_url,
            'model': self.deepseek_model,
        }
