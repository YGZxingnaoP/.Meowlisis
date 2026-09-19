# -*- coding: utf-8 -*-
"""docwriter 提示词：写作规范 + 版式/配图使用规则 + 工具定义。"""

from .design import THEMES
from .imagegen import ASPECT_HINT
from .layouts import LAYOUT_HINT

TYPE_DESC = {
    "thesis": "一篇结构完整的论文（含摘要、关键词、正文分章、参考文献）",
    "doc": "一份结构清晰的 Word 文档（报告/方案/总结/说明）",
    "ppt": "一份演示文稿（PPT）",
}

THEME_HINT = "、".join(f"{k}={v['name']}" for k, v in THEMES.items())

# 排版与写作规范（模型必须遵守）
STYLE_RULES_DOC = (
    "【Word 写作规范】\n"
    "1. 正文用简化 Markdown：# 一级标题、## 二级、### 三级、- 项目符号、1. 编号、> 引用、"
    "| 表格 |、![图注](图片路径)、--- 分页。\n"
    "2. 结构：标题 → 摘要/导语（3 行内）→ 正文分章（每章先结论后论据）→ 结论 → 参考资料。\n"
    "3. 每段 2~5 句，别写超长段落；关键数字/结论句单独成段。\n"
    "4. 一级标题不超过 6 个；每个二级标题下至少 1 段正文。\n"
    "5. 有 2 个以上可比较的数字时，必须用表格或图表，不要只堆文字。\n"
    "6. 图片必须写成 ![图 N  说明](路径)，图注 20 字内；图片路径只能用工具返回的路径。\n"
    "7. 不要把查找过程、工具调用写进正文；不要输出「根据搜索结果」这种话。\n"
)

STYLE_RULES_PPT = (
    "【PPT 制作规范（必须严格遵守，渲染层会按此校验）】\n"
    "1. 页数 8~16 页；结构：封面 → 目录 →（章节页）正文页 → 结论 → 结尾。\n"
    "2. 硬上限：**每页要点 3~5 条、每条 ≤18 字**；标题 ≤18 字；图表页结论 2~4 条。\n"
    "   超限会被截断——宁可少写一条，也不要写长句。\n"
    "3. 版式选择要「有节奏」，不要连续 3 页同版式：\n"
    "   - 关键数字 → kpi（3 个数字卡）；有数字对比 → table 或 chart\n"
    "   - 发展历程/步骤 → timeline（3~5 节点）；分类对比 → matrix（4 格）\n"
    "   - 案例/产品 → grid（2~4 图）或 image_right；金句 → quote\n"
    "   - 概念示意 → gen_image 生成（宽图用 wide）；真实照片 → image_search\n"
    "4. 文字页与视觉页交替：每 2~3 页必须有一页带图/表/卡的视觉页。\n"
    "5. 不要写「本页介绍」这类废话，也不要客套话（结尾页只写「谢谢观看」）。\n"
)

# 内容契约（与 render.LIMIT 保持一致）
CONTRACT_DOC = (
    "| 页型 | 条数上限 | 单条字数 |\n"
    "| --- | --- | --- |\n"
    "| bullets 要点页 | 5 | 18 |\n"
    "| toc 目录 | 7 | 14 |\n"
    "| kpi 数据卡 | 3 卡 | 数字≤8字符、说明≤12字 |\n"
    "| timeline 时间线 | 5 节点 | 标题≤10字、说明≤14字 |\n"
    "| matrix 矩阵 | 4 格 | 每格标题≤10字、内容≤20字 |\n"
    "| table 表格 | 8 行 | 单格≤12字 |\n"
    "| chart 图表 | 结论 4 条 | 18 |\n"
    "| grid 图片墙 | 4 图 | 图注≤12字 |\n"
)

IMAGE_RULES = (
    "【配图规则】\n"
    "- 需要**数据对比/趋势/占比** → 先算数据再调 make_chart 生成图表（最推荐，可控）。\n"
    "- 需要**真实事物照片**（人物、产品、地点、新闻现场） → image_search 搜图。\n"
    "- 需要**概念示意/抽象图**且搜不到合适的 → gen_image 生成（AI 生图偏插画风，慎用）。\n"
    "- gen_image 的 aspect 自行判断：正文配图/封面/图表旁用 wide；人物、手机界面、竖版长图用 tall；"
    "图标、示意、徽标用 square。\n"
    "- 图片总数不超过 {max_img} 张；搜不到就改用图表或纯排版，**绝不编造图片**。\n"
    "- 每次拿到图片路径后立刻在内容里引用；不要引用未通过工具获得的路径。\n"
)


