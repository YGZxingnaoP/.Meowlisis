# -*- coding: utf-8 -*-
# gui/tools/prefill_seed.py
# 用法：runtime\python.exe gui\tools\prefill_seed.py [--no-reset] [--site mcmod]

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(BASE)
sys.path.insert(0, BASE)

if __name__ == "__main__":
    from func.database.seed import main
    main()
