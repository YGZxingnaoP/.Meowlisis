# -*- coding: utf-8 -*-
# gui/tools/launcher.py
r"""统一子服务启动器。

背景：config_gui.py 里原本每个服务各写一份 subprocess.Popen（win32/非 win32 分支、
cwd/env 拼装、窗口标志），重复且细节不一致，日志落点也不统一。

现在所有服务的启动都收敛到本文件：
    - 同一套 win32 / 非 win32 处理；
    - 统一无窗口（CREATE_NO_WINDOW），不再弹黑框；
    - 统一把 stdout/stderr 追加写入 logs/svc_<key>.log；
    - 统一环境变量（PYTHONUNBUFFERED / PYTHONIOENCODING）与 runtime 解释器兜底。

每个服务仍然是**各自独立**的进程，互不影响；只是"启动方式"只有这一份实现。

服务清单（SERVICES / ORDER）也放在这里，属于"一处配置"：
"怎么启动"（launch）与"日志在哪、怎么查进程"（log / cmdline）写在一起。
"""

import os
import sys
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

# ============================================================================
# 服务注册表
#   name      : 显示名
#   endpoint  : config_gui.py 里的启动端点（由 loghub 接管成"走本启动器"）
#   log       : 日志文件（相对项目根）；{date} 会替换成当天日期
#   builtin   : True = 该日志是程序本来就写的（不由本启动器重定向）
#   cmdline   : 状态/停止兜底用的命令行关键字（反查进程）
#   launch    : 启动方式
#       kind=python     : runtime python 跑 script（相对项目根），cwd 相对项目根
#       kind=bat        : 直接跑 bat
#       kind=bat_or_py  : 有 bat 就跑 bat，否则 runtime python 跑 script
#       kind=sovits     : GPT-SoVITS 专用（参数来自 config.yml 的 tts.gpt-sovits 地址）
#       kind=managed    : 由 Python 侧管理器启动（绘画引擎），不是普通子进程
# ============================================================================
SERVICES = {
    'main': {
        'name': '主程序', 'endpoint': 'start_main',
        'log': 'logs/log_{date}.txt', 'builtin': True,
        'cmdline': ['api.py'], 'desc': 'Meowlisis 主程序（语音/LLM/桌宠等）',
        'launch': {'kind': 'python', 'script': 'api.py', 'cwd': '.'},
    },
    'painting': {
        'name': '绘画引擎', 'endpoint': 'start_painting_comfy',
        'log': 'logs/comfy_engine.log', 'builtin': True,
        'cmdline': ['--disable-auto-launch'], 'desc': '内置 ComfyUI 内核（常驻）',
        'launch': {'kind': 'managed'},
    },
    'sovits': {
        'name': 'SoVITS', 'endpoint': 'start_sovits',
        'log': 'logs/svc_sovits_{date}.log', 'cmdline': ['.Sovits'], 'desc': 'GPT-SoVITS 语音合成',
        'launch': {'kind': 'sovits'},
    },
    'sensevoice': {
        'name': 'SenseVoice', 'endpoint': 'start_sensevoice',
        'log': 'logs/svc_sensevoice_{date}.log', 'cmdline': ['.SenseVoice'], 'desc': '语音识别 + 声纹',
        'launch': {'kind': 'bat_or_py',
                   'bat': '.vendor/.SenseVoice/start.bat',
                   'script': '.vendor/.SenseVoice/server/sensevoice_server.py',
                   'cwd': '.vendor/.SenseVoice'},
    },
    'napcat': {
        'name': 'NapCat', 'endpoint': 'start_napcat',
        'log': 'logs/svc_napcat_{date}.log', 'cmdline': ['NapCatWinBootMain'], 'desc': 'QQ 机器人',
        'launch': {'kind': 'bat', 'bat': '.vendor/.NapCat/NapCat.Shell/napcat.quick.bat',
                   'cwd': '.vendor/.NapCat/NapCat.Shell'},
    },
    'netease': {
        'name': '网易云搜歌', 'endpoint': 'start_netease',
        'log': 'logs/svc_netease_{date}.log', 'cmdline': ['.NeteaseMusic'], 'desc': '网易云搜歌服务',
        'launch': {'kind': 'python', 'script': '.vendor/.NeteaseMusic/server/server.py',
                   'cwd': '.vendor/.NeteaseMusic'},
    },
    'rvc': {
        'name': 'RVC 翻唱', 'endpoint': 'start_rvc',
        'log': 'logs/svc_rvc_{date}.log', 'cmdline': ['.RVC'], 'desc': 'RVC 翻唱服务',
        'launch': {'kind': 'python', 'script': '.vendor/.RVC/cover_server.py', 'cwd': '.vendor/.RVC'},
    },
    'desktopet': {
        'name': '桌宠', 'endpoint': 'start_desktopet',
        'log': 'logs/svc_desktopet_{date}.log', 'cmdline': ['.desktopet'], 'desc': '桌宠',
        'launch': {'kind': 'bat', 'bat': '.vendor/.desktopet/start.bat', 'cwd': '.vendor/.desktopet'},
    },
    'phone': {
        'name': '手机接口', 'endpoint': 'start_phone',
        'log': 'logs/svc_phone_{date}.log', 'cmdline': ['.cam'], 'desc': '手机端接口服务',
        'launch': {'kind': 'python', 'script': '.vendor/.cam/serve.py', 'cwd': '.vendor/.cam'},
    },
}