def system_prompt(doc_type, fmt, config=None):
    """Agent 系统提示词"""
    target = TYPE_DESC.get(doc_type, TYPE_DESC["doc"])
    rules = STYLE_RULES_PPT if doc_type == "ppt" else STYLE_RULES_DOC
    max_img = getattr(config, "image_max", 4) if config else 4
    has_img = getattr(config, "images_enabled", True) if config else True
    img_rules = IMAGE_RULES.format(max_img=max_img) if has_img else "【配图规则】本次不配图。\n"
    tools = [
        "- web_search(query, page)：联网搜索（可翻页取更多线索）",
        "- web_open(url, dynamic)：读网页正文（dynamic=true 可渲染动态页）",
        "- make_chart(kind, title, rows)：用结构化数据画图，kind ∈ bar/barh/line/pie/area/scatter，"
        "rows=[{name,value,unit,year}]；返回图片路径",
        "- make_table(rows, header, max_rows)：把结构化数据转成 Markdown 表格文本，直接粘进正文",
        "- image_search(query, count)：联网搜真实图片并下载，返回图片路径",
        "- gen_image(prompt, aspect)：AI 生成配图，aspect 按用途选（" + ASPECT_HINT + "），返回图片路径",
        "- write_doc(filename, content, title, subtitle, theme)：生成 Word（content 为 Markdown）"
        if fmt == "docx" else
        "- write_ppt(filename, slides, title, subtitle, theme)：生成 PPT（slides 见下方版式）",
    ]
    parts = [
        "你是专业内容制作助手，可联网检索资料、处理数据、配图，并输出排版好的成品文件。\n",
        "可用工具：\n" + "\n".join(tools) + "\n",
        LAYOUT_HINT + "\n" if fmt == "pptx" else "",
        f"可选主题 theme：{THEME_HINT}（不确定就用 tech）\n",
        "\n" + rules,
        img_rules,
        "【工作流程】\n"
        "1. 先 web_search 检索足够资料（结果无效就换关键词或翻页），必要时 web_open 读正文。\n"
        "2. 把关键数字整理成结构化 rows，用 make_table / make_chart 产出表格与图表。\n"
        "3. 需要配图时调用 image_search 或 gen_image，记下返回的路径。\n"
        "4. 最后调用一次写文件工具生成成品，文件名贴合内容。\n"
        "5. 生成成功后立即结束，不要再多说话。\n",
        f"本次任务：{target}。\n",
    ]
    return "".join(p for p in parts if p)


def user_prompt(request, doc_type, fmt, short_memory):
    """Agent 用户提示词"""
    lines = []
    for m in (short_memory or [])[-6:]:
        if isinstance(m, dict) and m.get("content"):
            lines.append(f"{m.get('role', 'user')}: {m.get('content')}")
    parts = [f"用户需求：{request}"]
    if lines:
        parts.append("近期对话：\n" + "\n".join(lines))
    parts.append("请检索资料、处理数据、按需配图，并生成成品文件。")
    return "\n".join(parts)


def force_prompt(request, doc_type, fmt):
    """兜底成稿提示词（不再给工具，直接产出结构化内容）"""
    target = TYPE_DESC.get(doc_type, TYPE_DESC["doc"])
    if fmt == "pptx":
        shape = ('{"filename":"文件名","title":"主标题","slides":'
                 '[{"layout":"cover","title":"主标题","subtitle":"副标题"},'
                 '{"layout":"bullets","title":"页标题","bullets":["要点1","要点2"]},'
                 '{"layout":"end","title":"谢谢观看"}]}')
    else:
        shape = ('{"filename":"文件名","title":"标题","subtitle":"副标题",'
                 '"content":"# 一级标题\\n## 二级标题\\n正文……\\n| 表头 | 表头 |\\n| --- | --- |\\n| 值 | 值 |"}')
    return (
        "现在必须直接产出最终文件内容，不要再调用任何工具，也不要输出解释或代码块标记。\n"
        f"任务：{target}。用户需求：{request}\n"
        f"只输出一个 JSON 对象：{shape}"
    )


