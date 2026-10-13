# -*- coding: utf-8 -*-
# RVC i18n（精简版）：改用基于 __file__ 的绝对路径，不再依赖启动 cwd
import json
import locale
import os

from tools.file_io import read_text

I18N_DIR = os.path.dirname(os.path.abspath(__file__))


def load_language_list(language):
    return json.loads(read_text(os.path.join(I18N_DIR, "locale", f"{language}.json")))


class I18nAuto:
    def __init__(self, language=None):
        if language in ["Auto", None]:
            language = locale.getdefaultlocale()[0]
        if not os.path.exists(os.path.join(I18N_DIR, "locale", f"{language}.json")):
            language = "en_US"
        self.language = language
        self.language_map = load_language_list(language)

    def __call__(self, key):
        return self.language_map.get(key, key)

    def __repr__(self):
        return "Use Language: " + self.language
