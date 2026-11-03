# -*- coding: utf-8 -*-
# gui/tools/log_rules.py
r"""日志分类器：把一行日志判成"该不该给用户看"，以及看的时候显示成什么。

三层（tier）：
    story  用户想知道的事：收到 / 说了 / 发了 / 画了 / 表情 / 启动
    warn   值得看一眼，但不影响使用
    error  真出了问题（含堆栈归并后的一条）
    bg     后台细节：管道、参数、数值、轮询、进度条、已知无害的连接抖动
           —— 默认不显示，只计数（用户可一键展开）

约定：
    - EVENTS 的短句**不含变量**（稳定 i18n key），取到的值放 detail，前端拼成「短句：值」；
    - NOISE 命中的一律 bg，并带一个类别（access/frame/progress/conn/retry/boundary/stack/...），
      日志中心按类别统计"折叠了多少行"，不丢信息；
    - 连接类报错单独判：已知无害（10053/10054/no close frame/InvalidUpgrade）→ bg；
      其余连接失败 → tier=error + ev='连接中断'，并把它后面跟的堆栈一并吞进同一条；
    - 全部不命中 → 按 src 兜底（SRC_TIER），再不行按级别：ERROR→error，WARNING→warn，其余→bg。
"""

import re

TIER_STORY = 'story'
TIER_WARN = 'warn'
TIER_ERROR = 'error'
TIER_BG = 'bg'

# 场景键（前端映射成图标页签）
SCENE_CHAT = 'chat'      # 聊天
SCENE_VOICE = 'voice'    # 语音
SCENE_PHONE = 'phone'    # 手机
SCENE_PAINT = 'paint'    # 画图
SCENE_SING = 'sing'      # 唱歌
SCENE_MIND = 'mind'      # 内心/情绪
SCENE_SYS = 'sys'        # 系统

# ============================================================================
# 1. 噪音：命中即 bg（只计数）
#    顺序有意义：先判"明显是管道/轮询"的，再判别的。
# ============================================================================
NOISE_RULES = [
    # 1.1 HTTP 访问日志（手机端每 1~2 秒轮询 /api/tts/pending）
    ('access', re.compile(r'^\d+\.\d+\.\d+\.\d+ - - \[[^\]]+\] "(?:GET|POST|PUT|HEAD|DELETE) ')),
    # 1.2 桌面宠每帧注入参数
    ('frame', re.compile(r'\[vts\]\s*注入参数')),
    # 1.3 tqdm 进度条（含 \r 回刷残留）
    ('progress', re.compile(r'\d+%\|\S*\|\s*\d+/\d+|it/s\]|\[\d+:\d+<')),
    # 1.4 TTS 管道内部细节
    ('tts-pipe', re.compile(r'\[TTS->phone\]|播放片段 \d+|\[字幕\] chatStatus')),
    # 1.5 已知无害的连接抖动（客户端断开 / 浏览器探测）
    ('conn-quiet', re.compile(
        r'WinError 1005[34]|ConnectionAbortedError|ConnectionResetError|'
        r'RemoteDisconnected|no close frame received or sent|'
        r'InvalidUpgrade: invalid Connection header')),
    # 1.6 服务未起时的周期性重试
    ('retry', re.compile(r'识别服务未就绪|后台每秒重试|稍后自动连上')),
    # 1.7 语音识别边说边判的边界行
    ('boundary', re.compile(r'客户端(开始|结束)说话')),
    # 1.8 已知无影响的失败（δ-mem 引擎没开、VTS/桌宠没连）
    ('known-fail', re.compile(
        r'δ-mem 追加失败|VtubeStudio 尚未连接|桌宠尚未连接|'
        r'引擎未开启或不可达|本次指令已跳过')),
    # 1.9 判定过程的数值细节
    ('judge', re.compile(
        r'\[narration\]|\[表情\] 概率|\[表情\] 未命中|\[表情\] 命中|'
        r'\[改图判定\] 无改图窗口|\[群续聊\]|\[NapCat缓冲\]|\[NapCat群缓冲\]|'
        r'\[改图判定\] 命中改图窗口|未命中工具，走正常回复')),
    # 1.10 启动横幅 / 分隔线 / 插件清单
    ('banner', re.compile(r'^[=\-]{6,}$|^插件已(加载|关闭)')),
    # 1.11 其它诊断
    ('diag', re.compile(
        r'请求 LLM: merged=|分发工具调用:|客户端就绪|'
        r'\[奖励\] 启动消耗|已启用 Minecraft 日志读取')),
]

# 连接类报错里"值得让用户知道"的（会生成一条故障卡片）
CONN_ERROR = re.compile(
    r'WinError 1006[01]|WinError 1005[0-9]|WinError 1006[0-9]|'
    r'ConnectionRefusedError|NewConnectionError|Max retries exceeded|'
    r'目标计算机积极拒绝|远程主机强迫关闭|你的主机中的软件中止|'
    r'BrokenPipeError|ConnectionError')
