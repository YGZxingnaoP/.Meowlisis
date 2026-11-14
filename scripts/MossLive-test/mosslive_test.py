# -*- coding: utf-8 -*-
# scripts/MossLive-test/mosslive_test.py
# MOSS-Live 全双工实时对话 —— 独立联调脚本。
#
# 用法（在项目根目录）：
#   runtime\311\python.exe scripts\MossLive-test\mosslive_test.py                 # 正式通话
#   runtime\311\python.exe scripts\MossLive-test\mosslive_test.py --dry-run       # 只看提示词/音色/工具
#   runtime\311\python.exe scripts\MossLive-test\mosslive_test.py --selftest      # 本机自检（不连网）
#   直接双击 scripts\MossLive-test\run.bat 也可以。
#
# 说明：本测试不接短期记忆/长期记忆，也不启用 client delegation；
# 系统提示词、参考音频都直接引用主项目里的文件（见 config.json 的 prompt / voice 段）。

import argparse
import asyncio
import sys
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mosslive.config import ConfigError, TestConfig  # noqa: E402
from mosslive.console import Console  # noqa: E402
from mosslive.prompt import ProjectPromptBuilder, PromptError  # noqa: E402
from mosslive.session import MossLiveSession, ProtocolError  # noqa: E402
from mosslive.tools import ToolBox  # noqa: E402
from mosslive.voice import (  # noqa: E402
    VoiceError,
    prepare_sample,
    resolve_ref_audio,
    resolve_voice,
)


BANNER = "MOSS-Live 全双工测试 · Meowlisis"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MOSS-Live 全双工实时对话测试（独立运行，不启动主程序）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config", default=str(BASE_DIR / "config.json"), help="配置文件路径")
    p.add_argument("--dry-run", action="store_true", help="只构建提示词/音色/工具，不连接服务")
    p.add_argument("--selftest", action="store_true", help="本机自检：提示词、截屏、音频设备、工具（不连网）")
    p.add_argument("--no-mic", action="store_true", help="关闭麦克风（改为持续发送静音）")
    p.add_argument("--no-screen", action="store_true", help="关闭屏幕推流")
    p.add_argument("--screen-interval", type=int, default=None, help="屏幕帧间隔毫秒（>=200）")
    p.add_argument("--monitor", type=int, default=None, help="mss 显示器序号，0=全部，1=主屏")
    p.add_argument("--input-device", type=int, default=None, help="麦克风设备序号（-1 默认）")
    p.add_argument("--output-device", type=int, default=None, help="扬声器设备序号（-1 默认）")
    p.add_argument("--volume", type=float, default=None, help="播放音量倍数，1.0 原样")
    p.add_argument("--voice", default=None, help="直接指定已有 voice_id（等价 voice.mode=name）")
    p.add_argument("--no-clone", action="store_true", help="不复刻参考音频，改用 voice.fallback_name")
    p.add_argument("--model", default=None, help="覆盖 api.model")
    p.add_argument("--api-key", default=None, help="临时覆盖 API Key（优先于 config/env）")
    p.add_argument("--verbose", action="store_true", help="打印全部原始事件")
    p.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARN", "ERROR"], help="日志级别")
    p.add_argument("--list-devices", action="store_true", help="列出音频设备序号后退出")
    return p


def apply_overrides(cfg: TestConfig, args):
    if args.no_mic:
        cfg.audio["input_enabled"] = False
    if args.no_screen:
        cfg.screen["enabled"] = False
    if args.screen_interval is not None:
        cfg.screen["interval_ms"] = args.screen_interval
    if args.monitor is not None:
        cfg.screen["monitor"] = args.monitor
    if args.input_device is not None:
        cfg.audio["input_device"] = args.input_device
    if args.output_device is not None:
        cfg.audio["output_device"] = args.output_device
    if args.volume is not None:
        cfg.audio["volume"] = args.volume
    if args.model:
        cfg.api["model"] = args.model
    if args.api_key:
        cfg.api["api_key"] = args.api_key
    if args.voice:
        cfg.voice["mode"] = "name"
        cfg.voice["name"] = args.voice
    if args.no_clone:
        fallback = str(cfg.voice.get("fallback_name") or "").strip()
        if fallback:
            cfg.voice["mode"] = "name"
            cfg.voice["name"] = fallback
        else:
            cfg.voice["mode"] = "default"
    if args.verbose:
        cfg.log["verbose_events"] = True
        cfg.log["show_partial"] = True
        cfg.log["level"] = "DEBUG"
    if args.log_level:
        cfg.log["level"] = args.log_level
    cfg.validate()


