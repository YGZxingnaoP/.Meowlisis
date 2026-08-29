# -*- coding: utf-8 -*-
# func/tts/lan_judge.py
# 轻量级「整段语言」判定：仅在明显是整段英文/整段日文时切换合成语言，其余落回默认语言。
# 与 SoVITS 内置 auto 的 fast_langdetect 不同，这里用可控的正则统计，避免中文短句被误判成日文。
# 日文判定规则：假名（平假名/片假名）占「有效文字」比例 >= 1/3 才判为整段日文。

import re

# 平假名 + 片假名（含长音符号「ー」U+30FC）
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
# 中文汉字（用于区分「纯英文」与「中英混杂」）
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 拉丁字母
_LATIN_RE = re.compile(r"[A-Za-z]")


class LanguageJudge:
    """整段语言粗判，返回 SoVITS 可接受的 text_lang 标签。
    """

    def __init__(self, default_lang: str = "zh"):
        self.default_lang = default_lang or "zh"

    def judge(self, text: str) -> str:
        if not text or not text.strip():
            return self.default_lang

        text = text.strip()

        # 统计三类「有效文字」：假名 / 中文汉字 / 拉丁字母（标点、空格、数字不计入分母）
        kana = len(_KANA_RE.findall(text))
        cjk = len(_CJK_RE.findall(text))
        latin = len(_LATIN_RE.findall(text))
        total = kana + cjk + latin

        if total == 0:
            # 纯符号 / 数字 / 空白，交给默认语言
            return self.default_lang

        # 1. 日文：假名占有效文字 1/3 及以上才判为整段日文
        if kana * 3 >= total:
            return "ja"

        # 2. 整段英文：无中文汉字、且有拉丁字母
        if cjk == 0 and latin > 0:
            return "en"

        # 3. 其余落回默认语言
        return self.default_lang


def judge_language(text: str, default_lang: str = "zh") -> str:
    """模块级便捷函数"""
    return LanguageJudge(default_lang).judge(text)
