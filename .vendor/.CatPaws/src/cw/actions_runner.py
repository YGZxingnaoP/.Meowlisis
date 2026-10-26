import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time

from cw.protocol import CWErrorCode, CWProtocolError


class CWActionRunner:
    def __init__(self, config, operator, journal, store):
        self.config = config
        self.operator = operator
        self.journal = journal
        self.store = store
        self.asker = None
        self._lock = threading.Lock()

    def run(self, action_id, params=None):
        manifest = self.store.get(action_id)
        entry = str(manifest.get("entry") or "main.py:run").split(":")[0] or "main.py"
        directory = self.store.dir(action_id)
        script = os.path.join(directory, entry)
        if not os.path.isfile(script):
            raise CWProtocolError(CWErrorCode.NOT_FOUND, "脚本不存在：%s" % entry)
        with self._lock:
            if self.operator.stopping():
                raise CWProtocolError(CWErrorCode.CANCELLED, "已停止")
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONPATH"] = os.pathsep.join([self.config.src_dir, directory,
                                                 env.get("PYTHONPATH", "")])
            env["CW_ACTION_ID"] = action_id
            env["CW_ACTION_PARAMS"] = json.dumps(params or {}, ensure_ascii=False)
            started = time.time()
            ok = False
            message = ""
            lines = queue.Queue()
            proc = None
            self._params = dict(params or {})
            self.journal.record("action_start", action_id=action_id,
                                title=manifest.get("title", ""), params=params or {})
            try:
                proc = subprocess.Popen([sys.executable, "-u", script], cwd=directory, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                        errors="replace", bufsize=1)
                threading.Thread(target=self._pump, args=(proc.stdout, lines), daemon=True).start()
                threading.Thread(target=self._pump_err, args=(proc.stderr, action_id),
                                 daemon=True).start()
                deadline = started + self.config.action_timeout_sec
                while True:
                    if self.operator.stopping():
                        raise CWProtocolError(CWErrorCode.CANCELLED, "已停止")
                    if time.time() > deadline:
                        raise CWProtocolError(CWErrorCode.TIMEOUT,
                                              "action 超过 %d 秒" % self.config.action_timeout_sec)
                    try:
                        line = lines.get(timeout=0.2)
                    except queue.Empty:
                        if proc.poll() is not None:
                            break
                        continue
                    if line is None:
                        break
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        self.journal.record("script_output", action_id=action_id,
                                            text=line.strip()[:400])
                        continue
                    finish = self._dispatch(proc, payload, action_id)
                    if finish is not None:
                        ok = bool(finish.get("ok", True))
                        message = str(finish.get("text") or "")
                        break
            finally:
                elapsed = int((time.time() - started) * 1000)
                self._close(proc)
                if not ok and not message:
                    message = getattr(self, "_last_stderr", "") or "脚本异常退出"
                self.store.mark_run(action_id, ok, elapsed, message)
                self.journal.record("action_finish", action_id=action_id, ok=ok,
                                    elapsed_ms=elapsed, message=message)
        return {"ok": ok, "action_id": action_id, "message": message,
                "elapsed_ms": elapsed}

    def _pump(self, stream, lines):
        try:
            for line in stream:
                lines.put(line)
        except Exception:
            pass
        finally:
            lines.put(None)

    def _pump_err(self, stream, action_id):
        try:
            for line in stream:
                text = str(line).strip()
                if text:
                    self._last_stderr = text[:300]
                    self.journal.record("script_stderr", action_id=action_id, text=text[:400])
        except Exception:
            pass

    def _close(self, proc):
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _reply(self, proc, payload):
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                proc.stdin.flush()
        except Exception:
            pass

    def _dispatch(self, proc, payload, action_id):
        op = payload.get("op")
        if op == "emit":
            try:
                if payload.get("steps") is not None:
                    result = self.operator.sequence(payload.get("steps") or [],
                                                    payload.get("delay_ms"))
                else:
                    result = self.operator.single(payload.get("step") or {})
                self._reply(proc, {"ok": True, "executed": result.get("executed", 1)})
            except CWProtocolError as exc:
                self._reply(proc, {"ok": False, "code": exc.code, "message": exc.message})
            return None
        if op == "observe":
            try:
                result = self.operator.observe(payload.get("mode") or "ocr", payload.get("region"))
                if result.get("mode") == "image":
                    self._reply(proc, {"ok": True, "mode": "image",
                                       "image_size": result.get("screen", {}).get("pixel", []),
                                       "png_b64": base64.b64encode(result["image"]).decode()})
                else:
                    self._reply(proc, {"ok": True, "mode": "ocr",
                                       "texts": result.get("texts", []),
                                       "image_size": result.get("image_size", [])})
            except CWProtocolError as exc:
                self._reply(proc, {"ok": False, "code": exc.code, "message": exc.message})
            return None
        if op == "ask":
            question = str(payload.get("question") or "")
            options = payload.get("options") or []
            answer = ""
            try:
                if self.asker is not None:
                    answer = self.asker(question, options)
            except Exception:
                answer = ""
            self._reply(proc, {"ok": True, "answer": answer})
            return None
        if op == "probe":
            self._reply(proc, {"ok": True, "stop": bool(self.operator.stopping())})
            return None
        if op == "params":
            self._reply(proc, {"ok": True, "params": getattr(self, "_params", {})})
            return None
        if op == "log":
            self.journal.record("script_log", action_id=action_id,
                                text=str(payload.get("text") or "")[:400])
            return None
        if op == "done":
            return payload
        return None