# 堆栈块：一次异常从这几类行开始；后续缩进行/分隔线都算同一条
FAULT_START = re.compile(
    r'^(?:Traceback \(most recent call last\)|Exception occurred during processing of request|'
    r'Exception in thread|[-]{10,}$|.+?Error: )')
FAULT_CONT = re.compile(
    r'^(?:  File "|    |\s+[~^]{3,}$|[-]{10,}$|Traceback |\w*(?:Error|Exception)\b)')

# ============================================================================
# 2. 事件：命中即 story（用户真正想知道的事）
#    结构：(正则, 短句, 取值组号, 场景, 图标)
# ============================================================================
EVENTS = [
    # ---------- 聊天：收到 / 说出 ----------
    (re.compile(r'消息入队\s*[:：]\s*(.+)$'), '收到一条消息', 1, SCENE_CHAT, 'in'),
    (re.compile(r'\[AI回复\]\s*(.+)$'), '她说', 1, SCENE_CHAT, 'say'),
    (re.compile(r'\[CatPaws\]\s*台词[：:]\s*(.+)$'), '她说', 1, SCENE_PHONE, 'say'),
    (re.compile(r'\[CatPaws\]\s*提问已回答'), '手机操作提过问并记下了回答', None, SCENE_PHONE, 'in'),
    (re.compile(r'\[CatPaws\]\s*链路启动'), '开始操作手机', None, SCENE_PHONE, 'phone'),
    (re.compile(r'\[CatPaws\]\s*链路结束'), '手机操作结束', None, SCENE_PHONE, 'phone'),
    (re.compile(r'\[CatPaws\]\s*触发'), '被要求去操作手机', None, SCENE_PHONE, 'phone'),

    # ---------- QQ 收发 ----------
    (re.compile(r'\[NapCat\]\s*发送群@文本'), '在群里 @ 了人并说话', None, SCENE_CHAT, 'out'),
    (re.compile(r'\[NapCat\]\s*发送群文本'), '在群里说了一句', None, SCENE_CHAT, 'out'),
    (re.compile(r'\[NapCat\]\s*发送群图片'), '往群里发了一张图', None, SCENE_CHAT, 'pic'),
    (re.compile(r'\[NapCat\]\s*发送群文件'), '往群里发了一个文件', None, SCENE_CHAT, 'file'),
    (re.compile(r'\[NapCat\]\s*发送图片'), '发了一张图', None, SCENE_CHAT, 'pic'),
    (re.compile(r'\[NapCat\]\s*发送文本'), '回了一条消息', None, SCENE_CHAT, 'out'),
    (re.compile(r'\[NapCat\]\s*回复\s*([^\s:：]+)'), '回复了对方', 1, SCENE_CHAT, 'out'),
    (re.compile(r'\[NapCat群聊\]\s*回复'), '在群里回了一句', None, SCENE_CHAT, 'out'),
    (re.compile(r'\[群聊协调器\]\s*派发群'), '把几条群消息合起来回了一次', None, SCENE_CHAT, 'out'),
    (re.compile(r'\[插件\]\s*(\S+)\s*接管'), '插件接手了这个会话', 1, SCENE_CHAT, 'gear'),
    (re.compile(r'发送表情[:：]\s*(\S+)'), '发了个表情', 1, SCENE_CHAT, 'emoji'),

    # ---------- 工具 / 画图 ----------
    (re.compile(r'规则硬触发\s*(\S+)'), '走捷径直接用了工具', 1, SCENE_SYS, 'tool'),
    (re.compile(r'本地规则硬触发命中\s*(\S+)'), '走捷径直接用了工具', 1, SCENE_SYS, 'tool'),
    (re.compile(r'\[改图判定\]\s*判定为「改图」'), '接着改图了', None, SCENE_PAINT, 'paint'),
    (re.compile(r'\[改图判定\]\s*判定为「非改图」'), '判断这次不用改图', None, SCENE_PAINT, 'paint'),
    (re.compile(r'开始作画|Flux 绘画 QQ 开局'), '开始画画', None, SCENE_PAINT, 'paint'),
    (re.compile(r'画完了|已发送绘画|出图完成'), '画完发出去了', None, SCENE_PAINT, 'paint'),
    (re.compile(r'\[视觉\]\s*视觉回复已发'), '看过图并回了一句', None, SCENE_VOICE, 'eye'),

    # ---------- 唱歌 ----------
    (re.compile(r'接下来播放《(.+?)》'), '开始放歌', 1, SCENE_SING, 'music'),
    (re.compile(r'接下来翻唱《(.+?)》'), '开始翻唱', 1, SCENE_SING, 'music'),

    # ---------- 内心 / 情绪 ----------
    (re.compile(r'情绪指令\s*[:：]\s*(\w+)\s*\(intensity=([\d.]+)\)'),
     '心情变成了', 1, SCENE_MIND, 'heart'),

    # ---------- 语音 ----------
    (re.compile(r'已连接 SenseVoice 服务器'), '语音识别连上了', None, SCENE_VOICE, 'mic'),

    # ---------- 系统 / 启停 ----------
    (re.compile(r'开始启动人工智能【(.+?)】'), '启动了', 1, SCENE_SYS, 'power'),
    (re.compile(r'AI虚拟主播-启动成功'), '启动完成', None, SCENE_SYS, 'power'),
    (re.compile(r'已连接\s*NapCat'), 'QQ 服务连上了', None, SCENE_SYS, 'link'),
    (re.compile(r'NapCat\s*客户端已启动'), 'QQ 服务启动了', None, SCENE_SYS, 'link'),
    (re.compile(r'NapCat\s*已停止'), 'QQ 服务停了', None, SCENE_SYS, 'link'),
    (re.compile(r'连接异常.*(?:重连|重试)'), '和 QQ 服务断开，正在重连', None, SCENE_SYS, 'link'),
]