ORDER = ['main', 'painting', 'sovits', 'sensevoice', 'napcat', 'netease', 'rvc', 'desktopet', 'phone']


# ============================================================================
# 统一启动
# ============================================================================
def python_exe(base: Path) -> str:
    """优先用主项目自带 runtime 解释器（依赖齐全），否则回退当前解释器"""
    runtime_python = Path(base) / "runtime" / "311" / "python.exe"
    return str(runtime_python) if runtime_python.exists() else sys.executable


def spawn(args, cwd=None, env=None, log_key=None):
    """统一启动一个子进程，返回 Popen。

    args    : 命令列表
    cwd     : 工作目录
    env     : 追加/覆盖的环境变量（与父进程环境合并）
    log_key : 日志标识；给定则 stdout/stderr 追加写入 logs/svc_<log_key>_<日期>.log
    """
    """统一启动一个子进程，返回 Popen。

    args    : 命令列表
    cwd     : 工作目录
    env     : 追加/覆盖的环境变量（与父进程环境合并）
    log_key : 日志标识；给定则 stdout/stderr 追加写入 logs/svc_<log_key>.log
    """
    child_env = os.environ.copy()
    child_env.setdefault("PYTHONUNBUFFERED", "1")     # 否则输出被块缓冲，日志页半天不动
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        for k, v in env.items():
            child_env[str(k)] = str(v)

    kwargs = {
        "cwd": str(cwd) if cwd else None,
        "env": child_env,
        "stdin": subprocess.DEVNULL,
    }

    logf = None
    if log_key:
        try:
            log_dir = _log_dir()          # 所有服务日志统一落在 <项目根>/logs/
            log_dir.mkdir(parents=True, exist_ok=True)
            day = date.today().strftime("%Y-%m-%d")
            logf = open(log_dir / ("svc_%s_%s.log" % (log_key, day)), "ab", buffering=0)
            kwargs["stdout"] = logf
            kwargs["stderr"] = subprocess.STDOUT
        except Exception:
            logf = None
    if logf is None:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    if sys.platform == "win32":
        # 统一无窗口启动；GUI 程序自己的窗口不受影响
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        return subprocess.Popen([str(a) for a in args], **kwargs)
    finally:
        if logf is not None:
            try:
                logf.close()   # 关掉父进程副本；子进程持有自己的句柄，继续写
            except Exception:
                pass


_LOG_DIR = None


def _log_dir() -> Path:
    """统一日志目录：<项目根>/logs（未注入 base 时按本文件位置上溯三级推算）"""
    global _LOG_DIR
    if _LOG_DIR is not None:
        return _LOG_DIR
    return Path(__file__).resolve().parents[2] / 'logs'    # gui/tools/launcher.py → 项目根