def make_console(cfg: TestConfig) -> Console:
    return Console(
        level=str(cfg.log.get("level") or "INFO"),
        sessions_dir=cfg.local_path(cfg.log.get("sessions_dir") or "sessions"),
        save_events=bool(cfg.log.get("save_events", True)),
        verbose_events=bool(cfg.log.get("verbose_events", False)),
        show_partial=bool(cfg.log.get("show_partial", False)),
    )


def print_prompt_preview(console: Console, bundle):
    console.info("—— 系统提示词 ——")
    for line in bundle.summary():
        console.info(line)
    preview = bundle.persona[:600].replace("\n", "\n    ")
    console.info("persona 预览:\n    " + preview + ("…" if len(bundle.persona) > 600 else ""))
    instr_preview = bundle.instructions[:400].replace("\n", "\n    ")
    console.info("instructions 预览:\n    " + instr_preview + ("…" if len(bundle.instructions) > 400 else ""))


def run_dry(cfg: TestConfig, console: Console):
    builder = ProjectPromptBuilder(cfg, console)
    bundle = builder.build()
    print_prompt_preview(console, bundle)

    voice = resolve_voice(cfg, bundle.persona_name, console, allow_network=False)
    console.info(voice.describe())

    tools = ToolBox(cfg, console)
    defs = tools.definitions()
    console.info(f"工具定义 {len(defs)} 个: " + ", ".join(d["name"] for d in defs))

    console.info("—— 媒体 ——")
    console.info(f"上行: 16kHz PCM16（0x00 前缀）{'开' if cfg.audio.get('input_enabled') else '关'}")
    console.info(
        f"屏幕: {'开' if cfg.screen.get('enabled') else '关'} "
        f"{cfg.screen.get('max_long_side')}px/{cfg.screen.get('interval_ms')}ms/"
        f"q={cfg.screen.get('jpeg_quality')}"
    )
    out = cfg.session.get("output_audio") or {}
    console.info(f"下行: {out.get('format')}@{out.get('sample_rate')}Hz，回执={cfg.session.get('playback')}")
    console.info("演练结束（未连接服务）。")


def _probe_audio(cfg: TestConfig, console: Console) -> bool:
    try:
        import pyaudio
    except Exception as e:
        console.warn(f"PyAudio 不可用: {e}")
        return False
    pa = pyaudio.PyAudio()
    ok = True
    try:
        # 输入
        rate_in = None
        for rate in (16000, 48000, 44100):
            try:
                stream = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, input=True,
                                 input_device_index=(cfg.audio.get("input_device")
                                                     if int(cfg.audio.get("input_device") or -1) >= 0 else None),
                                 frames_per_buffer=int(rate * 0.02))
                rate_in = rate
                break
            except Exception:
                continue
        if rate_in is None:
            console.warn("麦克风打不开（自检不通过项，不影响 --dry-run）")
            ok = False
        else:
            data = stream.read(int(rate_in * 0.3), exception_on_overflow=False)
            stream.stop_stream()
            stream.close()
            console.info(f"麦克风: {rate_in}Hz 读取 {len(data)} 字节（0.3 秒）")
        # 输出
        rate_out = None
        for rate in (48000, 44100):
            try:
                stream = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, output=True,
                                 output_device_index=(cfg.audio.get("output_device")
                                                      if int(cfg.audio.get("output_device") or -1) >= 0 else None),
                                 frames_per_buffer=int(rate * 0.01))
                rate_out = rate
                break
            except Exception:
                continue
        if rate_out is None:
            console.warn("扬声器打不开（自检不通过项）")
            ok = False
        else:
            stream.write(b"\x00" * (int(rate_out * 0.2) * 2), exception_on_underflow=False)
            stream.stop_stream()
            stream.close()
            console.info(f"扬声器: {rate_out}Hz 写入 0.2 秒静音")
    finally:
        pa.terminate()
    return ok


