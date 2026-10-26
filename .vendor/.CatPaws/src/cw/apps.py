import os
import subprocess

CW_SYSTEM_APPS = {
    "Safari": "com.apple.mobilesafari",
    "相机": "com.apple.camera",
    "照片": "com.apple.mobileslideshow",
    "日历": "com.apple.mobilecal",
    "备忘录": "com.apple.mobilenotes",
    "时钟": "com.apple.mobiletimer",
    "提醒事项": "com.apple.reminders",
    "地图": "com.apple.Maps",
    "邮件": "com.apple.mobilemail",
    "文件": "com.apple.DocumentsApp",
    "天气": "com.apple.weather",
    "计算器": "com.apple.calculator",
    "音乐": "com.apple.Music",
    "信息": "com.apple.MobileSMS",
    "电话": "com.apple.mobilephone",
    "设置": "com.apple.Preferences",
}


class CWApps:
    def __init__(self, config):
        self.config = config
        self._map = {}

    def load(self):
        apps = dict(CW_SYSTEM_APPS)
        apps.update(dict(self.config.apps or {}))
        for name, bundle in self._from_device().items():
            apps[name] = bundle
        self._map = apps
        return dict(self._map)

    def _from_device(self):
        exe = os.path.join(self.config.catpaws_dir, "catpaws-launcher", "ios.exe")
        if not os.path.isfile(exe):
            return {}
        try:
            done = subprocess.run([exe, "apps", "--list"], capture_output=True, timeout=20,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            return {}
        text = ""
        for stream in (done.stdout, done.stderr):
            try:
                text += stream.decode("utf-8", "replace")
            except Exception:
                continue
        found = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            bundle = parts[0]
            if not bundle or "." not in bundle:
                continue
            name = " ".join(parts[1:-1]) if len(parts) > 2 else parts[1]
            name = name.strip()
            if name:
                found[name] = bundle
        return found

    def prompt_block(self, limit=60):
        if not self._map:
            return ""
        items = sorted(self._map.items(),
                       key=lambda item: (item[1].startswith("com.apple."), item[0].lower()))
        text = "；".join("%s=%s" % (name, bundle) for name, bundle in items[:limit])
        return "可启动的应用（名字=bundle_id）：%s" % text

    def resolve(self, value):
        body = str(value or "").strip()
        if not body:
            return ""
        if body in self._map:
            return self._map[body]
        low = body.lower()
        for name, bundle in self._map.items():
            if name.lower() == low or bundle.lower() == low:
                return bundle
        for name, bundle in self._map.items():
            if low in name.lower():
                return bundle
        return body
