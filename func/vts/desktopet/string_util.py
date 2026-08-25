# -*- coding: utf-8 -*-
# func/vts/desktopet/string_util.py
# 字符串匹配工具（与 VTS 模块一致）


class StringUtil:
    # 判断字符位置（包含搜索字符）
    @staticmethod
    def is_index_contain_string(string_array, target_string):
        for s in string_array:
            if s in target_string:
                num = target_string.find(s)
                return num + len(s)
        return 0

    # 判断字符位置（不含搜索字符）
    @staticmethod
    def is_index_nocontain_string(string_array, target_string):
        i = 0
        for s in string_array:
            i = i + 1
            if s in target_string:
                return i
        return 0