def run_selftest(cfg: TestConfig, console: Console) -> int:
    ok = True
    console.info(f"配置: {cfg.path}")
    console.info(cfg.summary())

    builder = ProjectPromptBuilder(cfg, console)
    try:
        bundle = builder.build()
    except PromptError as e:
        console.error(f"提示词构建失败: {e}")
        return 3
    print_prompt_preview(console, bundle)

    try:
        voice = resolve_voice(cfg, bundle.persona_name, console, allow_network=False)
        console.info(voice.describe())
    except VoiceError as e:
        console.warn(f"音色解析失败: {e}")
        ok = False

    if str(cfg.voice.get("mode")) == "clone":
        console.info("—— 参考音频 ——")
        ref_path, _meta = resolve_ref_audio(cfg, bundle.persona_name, console)
        if not ref_path:
            console.warn("没有找到参考音频，正式运行时会回落到 fallback_name")
        else:
            try:
                sample = prepare_sample(
                    ref_path, int((cfg.voice.get("clone") or {}).get("max_seconds") or 29), console
                )
                console.info(
                    f"参考音频可上传: {sample.name} {sample.stat().st_size / 1024:.0f} KB"
                    "（临时文件，自检后删除）"
                )
                sample.unlink(missing_ok=True)
            except VoiceError as e:
                console.error(f"参考音频处理失败: {e}")
                ok = False

    console.info("—— 屏幕抓帧 ——")
    from mosslive.screen import probe_screen
    probe = probe_screen(cfg.screen, console)
    if probe.get("ok"):
        console.info(f"抓屏成功: {probe['size'][0]}x{probe['size'][1]}，JPEG {probe['jpeg_bytes'] / 1024:.1f} KB")
    else:
        console.error(f"抓屏失败: {probe.get('error')}")
        ok = False

    console.info("—— 音频设备 ——")
    if not _probe_audio(cfg, console):
        ok = False

    console.info("—— 工具 ——")
    tools = ToolBox(cfg, console)
    defs = tools.definitions()
    console.info(f"工具定义 {len(defs)} 个: " + ", ".join(d["name"] for d in defs))
    if "get_time" in tools.enabled:
        console.info("get_time → " + tools.execute("get_time", {}))
    if "list_windows" in tools.enabled:
        result = tools.execute("list_windows", {})
        console.info("list_windows → " + (result[:200] + "…" if len(result) > 200 else result))
    if "search_files" in tools.enabled:
        result = tools.execute("search_files", {"query": "class MossLiveSession", "max_results": 3})
        console.info("search_files → " + (result[:300] + "…" if len(result) > 300 else result))

    if cfg.screen.get("save_frames"):
        console.warn("screen.save_frames=true 会把帧写进 frames/，联调完记得清理")

    if ok:
        console.info("自检通过。")
        return 0
    console.warn("自检完成，但有未通过项（上面标了警告/错误）。")
    return 1


def run_session(cfg: TestConfig, console: Console) -> int:
    builder = ProjectPromptBuilder(cfg, console)
    try:
        bundle = builder.build()
    except PromptError as e:
        console.error(f"提示词构建失败: {e}")
        return 3

    console.info("—— 系统提示词 ——")
    for line in bundle.summary():
        console.info(line)

    if not cfg.api_key:
        console.error(cfg.key_hint())
        return 2

    try:
        voice = resolve_voice(cfg, bundle.persona_name, console)
    except VoiceError as e:
        console.error(f"音色解析失败: {e}")
        return 3
    console.info(voice.describe())

    session = MossLiveSession(cfg, bundle, voice, console)
    try:
        session_id = asyncio.run(session.run())
        console.info(f"会话结束: {session_id or '(未建立)'}")
        return 0
    except ProtocolError as e:
        console.error(str(e))
        if cfg.log.get("level") == "DEBUG":
            console.debug(traceback.format_exc())
        return 4
    finally:
        console.close()


def list_devices():
    """列出 PyAudio 设备，方便填 input_device / output_device"""
    try:
        import pyaudio
    except Exception as e:
        print(f"PyAudio 不可用: {e}")
        return
    pa = pyaudio.PyAudio()
    try:
        print(f"{'idx':>4} {'in':>3} {'out':>4} {'rate':>6}  name")
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            print(
                f"{i:>4} {d.get('maxInputChannels', 0):>3} {d.get('maxOutputChannels', 0):>4} "
                f"{int(d.get('defaultSampleRate', 0)):>6}  {d.get('name', '')}"
            )
        try:
            print(f"默认输入: {pa.get_default_input_device_info().get('index')}")
        except Exception:
            print("默认输入: 无")
        try:
            print(f"默认输出: {pa.get_default_output_device_info().get('index')}")
        except Exception:
            print("默认输出: 无")
    finally:
        pa.terminate()


def main() -> int:
    args = build_parser().parse_args()
    try:
        cfg = TestConfig.load(args.config)
        apply_overrides(cfg, args)
    except ConfigError as e:
        print(f"配置错误: {e}", file=sys.stderr)
        return 2

    if args.list_devices:
        list_devices()
        return 0

    print("=" * 60)
    print(BANNER)
    print("=" * 60)

    console = make_console(cfg)
    try:
        if args.selftest:
            return run_selftest(cfg, console)
        if args.dry_run:
            run_dry(cfg, console)
            return 0
        return run_session(cfg, console)
    except KeyboardInterrupt:
        console.info("收到中断，正在退出…")
        return 0
    finally:
        console.close()


if __name__ == "__main__":
    sys.exit(main())
