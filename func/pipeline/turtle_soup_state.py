# -*- coding: utf-8 -*-
# func/pipeline/turtle_soup_state.py
# 海龟汤状态桥接：toolbox 与 system_prompt 之间的唯一传递通道

from func.tools.singleton_mode import singleton


@singleton
class TurtleSoupStateBridge:
    """pipeline 层只读桥接：SystemPromptBridge 通过它读 game_block，不 import toolbox 内部单例"""

    def __init__(self):
        from func.toolbox.turtle_soup.state import TBTurtleSoupState
        self._state = TBTurtleSoupState()

    def is_active(self, key) -> bool:
        return self._state.is_active(key)

    def get_game_block(self, key) -> str:
        return self._state.get_game_block(key)

    def get_puzzle(self, key) -> dict:
        return self._state.get_puzzle(key)
