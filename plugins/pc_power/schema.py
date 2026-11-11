# -*- coding: utf-8 -*-
"""睡前关机：GUI 配置面板 schema（纯数据）。

危险功能，默认关闭；第一次打开请保持 dry_run=true 跑一遍流程，确认无误再关掉。
"""

PLUGIN = {
    "id": "pc_power",
    "title": "睡前关机",
    "version": "1.0.0",
    "group": "core",
    "emoji": "\U0001F319",          # 🌙
    "default_enabled": False,
}

FIELDS = [
    {"key": "enabled", "label": "启用睡前关机", "type": "check", "default": False,
     "help": "只作用于主链路（语音/聊天），QQ 链路完全不加载这个工具"},

    {"key": "dry_run", "label": "试运行（只走流程不真关机）", "type": "check", "default": True,
     "help": "打开时到点只写日志，不结束进程也不关机；确认流程无误后再关掉"},

    # ---------------- 监听 ----------------
    {"key": "window_sec", "label": "监听时长（秒）", "type": "num", "default": 300,
     "min": 10, "max": 3600, "step": 10,
     "help": "开始监听后，主人每说一句话就重写这个倒计时；到点没人说话才继续关机流程"},
    {"key": "trigger_phrase", "label": "回复触发语句", "type": "text",
     "default": "愿弦月之眼保佑你",
     "help": "角色回复里出现这句话就立刻开始监听（只看主链路回复，弹幕/QQ 不算）"},
    {"key": "watch_reply", "label": "监听角色回复", "type": "check", "default": True,
     "help": "关闭后只能靠工具调用开始监听"},
    {"key": "min_goodnight", "label": "至少几次晚安", "type": "num", "default": 2,
     "min": 1, "max": 10, "step": 1,
     "help": "工具触发时，如果主人没说「睡觉/去睡/困了」，至少要连续几次晚安才真的开始监听"},
    {"key": "goodnight_gap_sec", "label": "晚安计数有效间隔（秒）", "type": "num", "default": 1800,
     "min": 60, "max": 21600, "step": 60,
     "help": "两次晚安间隔超过这个时长就重新计数"},

    # ---------------- 取消 / 确认 ----------------
    {"key": "cancel_words", "label": "取消词（命中就不关机）", "type": "tags",
     "default": ["别关", "不要关", "别关机", "不关电脑", "先别关", "不准关"],
     "help": "监听期间命中任意一个，立刻取消本次关机"},
    {"key": "confirm_words", "label": "确认词（有下载时用）", "type": "tags",
     "default": ["关吧", "关掉", "确认关机", "关机吧", "可以关了", "现在关"],
     "help": "到点发现还有下载/上传时，转为确认态；只有命中这些词才会真的关机"},

    # ---------------- 下载 / 上传体检 ----------------
    {"key": "check_transfer", "label": "关机前检查下载/上传进程", "type": "check", "default": True,
     "help": "有这类进程时不直接关，先问一句等主人确认"},
    {"key": "transfer_keywords", "label": "下载/上传进程关键字", "type": "tags",
     "default": ["qbittorrent", "utorrent", "transmission", "aria2", "motrix",
                 "thunder", "xunlei", "idm", "baidunetdisk", "aliyunpan",
                 "115", "steam", "epicgameslauncher", "battle.net"],
     "help": "匹配进程名或命令行（不区分大小写）。匹配不到就不算占用"},
    {"key": "net_busy_mbps", "label": "网络繁忙阈值（MB/s，0=关闭）", "type": "num", "default": 2.0,
     "min": 0, "max": 100, "step": 0.5,
     "help": "整体吞吐超过该值也当作「可能在上传/下载」，转确认态；关掉可避免误报"},
    {"key": "confirm_window_sec", "label": "确认等待时长（秒）", "type": "num", "default": 120,
     "min": 10, "max": 900, "step": 10,
     "help": "等不到确认就取消关机（默认安全），不会硬关"},
    {"key": "transfer_ask_hint", "label": "有下载时的询问意图", "type": "text",
     "default": "告诉主人还有东西在下载/上传（{names}），问他要不要现在关掉电脑。",
     "help": "这是给角色的内部意图，不是台词；真正怎么说由角色自己组织。可用 {names} / {count} 占位"},

    # ---------------- 关机 ----------------
    {"key": "mode", "label": "关机方式", "type": "select", "default": "shutdown",
     "options": [{"value": "shutdown", "label": "关机（shutdown /s）"},
                 {"value": "hibernate", "label": "休眠（shutdown /h）"},
                 {"value": "sleep", "label": "睡眠"}],
     "help": "想保留进程状态、以后做定时唤醒，用休眠"},
    {"key": "shutdown_delay_sec", "label": "关机倒计时（秒）", "type": "num", "default": 20,
     "min": 0, "max": 600, "step": 5,
     "help": "留给系统收尾的时间；倒计时内仍可用 shutdown /a 撤销"},
    {"key": "stop_processes", "label": "关机前结束本项目服务进程", "type": "check", "default": True,
     "help": "按下面的关键字结束 SoVITS / SenseVoice / NapCat / 绘画引擎等；主程序交给系统关机"},
    {"key": "process_keywords", "label": "服务进程关键字", "type": "tags",
     "default": [".Sovits", ".SenseVoice", ".NeteaseMusic", ".RVC",
                 ".desktopet", ".cam", ".CatPaws", ".ComfyNode", "NapCatWinBootMain"],
     "help": "只匹配本项目服务的命令行特征，避免误杀其它软件"},
    {"key": "shutdown_note", "label": "关机提示语（系统关机提示框）", "type": "text",
     "default": "喵呜要睡了",
     "help": "会显示在 Windows 的关机提示里"},
]
