import datetime
import difflib
import json
import os
import re

from cw.protocol import CWErrorCode, CWProtocolError

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
ENTRY_DEFAULT = "main.py"


class CWActionStore:
    def __init__(self, config, reviewer):
        self.config = config
        self.reviewer = reviewer
        config.ensure_dirs()

    def _dir(self, action_id):
        return os.path.join(self.config.actions_dir, action_id)

    def _manifest_path(self, action_id):
        return os.path.join(self._dir(action_id), "manifest.json")

    def dir(self, action_id):
        return self._dir(action_id)

    def exists(self, action_id):
        return bool(action_id) and os.path.isfile(self._manifest_path(action_id))

    def _require_writable(self):
        if not getattr(self.config, "actions_writable", True):
            raise CWProtocolError(CWErrorCode.UNAVAILABLE,
                                  "actions 目录不可写，无法新建或修改 action：%s"
                                  % self.config.actions_dir)

    def list(self):
        if not os.path.isdir(self.config.actions_dir):
            return []
        items = []
        for name in sorted(os.listdir(self.config.actions_dir)):
            if name.startswith(".") or not ID_PATTERN.match(name):
                continue
            manifest = self._load(name)
            if manifest is None:
                continue
            manifest["files"] = self._file_names(name)
            manifest["locked"] = self._locked(manifest)
            items.append(manifest)
        return items

    def get(self, action_id):
        manifest = self._load(action_id)
        if manifest is None:
            raise CWProtocolError(CWErrorCode.NOT_FOUND, "action 不存在：%s" % action_id)
        manifest["files"] = self._file_names(action_id)
        manifest["locked"] = self._locked(manifest)
        return manifest

    def get_manifest(self, action_id):
        return self.get(action_id)

    def read_files(self, action_id):
        files = {}
        for name in self._file_names(action_id):
            if not name.endswith(".py"):
                continue
            try:
                with open(os.path.join(self._dir(action_id), name), "r", encoding="utf-8") as handle:
                    files[name] = handle.read()
            except OSError:
                files[name] = ""
        return files

    def _file_names(self, action_id):
        directory = self._dir(action_id)
        if not os.path.isdir(directory):
            return []
        return sorted(name for name in os.listdir(directory)
                      if os.path.isfile(os.path.join(directory, name)))

    def _load(self, action_id):
        path = self._manifest_path(action_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except Exception:
            return None
        if not isinstance(manifest, dict):
            return None
        manifest.setdefault("id", action_id)
        manifest.setdefault("status", "unverified")
        manifest.setdefault("updatable", False)
        manifest.setdefault("version", 1)
        manifest.setdefault("entry", ENTRY_DEFAULT + ":run")
        manifest.setdefault("steps", [])
        manifest.setdefault("params", {})
        manifest.setdefault("last_run", {"ok": False, "at": "", "elapsed_ms": 0})
        return manifest

    def _locked(self, manifest):
        return manifest.get("status") == "verified" and not manifest.get("updatable", False)

    def _now(self):
        return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    def _save(self, manifest):
        path = self._manifest_path(manifest["id"])
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)

    def can_update(self, action_id):
        manifest = self.get(action_id)
        if self._locked(manifest):
            return False, "该 action 已验证且未标记可更新，禁止修改"
        return True, ""

    def create(self, payload, phase):
        if phase != "reflecting":
            raise CWProtocolError(CWErrorCode.GUARD, "只有反思阶段可以新建 action")
        self._require_writable()
        action_id = str(payload.get("id") or "").strip()
        if not ID_PATTERN.match(action_id):
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "id 必须是 snake_case 且 2..41 字符")
        if self.exists(action_id):
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "action 已存在：%s" % action_id)
        title = str(payload.get("title") or "").strip()
        scene = str(payload.get("scene") or "").strip()
        code = str(payload.get("code") or "")
        if not title or not scene:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "title 与 scene 必填")
        if not code.strip():
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "code 不能为空")
        errors = self.reviewer.review({ENTRY_DEFAULT: code})
        if errors:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "审查未通过：" + "；".join(errors))
        os.makedirs(self._dir(action_id), exist_ok=True)
        target = os.path.join(self._dir(action_id), ENTRY_DEFAULT)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(code)
        manifest = {
            "id": action_id,
            "title": title,
            "scene": scene,
            "status": "unverified",
            "updatable": bool(payload.get("updatable", False)),
            "author": str(payload.get("author") or "ai"),
            "version": 1,
            "entry": ENTRY_DEFAULT + ":run",
            "params": payload.get("params") or {},
            "steps": payload.get("steps") or [],
            "requires": payload.get("requires") or [],
            "last_run": {"ok": False, "at": "", "elapsed_ms": 0},
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        self._save(manifest)
        return self.get(action_id)

    def update(self, action_id, code, reason, phase, target=ENTRY_DEFAULT):
        manifest = self.get(action_id)
        if phase not in ("running", "reflecting"):
            raise CWProtocolError(CWErrorCode.GUARD, "链路未激活，禁止修改 action")
        self._require_writable()
        if self._locked(manifest):
            raise CWProtocolError(CWErrorCode.LOCKED_ACTION,
                                  "该 action 已验证且未标记可更新，禁止修改")
        if target not in self._file_names(action_id):
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "只能修改已存在的文件：%s" % target)
        if not target.endswith(".py"):
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "只能修改 .py 文件")
        errors = self.reviewer.review({target: code})
        if errors:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "审查未通过：" + "；".join(errors))
        current = self.read_files(action_id).get(target, "")
        changed = count_changed_lines(current, code)
        if changed > self.config.action_max_change_lines:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST,
                                  "改动过大（%d 行，上限 %d 行），请新建 action"
                                  % (changed, self.config.action_max_change_lines))
        with open(os.path.join(self._dir(action_id), target), "w", encoding="utf-8") as handle:
            handle.write(code)
        manifest["status"] = "unverified"
        manifest["version"] = int(manifest.get("version", 1)) + 1
        manifest["updated_at"] = self._now()
        manifest["update_reason"] = str(reason or "")
        self._save(manifest)
        return self.get(action_id)

    def mark_run(self, action_id, ok, elapsed_ms, message=""):
        try:
            manifest = self.get(action_id)
        except CWProtocolError:
            return None
        manifest["last_run"] = {"ok": bool(ok), "at": self._now(),
                                "elapsed_ms": int(elapsed_ms), "message": message}
        if ok:
            manifest["status"] = "verified"
        manifest["updated_at"] = self._now()
        self._save(manifest)
        return manifest

    def set_verified(self, action_id, verified):
        manifest = self.get(action_id)
        manifest["status"] = "verified" if verified else "unverified"
        manifest["updated_at"] = self._now()
        self._save(manifest)
        return self.get(action_id)

    def set_updatable(self, action_id, updatable):
        manifest = self.get(action_id)
        manifest["updatable"] = bool(updatable)
        manifest["updated_at"] = self._now()
        self._save(manifest)
        return self.get(action_id)


def phase_is_running(phase):
    return phase == "running"


def count_changed_lines(before, after):
    left = str(before or "").splitlines()
    right = str(after or "").splitlines()
    matcher = difflib.SequenceMatcher(None, left, right)
    total = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        total += max(i2 - i1, j2 - j1)
    return total
