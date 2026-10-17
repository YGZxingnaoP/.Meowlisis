# -*- coding: utf-8 -*-
"""FastAPI 应用装配与进程入口。

启动流程
--------
1. 控制台切 UTF-8（Windows GBK 控制台下中文日志不再乱码）
2. 读 config.yml（根键 meowllm:）
3. 校验（host 必须回环、引擎必须在白名单、max_tokens < n_ctx ……）
4. 引擎工厂三道闸门 -> 创建并**预加载**引擎（>1B 会在这里被拒，不会进 uvicorn）
5. 端口探测 18100..18108，写 state/meowllm/port.json
6. uvicorn 提供服务
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import socket
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from meowllm import MEOWLLM_SERVICE_NAME, MeowLLM_VERSION
from meowllm.config import MeowLLMConfig
from meowllm.errors import MeowLLMConfigError, MeowLLMError
from meowllm.server.routes_control import router as control_router
from meowllm.server.routes_v1 import router as v1_router
from meowllm.server.state import MeowLLMServiceState

log = logging.getLogger("meowllm.app")

_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def setup_console() -> None:
    """Windows 控制台默认 GBK，中文会变乱码；能改就改成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def setup_logging(level: str = "INFO", log_dir: str | None = None) -> None:
    root = logging.getLogger("meowllm")
    if getattr(root, "_meowllm_configured", False):
        return
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    formatter = logging.Formatter(_LOG_FORMAT)

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, "meowllm.log")
            file_handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=8 * 1024 * 1024, backupCount=5, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except Exception:  # noqa: BLE001
            root.warning("日志文件不可写，仅输出到 stderr：%s", log_dir)

    root._meowllm_configured = True  # noqa: SLF001


def create_app(cfg: MeowLLMConfig, engine=None) -> FastAPI:
    from meowllm.engine import create as create_engine

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = getattr(app.state, "meowllm", None)
        if state is None:
            eng = engine if engine is not None else create_engine(cfg)
            if not eng.loaded:
                eng.load()
            state = MeowLLMServiceState(cfg, eng)
            app.state.meowllm = state
        eng = state.engine
        log.info("%s %s 就绪：engine=%s model=%s",
                 MEOWLLM_SERVICE_NAME, MeowLLM_VERSION, eng.kind,
                 cfg.get("model.name"))
        try:
            yield
        finally:
            log.info("正在关闭引擎……")
            try:
                eng.unload()
            except Exception:  # noqa: BLE001
                log.exception("关闭引擎异常")

    app = FastAPI(
        title="MeowLLM",
        version=MeowLLM_VERSION,
        description="本地模型加载与认知编排服务；对外仅 /meowllm/* 前缀",
        lifespan=lifespan,
        docs_url="/meowllm/docs",
        redoc_url=None,
        openapi_url="/meowllm/openapi.json",
    )

    @app.exception_handler(MeowLLMError)
    async def _handle_meowllm_error(request: Request, exc: MeowLLMError):
        return JSONResponse(status_code=exc.http_status,
                            content={"meowllm": {"error": exc.to_dict()}})

    app.include_router(v1_router)
    app.include_router(control_router)

    @app.get("/")
    async def _root():
        return {"service": MEOWLLM_SERVICE_NAME, "version": MeowLLM_VERSION,
                "v1": "/meowllm/v1", "control": "/meowllm/control"}

    # 预加载的引擎：在进 uvicorn 之前就把 state 挂好，健康检查立刻可用
    if engine is not None and engine.loaded:
        app.state.meowllm = MeowLLMServiceState(cfg, engine)

    return app


# ---------------------------------------------------------------- 端口
def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            return sock.connect_ex((host, port)) != 0
        except OSError:
            return False


def pick_port(host: str, base: int, fallback: int) -> tuple[int, list[int]]:
    tried: list[int] = []
    for offset in range(max(0, fallback) + 1):
        candidate = base + offset
        if candidate > 65535:
            break
        if _port_free(host, candidate):
            return candidate, tried
        tried.append(candidate)
    raise MeowLLMConfigError(
        f"{host} 上 {base}..{base + fallback} 全部被占用", detail={"tried": tried})


