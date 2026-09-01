# -*- coding: utf-8 -*-
# scripts/xiaohu_response/main.py
# 筱狐必回机器人：入口
#
# 独立运行（不启动主项目）：
#   cd /d D:\.Meowlisis
#   python scripts\xiaohu_response\main.py
# 或直接双击 scripts\xiaohu_response\start.bat
#
# 行为：监听群 174127179（上理GM电竞方块幻想MC社团分部）
#   - 用户 3382794370（熙欧_筱狐）任何消息 → 合并缓冲（同主项目逻辑）→ LLM 必回，
#     回复句首有效 @ 筱狐；
#   - 其它人 @ 角色 → 按原群聊 @ 回复逻辑回复（纯文本，不 @ 回去）；
#   - 其它人普通消息 → 不回复（仅在 @ 等待中并入后续消息）。
# 记忆回写与表情 gif 触发与主项目一致。
# 复用主项目库，不改主项目任何代码。

import logging
import os
import sys
import threading

# 项目根目录：scripts/xiaohu_response/main.py -> 上级 x2 = D:\.Meowlisis
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ==================== 日志 ====================
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def setup_logging() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("xiaohu_response")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    # 控制台
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    # 文件
    fh = logging.FileHandler(os.path.join(LOG_DIR, "xiaohu.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def register_character_builder(log: logging.Logger):
    """注册角色卡构建器（与主项目 api.py 一致），保证群聊系统提示词完整"""
    try:
        from func.catbrain.prompt_builder import MeowPromptBuilder
        from func.pipeline.system_prompt import SystemPromptBridge
        SystemPromptBridge().register_builder(MeowPromptBuilder())
        log.info("角色卡构建器已注册")
    except Exception:
        log.exception("注册角色卡构建器失败（提示词将缺少角色卡部分）")


def build_app(log: logging.Logger):
    """装配各模块，返回 (core, buffer, trigger) 供事件回调使用"""
    from config import XHConfig
    from sender import XHSender
    from trigger import XHTrigger
    from buffer_runner import XHBufferRunner
    from memory_writer import XHMemoryWriter
    from reply_engine import XHReplyEngine

    config = XHConfig()
    sender = XHSender(log)
    memory = XHMemoryWriter(log, config)
    engine = XHReplyEngine(log, config, sender, memory)
    buffer = XHBufferRunner(log, engine.reply)
    trigger = XHTrigger(log, config)

    from func.toolbox.napcat.napcat_core import TBNapCatCore
    core = TBNapCatCore()

    # 覆盖事件回调（脚本侧操作，不改主项目代码）
    core.on_group_message = lambda event: _safe_call(log, trigger, buffer, event)
    core.on_private_message = lambda event: log.info(f"[忽略] 私聊消息（脚本只处理目标群）")
    core.on_poke = lambda event: None

    return core, buffer


def _safe_call(log: logging.Logger, trigger, buffer, event: dict):
    """群消息回调：解析分类 → 入缓冲（异常不拖垮事件循环）

    入缓冲规则：
    - 筱狐任何消息 → 必入缓冲（必回）；
    - 其它人 @ 角色 → 入缓冲（走原群聊 @ 回复逻辑）；
    - 其它人普通消息 → 仅当该用户已在缓冲中（刚 @ 过在等待）时并入，
      与主项目「@ 后合并该用户后续消息」行为一致。
    """
    try:
        result = trigger.parse(event)
        if not result:
            return
        parsed = result["parsed"]
        is_xiaohu = result["is_xiaohu"]
        is_at_self = result["is_at_self"]
        if is_xiaohu or is_at_self or buffer.exists(parsed["group_id"], parsed["user_id"]):
            log.info(f"[触发] {parsed.get('username')}({parsed.get('user_id')}) "
                     f"群 {parsed.get('group_id')}: {parsed.get('text', '')[:30]}"
                     f"{' [筱狐]' if is_xiaohu else (' [@角色]' if is_at_self else ' [并入]')}")
            buffer.add(parsed)
    except Exception:
        log.exception("处理群消息异常")


def main():
    log = setup_logging()
    log.info("=" * 50)
    log.info("筱狐必回机器人启动")

    register_character_builder(log)

    core, buffer = build_app(log)
    if not core.enabled:
        log.error("主项目 napcat.enabled=false，无法连接 NapCat，请先在 config.yml 打开 napcat 节点")
        return

    core.start()
    log.info("已连接 NapCat，开始监听群 174127179（上理GM电竞方块幻想MC社团分部）")
    log.info("  筱狐(3382794370)任何消息 → 必回且句首 @；其它人 @ 角色 → 回复；普通消息 → 不回复")
    log.info("按 Ctrl+C 停止")

    try:
        # 阻塞主线程，等待 Ctrl+C
        threading.Event().wait()
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C，准备停止...")
    finally:
        buffer.clear()
        core.stop()
        log.info("已停止")


if __name__ == "__main__":
    main()
