# -*- coding: utf-8 -*-
# func/toolbox/turtle_soup/prompt.py
# 拼装海龟汤「游戏注入块」：由 toolbox 生成，经状态桥接传给 system_prompt.py 追加到最下方


def build_game_block(puzzle: dict) -> str:
    """把谜题拼成注入系统提示词最下方的游戏块（含汤底，强约束不剧透）"""
    title = (puzzle.get("title") or "").strip()
    surface = (puzzle.get("surface") or "").strip()
    answer = (puzzle.get("answer") or "").strip()
    return (
        "# 正在进行海龟汤游戏（你是主持人）\n"
        "你必须认真主持本局游戏：不得拒绝、不得敷衍、不得中途跑题，直到游戏结束。\n"
        f"## 标题\n{title}\n"
        f"## 汤面\n{surface}\n"
        f"## 汤底（这是答案，绝对不要直接告诉用户）\n{answer}\n"
        "## 规则\n"
        "- 用户通过「是/否」提问或直接猜测来推理汤底；\n"
        "- 你只能回答：是 / 否 / 无关 / 不重要，或给适度提示；\n"
        "- 当答案是「不重要/无关」时，要用符合你角色性格的方式做一句不剧透的吐槽；\n"
        "- 严格把控：只有用户说出汤底完整真相的时候才算猜中，模糊、擦边、只说部分、复述汤面都不算；\n"
        "- 当用户准确猜中汤底时，跟对方说才对了，公布汤底。"
    )
