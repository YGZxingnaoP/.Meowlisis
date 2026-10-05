# -*- coding: utf-8 -*-
# gui/tools/log_rules.py
r"""日志转译规则表：把常见日志行翻成一句人话。

约定：
    - 规则 = (编译好的正则, 中文短句)；短句**不含变量**，保证它是稳定的 i18n key；
    - 正则里如果需要取出关键值（工具名、用户名…），用捕获组，取到的值作为 detail
      单独返回，前端拼成「短句：值」，这样英文词条仍然能命中；
    - 从上往下匹配，先写具体、后写宽泛；
    - **匹配不到返回 ('', '')**，前端回退显示去掉前缀的原文（保底，不丢信息）；
    - 不使用 emoji；文案只做"摘要"，不改变原意（错误信息尤其如此）。

translate(text) -> (title, detail)
"""

import re

RULES = [
    # ==================== 连接 / 启停 ====================
    (re.compile(r'已连接\s*NapCat'), ('QQ 服务已连接', None)),
    (re.compile(r'NapCat\s*客户端已启动'), ('QQ 服务已启动', None)),
    (re.compile(r'NapCat\s*已停止'), ('QQ 服务已停止', None)),
    (re.compile(r'连接异常.*(?:重连|重试)'), ('与 QQ 服务断开，正在自动重连', None)),
    (re.compile(r'主协程异常'), ('QQ 服务内部出错', None)),
    (re.compile(r'已在运行'), ('这个服务已经在跑了', None)),

    # ==================== QQ 收 / 发 ====================
    (re.compile(r'\[NapCat\]\s*发送群@文本'), ('在群里 @ 某人并发了消息', None)),
    (re.compile(r'\[NapCat\]\s*发送群文本'), ('往群里发了一条消息', None)),
    (re.compile(r'\[NapCat\]\s*发送群图片'), ('往群里发了一张图片', None)),
    (re.compile(r'\[NapCat\]\s*发送群文件'), ('往群里发了一个文件', None)),
    (re.compile(r'\[NapCat\]\s*发送图片'), ('给对方发了一张图片', None)),
    (re.compile(r'\[NapCat\]\s*发送文本'), ('给对方发了一条消息', None)),
    (re.compile(r'\[NapCat\]\s*发送.*失败'), ('消息没能发出去', None)),
    (re.compile(r'\[NapCat\]\s*发送.*无响应'), ('发送没有回应，可能连接断了', None)),
    (re.compile(r'\[NapCat\]\s*发送.*成功'), ('消息已送达', None)),
    (re.compile(r'\[NapCat\]\s*回复\s*([^\s:]+)'), ('回复了对方', 1)),
    (re.compile(r'\[NapCat群聊\]\s*回复'), ('在群里回了一句', None)),

    # ==================== 消息缓冲 ====================
    (re.compile(r'\[NapCat缓冲\]\s*用户\s*\S+\s*停顿超时'), ('对方停下来了，开始回复', None)),
    (re.compile(r'\[NapCat缓冲\]\s*用户\s*\S+\s*达到上限'), ('消息太多，立即回复', None)),
    (re.compile(r'\[NapCat缓冲\]\s*用户\s*\S+\s*第'), ('收到消息，先等一会儿再一起回', None)),
    (re.compile(r'\[NapCat群缓冲\].*达到上限'), ('群里消息太多，立即回复', None)),
    (re.compile(r'\[NapCat群缓冲\].*停顿超时'), ('群里安静了，准备回一句', None)),
    (re.compile(r'\[NapCat群缓冲\].*@\s*触发'), ('有人在群里 @ 了角色，稍等就回', None)),

    # ==================== 群聊决策 ====================
    (re.compile(r'关键词命中，触发回复'), ('群里说到关键词，触发回复', None)),
    (re.compile(r'AI\s*决策\s*pass'), ('判断这轮不插话', None)),
    (re.compile(r'AI\s*主动调用群机器人'), ('叫群里的机器人来活跃气氛', None)),
    (re.compile(r'概率触发幻梦'), ('随机叫了幻梦来搭话', None)),
    (re.compile(r'群聊协调器回复异常'), ('群聊合并回复时出错', None)),
    (re.compile(r'群聊意图分析异常'), ('判断群聊意图时出错', None)),

    # ==================== 工具调用 ====================
    (re.compile(r'规则硬触发'), ('命中本地规则，直接启动对应工具', None)),
    (re.compile(r'命中工具\s*([^\s:]+)'), ('用上了工具', 1)),
    (re.compile(r'未命中工具'), ('没有用到工具，按普通聊天回复', None)),
    (re.compile(r'未知工具\s*([^\s:]+)'), ('遇到了不认识的工具', 1)),
    (re.compile(r'构建.*工具失败'), ('准备工具时出错', None)),

    # ==================== 等待 / 追问 ====================
    (re.compile(r'excuse\s*等待命中，消费'), ('收到对方的补充说明，继续处理', None)),
    (re.compile(r'等待用户回复超时'), ('等对方回复，等超时了', None)),
    (re.compile(r'未启用阻塞等待'), ('不需要等待对方回复', None)),

    # ==================== 图片 / 视觉 ====================
    (re.compile(r'\[视觉\].*视觉回复已发'), ('看过图片并回复了', None)),
    (re.compile(r'\[视觉\].*视觉回复为空'), ('看了图片，但没想出要说什么', None)),

    # ==================== NapCat 主动发送 ====================
    (re.compile(r'已发送'), ('主动发送完成', None)),
    (re.compile(r'发送失败'), ('主动发送失败', None)),

    # ==================== 其它常见 ====================
    (re.compile(r'获取群信息失败'), ('拿不到群信息', None)),
    (re.compile(r'获取好友列表失败'), ('拿不到好友列表', None)),
    (re.compile(r'获取群列表失败'), ('拿不到群列表', None)),
    (re.compile(r'读取(?:角色卡|配置).*失败'), ('读取配置失败', None)),
    (re.compile(r'记录\s*QQ\s*昵称映射失败'), ('记录群昵称失败，不影响聊天', None)),
    (re.compile(r'处理群消息异常'), ('处理群消息时出错了', None)),
    (re.compile(r'处理私聊消息异常'), ('处理私聊消息时出错了', None)),
    (re.compile(r'处理戳一戳异常'), ('处理戳一戳时出错了', None)),
    (re.compile(r'后置情绪更新异常'), ('更新角色情绪时出错了', None)),
    (re.compile(r'启动消耗'), ('启动扣掉了一些电池', None)),
    (re.compile(r'Traceback \(most recent call last\)'), ('出错了，下面是详细堆栈', None)),
]


def translate(text):
    """把一行日志的正文翻成 (短句, 关键值)。

    匹配不到返回 ('', '')，前端回退显示原文。
    """
    s = (text or '').strip()
    if not s:
        return '', ''
    for rx, (title, group_idx) in RULES:
        m = rx.search(s)
        if not m:
            continue
        detail = ''
        if group_idx:
            try:
                detail = (m.group(group_idx) or '').strip()
            except Exception:
                detail = ''
        return title, detail
    return '', ''