# ============================================================================
# 3. 兜底：按来源模块定级
# ============================================================================
SRC_TIER = [
    (re.compile(r'func[\\/]tts[\\/]'), TIER_BG),
    (re.compile(r'func[\\/]pipeline[\\/](llm_tts|toolbox_tts|subtitle|llm_emotion)'), TIER_BG),
    (re.compile(r'func[\\/]toolbox[\\/]port[\\/]'), TIER_BG),
    (re.compile(r'func[\\/]sensevoice[\\/]'), TIER_BG),
    (re.compile(r'func[\\/]vts[\\/]'), TIER_BG),
    (re.compile(r'func[\\/]catbrain[\\/]'), TIER_BG),
    (re.compile(r'func[\\/]llm[\\/]'), TIER_BG),
    (re.compile(r'func[\\/]toolbox[\\/]napcat[\\/]analysis'), TIER_BG),
    (re.compile(r'func[\\/]'), TIER_BG),
    (re.compile(r'api\.py'), TIER_BG),
]


def _noise(msg):
    for cat, rx in NOISE_RULES:
        if rx.search(msg):
            return cat
    return ''


def _event(msg):
    for rx, title, group, scene, icon in EVENTS:
        m = rx.search(msg)
        if not m:
            continue
        detail = ''
        if group:
            try:
                detail = (m.group(group) or '').strip()
            except Exception:
                detail = ''
        return title, detail, scene, icon
    return '', '', '', ''


def classify(msg, src='', lv=''):
    """把一行日志归类。

    返回 dict：
        tier    story / warn / error / bg
        noise   噪音类别（bg 时有值，用于"折叠了多少行"的统计）
        title   短句（i18n key，bg 时为空）
        detail  取到的值（可空）
        scene   chat/voice/phone/paint/sing/mind/sys
        icon    图标键
        fault   是否是一条"连接中断"故障（前端画成故障卡片）
    """
    text = (msg or '').strip()
    out = {'tier': TIER_BG, 'noise': '', 'title': '', 'detail': '',
           'scene': SCENE_SYS, 'icon': 'dot', 'fault': False}
    if not text:
        out['tier'] = TIER_BG
        out['noise'] = 'empty'
        return out

    # 1) 已知噪音：直接后台
    cat = _noise(text)
    if cat:
        out['tier'] = TIER_BG
        out['noise'] = cat
        return out

    # 2) 连接失败（非无害类）：一条故障卡片
    if CONN_ERROR.search(text):
        out['tier'] = TIER_ERROR
        out['title'] = '连接中断'
        out['detail'] = text[:120]
        out['icon'] = 'link'
        out['fault'] = True
        return out

    # 3) 事件表
    title, detail, scene, icon = _event(text)
    if title:
        out.update(tier=TIER_STORY, title=title, detail=detail,
                   scene=scene or SCENE_SYS, icon=icon or 'dot')
        return out

    # 4) 真异常（堆栈 / ERROR 级别）→ 错误层
    if lv in ('ERROR', 'CRITICAL', 'FATAL'):
        out['tier'] = TIER_ERROR
        out['title'] = '出错了'
        out['detail'] = text[:120]
        out['icon'] = 'error'
        return out

    # 5) 按来源模块兜底
    for rx, tier in SRC_TIER:
        if src and rx.search(src):
            out['tier'] = tier
            out['noise'] = 'module'
            return out

    # 6) 剩下按级别：警告给用户看一眼，其余后台
    if lv in ('WARN', 'WARNING'):
        out['tier'] = TIER_WARN
        out['title'] = '提示'
        out['detail'] = text[:120]
        out['icon'] = 'warn'
        return out
    out['tier'] = TIER_BG
    out['noise'] = 'other'
    return out


def translate(text):
    """兼容旧接口：返回 (短句, 关键值)；非事件行返回 ('', '')。"""
    r = classify(text)
    if r['tier'] in (TIER_STORY, TIER_WARN, TIER_ERROR):
        return r['title'], r['detail']
    return '', ''
