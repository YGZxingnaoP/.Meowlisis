# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/__init__.py
# SVG 绘画 Agent 包（触发型工具 + 独立画板服务）
# - 绘画模型 port 完全独立（svg_painter/port），不依赖 toolbox/port 与 llm/llm_active 的任何配置
# - 触发入口 TBSvgPainterCore（父级 toolcalls 注册为 svg_paint）
# - 画板服务 HTTP 8090 + WebSocket 8767，页面 svg_board.html