def agent_tools():
    """Agent 工具定义（OpenAI function schema）"""
    rows_prop = {"type": "array", "description": "结构化数据行",
                 "items": {"type": "object", "properties": {
                     "name": {"type": "string", "description": "项目/名称"},
                     "value": {"type": "number", "description": "数值"},
                     "unit": {"type": "string", "description": "单位，如 %/元/万人"},
                     "year": {"type": "string", "description": "年份，同比用"},
                     "source": {"type": "string", "description": "来源 URL"}}}}
    return [
        {"type": "function", "function": {
            "name": "web_search",
            "description": "联网搜索关键词，返回标题、链接与摘要。结果无效时增大 page 翻页。",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "page": {"type": "integer", "description": "页码，从 1 开始"}},
                "required": ["query"]}}},
        {"type": "function", "function": {
            "name": "web_open",
            "description": "打开网页并提取正文。dynamic=true 时用浏览器渲染动态页面。",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string", "description": "网页链接"},
                "dynamic": {"type": "boolean", "description": "是否用浏览器渲染"}},
                "required": ["url"]}}},
        {"type": "function", "function": {
            "name": "make_chart",
            "description": "用结构化数据生成图表 PNG（bar 柱状 / barh 条形 / line 折线 / pie 饼图 / "
                           "area 面积 / scatter 散点），返回图片路径供引用。",
            "parameters": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["bar", "barh", "line", "pie", "area", "scatter"]},
                "title": {"type": "string", "description": "图表标题"},
                "rows": rows_prop,
                "top": {"type": "integer", "description": "最多显示几项，默认 8"},
                "xlabel": {"type": "string"}, "ylabel": {"type": "string"},
                "filename": {"type": "string", "description": "输出文件名，可省略"}},
                "required": ["kind", "rows"]}}},
        {"type": "function", "function": {
            "name": "make_table",
            "description": "把结构化数据转成 Markdown 表格文本（直接粘进正文），或用于 PPT 表格页。",
            "parameters": {"type": "object", "properties": {
                "rows": rows_prop,
                "header": {"type": "array", "items": {"type": "string"},
                           "description": "表头，默认 [名称, 数值, 单位]"},
                "max_rows": {"type": "integer", "description": "最多几行，默认 12"}},
                "required": ["rows"]}}},
        {"type": "function", "function": {
            "name": "image_search",
            "description": "联网搜真实图片并下载（人物/产品/地点/现场等），返回图片路径与来源。",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "图片关键词"},
                "count": {"type": "integer", "description": "需要几张，默认 1"}},
                "required": ["query"]}}},
        {"type": "function", "function": {
            "name": "gen_image",
            "description": "AI 生成配图（概念示意/插画风），返回图片路径。真实照片请用 image_search。",
            "parameters": {"type": "object", "properties": {
                "prompt": {"type": "string", "description": "画面描述，中文即可"},
                "aspect": {"type": "string", "enum": ["square", "wide", "tall"],
                           "description": "画幅，按用途自行决定：" + ASPECT_HINT},
                "filename": {"type": "string", "description": "文件名，可省略"}},
                "required": ["prompt"]}}},
        {"type": "function", "function": {
            "name": "write_doc",
            "description": "生成 Word 文档（排版样式由系统保证）。",
            "parameters": {"type": "object", "properties": {
                "filename": {"type": "string"},
                "content": {"type": "string", "description": "Markdown 正文"},
                "title": {"type": "string", "description": "封面主标题"},
                "subtitle": {"type": "string", "description": "封面副标题"},
                "theme": {"type": "string", "description": f"主题：{THEME_HINT}"}},
                "required": ["filename", "content"]}}},
        {"type": "function", "function": {
            "name": "write_ppt",
            "description": "生成 PPT 演示文稿（版式由 layout 指定，系统保证排版）。",
            "parameters": {"type": "object", "properties": {
                "filename": {"type": "string"},
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "theme": {"type": "string"},
                "slides": {"type": "array", "description": "幻灯片列表", "items": {
                    "type": "object", "properties": {
                        "layout": {"type": "string",
                                   "description": "cover/toc/section/bullets/kpi/timeline/"
                                                  "matrix/table/chart/image_right/full_image/"
                                                  "grid/two_col/quote/end"},
                        "title": {"type": "string"},
                        "kicker": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"},
                                    "description": "要点，最多 5 条、每条 ≤18 字"},
                        "points": {"type": "array", "items": {"type": "string"},
                                   "description": "图表页/大图页的结论，最多 4 条"},
                        "cards": {"type": "array", "description": "kpi 版式：3 个数字卡",
                                  "items": {"type": "object", "properties": {
                                      "value": {"type": "string", "description": "数字，如 460亿"},
                                      "label": {"type": "string", "description": "指标名"},
                                      "note": {"type": "string", "description": "补充说明"}}}},
                        "nodes": {"type": "array", "description": "timeline 版式：3~5 个节点",
                                  "items": {"type": "object", "properties": {
                                      "label": {"type": "string", "description": "时间/序号"},
                                      "title": {"type": "string"},
                                      "desc": {"type": "string"}}}},
                        "cells": {"type": "array", "description": "matrix 版式：4 个格子",
                                  "items": {"type": "object", "properties": {
                                      "title": {"type": "string"},
                                      "items": {"type": "array", "items": {"type": "string"},
                                                "description": "该格 1~3 条，每条 ≤20 字"}}}},
                        "images": {"type": "array", "description": "grid 版式：2~4 张图片墙",
                                   "items": {"type": "object", "properties": {
                                       "path": {"type": "string", "description": "图片路径"},
                                       "caption": {"type": "string",
                                                   "description": "图注 ≤12 字"}}}},
                        "image": {"type": "string", "description": "图片路径（工具返回值）"},
                        "caption": {"type": "string"},
                        "header": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array", "items": {"type": "array",
                                                            "items": {"type": "string"}}},
                        "text": {"type": "string"}, "author": {"type": "string"},
                        "no": {"type": "string"}, "desc": {"type": "string"},
                        "left_title": {"type": "string"}, "left_items": {"type": "array",
                                                                         "items": {"type": "string"}},
                        "right_title": {"type": "string"}, "right_items": {"type": "array",
                                                                           "items": {"type": "string"}}}}}},
                "required": ["filename", "slides"]}}},
    ]
