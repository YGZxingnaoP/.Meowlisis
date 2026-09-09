# -*- coding: utf-8 -*-
# func/toolbox/flux_painter
# ComfyUI 文生图绘画模块（flux_painter，父级工具名 flux_paint）
# - 内置 headless ComfyUI 子服务（资源在 .ComfyNode）或外部 ComfyUI 服务
# - LLM(prompt_producer) 基于 .ComfyNode/prompt_reference 的 ANIMA3 提示词法典生成
#   {标题, 正向(画师串+质量+tag+自然语言), 回复}；负向固定库；画师默认配置可点名检索
# - 出图 → 审查(可配) → TTS(type=toolbox_painting) → 归档 character/paints → 记忆
# - 一次性触发工具（live/QQ），绘画中冷却，不长期接管对话
