# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/prompts.py
# SVG 绘画提示词组装：角色人设（外部传入）+ 画板规则

class TBSvgPainterPrompts:
    """生成绘画 Agent 的系统提示词与单轮指令"""

    # 允许出现在片段中的 SVG 元素（白名单，安全过滤）
    ALLOWED_TAGS = (
        "svg", "g", "defs", "linearGradient", "radialGradient", "stop",
        "pattern", "clipPath", "mask", "path", "rect", "circle", "ellipse",
        "line", "polyline", "polygon", "text", "tspan", "use", "title", "desc",
    )

    PAINT_RULES = (
        "【你是绘画者 · 规则】\n"
        "你只做一件事：把整幅画面画出来。风格固定为 **扁平矢量 + 极简 + 线稿感**。\n"
        "1. 画风：大块几何形状与干净线条拼出画面；2~4 个明快纯色；构图多留白、元素少而精（6~10 个），"
        "一眼看懂。不做写实、不做杂多渐变、不加细碎装饰。\n"
        "2. **唯一动作**：调用一次工具 paint_submit_svg，把整幅 SVG 写进它的 svg 参数"
        "（或直接把这个 <svg>…</svg> 写在回复正文里——两种方式系统都会自动识别上板显示）。"
        "svg 可用 <svg viewBox='0 0 600 800'>…</svg> 完整文档，坐标须落在 viewBox 内、主体不重叠不飞出。\n"
        "3. **一次给整幅，不分步**：不要挤牙膏式逐笔画，不要在回复里解释思路，画完整幅就停。\n"
        "4. 用粗一点的描边线条（stroke 约 3~5）勾勒形状、纯色填充可保留；这样画面清晰耐看。\n"
        "5. 用户中途插话/提了新要求：直接在下一版里提交新的整幅画面即可（整体替换），不逐笔修补。\n"
    )

    def build_system(self, persona: str, canvas_w: int, canvas_h: int, canvas_bg: str,
                     base_note: str = "") -> str:
        """组装绘画系统提示词：角色人设 + 画板信息 + 规则 + （可选）旧画说明"""
        parts = []
        if persona:
            parts.append(persona)
        canvas = (
            f"【画布】规格 {canvas_w}×{canvas_h}（600×800 头像/插画；1080×1960 长图/全身，"
            f"在 paint.start_session 的 canvas 参数里选）。viewBox 与所选规格一致，所有坐标须落在其内。"
            f"背景底色 {canvas_bg}（底色由系统铺，除非要画天空/地板等场景色，不必再铺整底）。"
        )
        if base_note:
            canvas += f"\n{base_note}"
        parts.append(canvas)
        parts.append(self.PAINT_RULES)
        return "\n\n".join(parts)

    # ==================== 方案A：绘画蓝图（导演模式） ====================
    @staticmethod
    def build_blueprint_prompt(persona: str = "") -> str:
        """绘画「导演」指令：把模糊需求转成可执行蓝图（一次性整幅，风格=扁平矢量极简线稿）"""
        style_hint = ""
        if persona:
            p = str(persona).strip()
            style_hint = "\n\n参考角色风格与对主人的了解（把握画面气质，不要生硬照搬）：\n" + p[:500]
        return (
            "你是绘画『导演』。用户说了一句画画需求，你要把它变成一份可直接执行的 SVG 绘画蓝图，"
            "让画家**一次性画出整幅**、不跑偏。\n"
            "必须调用工具 paint_submit_blueprint 一次性提交，全部内容填进参数字段"
            "（canvas / style / scene / palette / layout / anchors / elements / avoid / note），"
            "不要输出 JSON 文本、不要解释。参数示例：\n"
            "{\n"
            '  "canvas": "600x800",\n'
            '  "style": "扁平矢量 + 极简 + 线稿感：几何形状、干净线条、明快纯色",\n'
            '  "scene": "画面一句话：场景、时间、氛围、主体动作",\n'
            '  "palette": {"天空": "#bfe8ff", "人物": "#3a3a45", "点缀": "#ff9fb0"},\n'
            '  "layout": "构图一句话：主体位置、留白",\n'
            '  "anchors": [{"element": "太阳", "kind": "circle", "x": 300, "y": 200, "size": "r≈90"}],\n'
            '  "elements": ["元素1", "元素2"],\n'
            '  "avoid": ["元素太杂、渐变太多、主体出画布"],\n'
            '  "note": ""\n'
            "}\n"
            "要求：\n"
            "1. 坐标按 600×800 描述（x∈[0,600]，y∈[0,800]），anchors 只给 2~6 个关键元素，宁少而准。\n"
            "2. elements 是**必画元素清单，列 6~10 个以内**（先主体轮廓、后细节装饰），画家照着画齐即可。\n"
            "3. 风格固定**扁平矢量 + 极简 + 线稿感**：几何形状、2~4 纯色、线条干净，禁止写实/复杂渐变/元素堆砌。\n"
            "4. 配色与背景有对比；长图/全身场景 canvas 填 1080x1960。\n"
            "5. 所有字段都填，缺失会让画面失控。"
            + style_hint
        )
