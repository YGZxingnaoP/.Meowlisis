# -*- coding: utf-8 -*-

from func.toolbox.flux_painter.prompts.anima import AnimaPromptSpec
from func.toolbox.flux_painter.prompts.moss import MossPromptSpec

SPECS = {
    AnimaPromptSpec.family: AnimaPromptSpec(),
    MossPromptSpec.family: MossPromptSpec(),
}

def get_prompt_spec(family: str):
    """按底模家族取提示词规范（未知家族回退 anima）"""
    return SPECS.get(str(family or "").strip().lower()) or SPECS["anima"]