def write_port_file(cfg: MeowLLMConfig, host: str, port: int) -> str | None:
    try:
        os.makedirs(cfg.state_dir, exist_ok=True)
        path = os.path.join(cfg.state_dir, "port.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"host": host, "port": port,
                       "base_url": f"http://{host}:{port}/meowllm/v1",
                       "pid": os.getpid(),
                       "started_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      fh, ensure_ascii=False, indent=2)
        # 单独一份 pid 供 .test\bin\stop.bat 用（纯数字，方便 set /p 读取）
        try:
            with open(os.path.join(cfg.state_dir, "meowllm.pid"), "w",
                      encoding="ascii") as fh:
                fh.write(str(os.getpid()))
        except OSError:
            pass
        return path
    except Exception:  # noqa: BLE001
        log.warning("无法写入 port.json（state_dir 不可写）：%s", cfg.state_dir)
        return None


def _print_error(title: str, exc: MeowLLMError) -> None:
    payload = exc.to_dict()
    print(f"\n[MeowLLM] {title}", file=sys.stderr)
    print(f"  code   : {payload.get('code')}", file=sys.stderr)
    print(f"  message: {payload.get('message')}", file=sys.stderr)
    detail = payload.get("detail")
    if detail:
        print(f"  detail : {json.dumps(detail, ensure_ascii=False)}", file=sys.stderr)


# ---------------------------------------------------------------- 入口
def main(argv: list[str] | None = None) -> int:
    setup_console()

    parser = argparse.ArgumentParser(prog="meowllm", description="MeowLLM 服务")
    parser.add_argument("--config", default=None, help="config.yml 路径")
    parser.add_argument("--engine", default=None, help="临时覆盖 engine.kind")
    parser.add_argument("--port", type=int, default=None, help="临时覆盖 server.port")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--check", action="store_true",
                        help="只做配置校验与闸门自检，不启动服务")
    args = parser.parse_args(argv)

    if args.engine:
        os.environ["MEOWLLM__ENGINE__KIND"] = args.engine
    if args.port:
        os.environ["MEOWLLM__SERVER__PORT"] = str(args.port)

    try:
        cfg = MeowLLMConfig.load(args.config)
    except MeowLLMError as exc:
        _print_error("配置错误", exc)
        return 2

    setup_logging(args.log_level, cfg.log_dir)

    from meowllm.engine import create as create_engine

    # 闸门与加载都在进 uvicorn 之前做完：失败直接给可读信息，不甩 traceback
    try:
        engine = create_engine(cfg)
    except MeowLLMError as exc:
        _print_error("闸门拦截", exc)
        return 3

    if args.check:
        print(json.dumps({
            "config_ok": True,
            "config_source": cfg.source,
            "engine": cfg.get("engine.kind"),
            "safety": cfg.get("safety"),
            "engine_info": _safe(engine.info),
        }, ensure_ascii=False, indent=2))
        return 0

    try:
        engine.load()
    except MeowLLMError as exc:
        _print_error("引擎加载失败", exc)
        if isinstance(exc.detail, dict) and exc.detail.get("tail"):
            print("\n--- llama-server 日志尾部 ---", file=sys.stderr)
            print(exc.detail["tail"], file=sys.stderr)
        return 5

    try:
        host = str(cfg.get("server.host", "127.0.0.1"))
        base = int(cfg.get("server.port", 18100))
        fallback = int(cfg.get("server.port_fallback", 9))
        port, tried = pick_port(host, base, fallback)
        if tried:
            log.warning("端口 %s 被占用，改用 %s（已试 %s）", base, port, tried)
        write_port_file(cfg, host, port)
    except MeowLLMError as exc:
        _print_error("端口不可用", exc)
        engine.unload()
        return 4

    app = create_app(cfg, engine=engine)
    import uvicorn

    print(f"[MeowLLM] {MEOWLLM_SERVICE_NAME} {MeowLLM_VERSION} listening on "
          f"http://{host}:{port}/meowllm/v1  (engine={cfg.get('engine.kind')})",
          flush=True)
    try:
        uvicorn.run(app, host=host, port=port, log_level=args.log_level.lower(),
                    access_log=False)
    finally:
        try:
            engine.unload()
        except Exception:  # noqa: BLE001
            pass
    return 0


def _safe(fn) -> dict:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


if __name__ == "__main__":
    raise SystemExit(main())