def set_base(base):
    """注入项目根目录（由 loghub.register 调用），日志目录随之确定"""
    global _LOG_DIR
    _LOG_DIR = Path(base).resolve() / "logs"
    return _LOG_DIR


def _sovits_host_port(base: Path):
    """从 config.yml 的 tts.gpt-sovits.gpt_sovits_url 解析监听地址/端口"""
    try:
        import yaml
        cfg_path = Path(base) / 'config.yml'
        if cfg_path.exists():
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            url = ((cfg.get('tts') or {}).get('gpt-sovits') or {}).get(
                'gpt_sovits_url', 'http://127.0.0.1:9880')
            p = urlparse(str(url))
            return (p.hostname or '127.0.0.1'), (p.port or 9880)
    except Exception:
        pass
    return '127.0.0.1', 9880


def build_command(key: str, base):
    """把某个服务的启动方式解析成 (args, cwd, env)；不支持的返回 (None, 原因)"""
    s = SERVICES.get(key)
    if not s:
        return None, '未知服务: %s' % key
    base = Path(base)
    spec = s.get('launch') or {}
    kind = spec.get('kind')

    if kind == 'managed':
        return None, 'managed'

    env = {}
    cwd = (base / spec['cwd']) if spec.get('cwd') else base

    if kind == 'python':
        script = base / str(spec.get('script') or '')
        if not script.exists():
            return None, '%s not found' % spec.get('script')
        return [python_exe(base), str(script)], cwd, env

    if kind == 'bat':
        bat = base / str(spec.get('bat') or '')
        if not bat.exists():
            return None, '%s not found' % spec.get('bat')
        return [str(bat)], cwd, env

    if kind == 'bat_or_py':
        bat = base / str(spec.get('bat') or '')
        if bat.exists():
            return [str(bat)], cwd, env
        script = base / str(spec.get('script') or '')
        if not script.exists():
            return None, '%s not found' % spec.get('script')
        return [python_exe(base), str(script)], cwd, env

    if kind == 'sovits':
        d = base / '.vendor' / '.Sovits'
        api_path = d / 'api_v2.py'
        if not api_path.exists():
            return None, 'api_v2.py not found'
        host, port = _sovits_host_port(base)
        infer_path = d / 'tts_infer.yaml'
        ffmpeg_bin = d / 'FFmpeg' / 'bin'
        if ffmpeg_bin.exists():
            env['PATH'] = str(ffmpeg_bin) + os.pathsep + os.environ.get('PATH', '')
        args = [python_exe(base), str(api_path), '-c', str(infer_path),
                '-a', str(host), '-p', str(port)]
        return args, d, env

    return None, '未配置启动方式'


def start(key: str, base):
    """启动某个服务（各自独立进程）。返回 (ok: bool, message: str, proc)。

    proc 是 subprocess.Popen（managed 类型为 None）—— 调用方持有它就能 O(1)
    判断"在不在跑""pid 是多少"，不必再去扫进程表。
    """
    s = SERVICES.get(key)
    if not s:
        return False, '未知服务: %s' % key, None

    spec = s.get('launch') or {}
    if spec.get('kind') == 'managed':
        # 绘画引擎由 Python 侧管理器负责（常驻、自带 pid 与停止逻辑）
        try:
            from func.toolbox.flux_painter.config import TBFluxPainterConfig
            from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter
            cfg = TBFluxPainterConfig()
            cfg.engine_window = False          # 不再弹引擎窗口
            import threading

            def _boot():
                try:
                    get_managed_painter(cfg).start()
                except Exception:
                    pass

            threading.Thread(target=_boot, daemon=True).start()
            return True, '已启动', None
        except Exception as e:
            return False, str(e), None

    args, cwd, env = build_command(key, base)
    if args is None:
        return False, str(cwd), None
    try:
        proc = spawn(args, cwd=cwd, env=env, log_key=key)
        return True, '已启动', proc
    except Exception as e:
        return False, str(e), None
