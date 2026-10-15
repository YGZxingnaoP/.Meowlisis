import datetime
import glob
import json
import os
import shutil

from func.catbrain.UserMemory.identity.store import IdentityStore
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

PROFILE_DIR = os.path.join("character", "info", "users_info")
BACKLOG_DIR = os.path.join("character", "backlog")
MEMORY_DIR = os.path.join("character", "memory")
RECORD_DIR = ".temp"


@singleton
class UserMerge:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.store = IdentityStore()

    @staticmethod
    def safe_name(name):
        """把用户名清洗成能当文件名的形式"""
        text = str(name or "").strip()
        for ch in '\\/:*?"<>|\r\n\t':
            text = text.replace(ch, "_")
        return text.strip()

    def user_dir(self, uid):
        """取编号对应的档案目录"""
        return os.path.join("character", "userinfo", str(uid))

    def profile_path(self, key):
        """取档案路径：编号走新目录，名字走老目录"""
        key = str(key or "").strip()
        if len(key) == 6 and key.isdigit():
            return os.path.join(self.user_dir(key), "profile.json")
        return os.path.join(PROFILE_DIR, f"{self.safe_name(key)}_latest.json")

    def backup_files(self, key):
        """列出某个名字的历史备份档案"""
        pattern = os.path.join(PROFILE_DIR, f"{self.safe_name(key)}-*.json")
        return sorted(glob.glob(pattern))

    def record_path(self, key):
        """取某个名字的短期记录路径"""
        return os.path.join(RECORD_DIR, f"{self.safe_name(key)}_record.txt")

    def backlog_path(self, key):
        """取某个名字的待办路径"""
        return os.path.join(BACKLOG_DIR, f"{self.safe_name(key)}.json")

    def read_json(self, path):
        """读 json，失败回空 dict"""
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception(f"读取失败: {path}")
        return {}

    def read_profile(self, key):
        """读档案"""
        return self.read_json(self.profile_path(key))

    def affinity(self, key):
        """读好感度，读不到算 0"""
        value = self.read_profile(key).get("affinity", 0)
        try:
            return int(value)
        except Exception:
            return 0

    def bili_bound(self, key):
        """判断这个用户名或编号名下有没有 B站账号"""
        key = str(key or "").strip()
        if not key:
            return False
        if len(key) == 6 and key.isdigit():
            user = self.store.get_user(key)
            return bool((user.get("accounts") or {}).get("bili"))
        for user in self.store.list_users():
            if str(user.get("nickname") or "").strip() == key:
                return bool((user.get("accounts") or {}).get("bili"))
        return False

    def profile_files(self, key):
        """列出这个用户名下所有档案文件"""
        files = []
        latest = self.profile_path(key)
        if os.path.exists(latest):
            files.append(latest)
        files.extend(self.backup_files(key))
        return files

    def pick_base(self, keys):
        """定当底的：好感度高的优先，一样时优先有 B站账号的那份"""
        scored = []
        for key in keys:
            scored.append((self.affinity(key), 1 if self.bili_bound(key) else 0, str(key)))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return scored[0][2]

    def field_conflicts(self, base, other):
        """列出两边都有值又不一样的字段，unknown 不算冲突"""
        conflicts = []
        for field, value in (other or {}).items():
            if field == "name":
                continue
            old = (base or {}).get(field)
            if old in (None, "", "unknown") or value in (None, "", "unknown"):
                continue
            if old != value:
                conflicts.append((field, old, value))
        return conflicts


    def merge_fields(self, base, other):
        """当底字段保留，另一份只补空缺"""
        merged = dict(base or {})
        for field, value in (other or {}).items():
            old = merged.get(field)
            if old in (None, "", "unknown") and value not in (None, "", "unknown"):
                merged[field] = value
        return merged

    def plan(self, keys):
        """打出合并方案，含双方编号、昵称、账号、好感度、档案清单、冲突字段"""
        keys = [str(k).strip() for k in (keys or []) if str(k).strip()]
        if len(keys) < 2:
            return ["至少给两个用户名或编号"]
        base = self.pick_base(keys)
        lines = [f"当底：{base}（好感度 {self.affinity(base)}，B站账号 {'有' if self.bili_bound(base) else '无'}）"]
        for key in keys:
            profile = self.read_profile(key)
            uid = ""
            if len(key) == 6 and key.isdigit():
                uid = key
            else:
                for user in self.store.list_users():
                    if str(user.get("nickname") or "").strip() == key:
                        uid = str(user.get("id") or "")
                        break
            accounts = self.store.get_user(uid).get("accounts") if uid else {}
            lines.append(
                f"· {key}：编号 {uid or '未绑定'}，昵称 {profile.get('name') or key}，"
                f"好感度 {self.affinity(key)}，账号 {accounts or '无'}，"
                f"档案 {len(self.profile_files(key))} 个"
            )
            for path in self.profile_files(key):
                lines.append(f"    - {path}")
        for key in keys:
            if key == base:
                continue
            for field, old, new in self.field_conflicts(self.read_profile(base), self.read_profile(key)):
                lines.append(f"冲突：{field} 当底={old} / {key}={new}（不自动覆盖）")
        return lines

    def backup(self, uid, paths):
        """把要动的文件先复制一份到编号目录下的 _backup"""
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target = os.path.join(self.user_dir(uid), "_backup", stamp)
        os.makedirs(target, exist_ok=True)
        for path in paths:
            if not path or not os.path.exists(path):
                continue
            try:
                shutil.copy2(path, os.path.join(target, os.path.basename(path)))
            except Exception:
                self.log.exception(f"备份失败: {path}")
        return target

    def move_profile(self, key, uid):
        """把档案与历史备份搬进编号目录"""
        target_dir = self.user_dir(uid)
        os.makedirs(target_dir, exist_ok=True)
        moved = []
        latest = self.profile_path(key)
        if os.path.exists(latest):
            dest = os.path.join(target_dir, "profile.json")
            shutil.move(latest, dest)
            moved.append(dest)
        for path in self.backup_files(key):
            dest = os.path.join(target_dir, os.path.basename(path).replace(f"{self.safe_name(key)}-", "profile-"))
            shutil.move(path, dest)
            moved.append(dest)
        return moved

    def move_backlog(self, key, uid):
        """把待办搬进编号目录"""
        src = self.backlog_path(key)
        if not os.path.exists(src):
            return []
        target_dir = self.user_dir(uid)
        os.makedirs(target_dir, exist_ok=True)
        dest = os.path.join(target_dir, "backlog.json")
        shutil.move(src, dest)
        return [dest]

    def move_record(self, key, uid):
        """把短期记录改成按编号命名，已有就追加"""
        src = self.record_path(key)
        if not os.path.exists(src):
            return []
        dest = self.record_path(uid)
        with open(src, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        with open(dest, "a", encoding="utf-8") as f:
            f.write(text)
        os.remove(src)
        return [dest]

    def rewrite_memory_tags(self, old_name, new_name):
        """把长期记忆里的 [旧名] 标签换成新名"""
        old_tag = f"[{old_name}]"
        new_tag = f"[{new_name}]"
        changed = []
        for path in glob.glob(os.path.join(MEMORY_DIR, "*.txt")):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                if old_tag not in text:
                    continue
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text.replace(old_tag, new_tag))
                changed.append(path)
            except Exception:
                self.log.exception(f"改写记忆标签失败: {path}")
        return changed

    def migrate(self, key):
        """把一个老档案名字整体搬进编号目录，返回 (成功, 提示)"""
        key = str(key or "").strip()
        if not key:
            return False, "参数缺失：请给用户名"
        from func.pipeline.id_signup import IdSignupBridge
        uid = IdSignupBridge().new_user(key)
        if not uid:
            return False, "开编号失败，身份表正忙"
        name = self.safe_name(key)
        target_dir = self.user_dir(uid)
        os.makedirs(target_dir, exist_ok=True)
        sources = []
        latest = os.path.join(PROFILE_DIR, f"{name}_latest.json")
        if os.path.exists(latest):
            sources.append(latest)
        sources.extend(self.backup_files(key))
        for extra in glob.glob(os.path.join(PROFILE_DIR, f"{name}2*")):
            sources.append(extra)
        record = self.record_path(key)
        if os.path.exists(record):
            sources.append(record)
        backlog = self.backlog_path(key)
        if os.path.exists(backlog):
            sources.append(backlog)
        if not sources:
            return False, f"{key} 没有可搬的文件"
        backup_dir = self.backup(uid, sources)
        moved = []
        for path in sources:
            base = os.path.basename(path)
            if base == f"{name}_latest.json":
                dest = os.path.join(target_dir, "profile.json")
            elif base.endswith("_record.txt"):
                dest = self.record_path(uid)
                self._append_text(path, dest)
                os.remove(path)
                moved.append(dest)
                continue
            elif path == backlog:
                dest = os.path.join(target_dir, "backlog.json")
            else:
                dest = os.path.join(target_dir, base.replace(name, "profile", 1))
            shutil.move(path, dest)
            moved.append(dest)
        return True, f"{key} 已搬到编号 {uid}，共 {len(moved)} 个文件，备份在 {backup_dir}"

    @staticmethod
    def _append_text(src, dest):
        """把源文本追加到目标文件"""
        with open(src, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        with open(dest, "a", encoding="utf-8") as f:
            f.write(text)

    def apply(self, keys, keep="", dry_run=True):
        """执行合并：先备份再搬文件，dry_run 只打印不动手"""
        keys = [str(k).strip() for k in (keys or []) if str(k).strip()]
        if len(keys) < 2:
            return False, "至少给两个用户名或编号"
        base = str(keep).strip() or self.pick_base(keys)
        uid = base if (len(base) == 6 and base.isdigit()) else ""
        if not uid:
            from func.pipeline.id_signup import IdSignupBridge
            uid = IdSignupBridge().new_user(base)
        if not uid:
            return False, "拿不到编号，请先在身份表里绑定"
        user = self.store.get_user(uid)
        new_name = str(user.get("nickname") or "").strip() or base
        touched = []
        for key in keys:
            touched.extend(self.profile_files(key))
            touched.append(self.backlog_path(key))
            touched.append(self.record_path(key))
        if dry_run:
            lines = self.plan(keys)
            lines.append(f"执行后：编号 {uid}，昵称 {new_name}")
            lines.append("要动的文件：" + "、".join([p for p in touched if os.path.exists(p)]))
            return True, "\n".join(lines)
        backup_dir = self.backup(uid, [p for p in touched if os.path.exists(p)])
        merged = {}
        for key in keys:
            merged = self.merge_fields(merged, self.read_profile(key)) if key != base else self.merge_fields(self.read_profile(key), merged)
        for key in keys:
            self.move_profile(key, uid)
            self.move_backlog(key, uid)
            self.move_record(key, uid)
            if key != base:
                self.rewrite_memory_tags(key, new_name)
        target = os.path.join(self.user_dir(uid), "profile.json")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        for key in keys:
            if key == base:
                continue
            other = ""
            if not (len(key) == 6 and key.isdigit()):
                for item in self.store.list_users():
                    if str(item.get("nickname") or "").strip() == key:
                        other = str(item.get("id") or "")
                        break
            if other and other != uid:
                self.store.merge_users(uid, other)
        return True, f"已合并到编号 {uid}（昵称 {new_name}），备份在 {backup_dir}"
