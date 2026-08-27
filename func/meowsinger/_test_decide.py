# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"D:\.Meowlisis")

from func.meowsinger.if_start import MeowIfStart

text = "Meowlisis唱歌 是远航啊，akie秋绘的远航"
r = MeowIfStart().decide(text, "testuser")
print("decide 返回:", repr(r))
