import os
import signal
import ctypes
import ctypes.wintypes as wt

# 终止所有 electron.exe
psapi = ctypes.WinDLL('psapi')
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
arr = (wt.DWORD * 4096)()
needed = wt.DWORD(0)
psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed))
count = needed.value // ctypes.sizeof(wt.DWORD)
killed = 0
for i in range(count):
    pid = arr[i]
    if pid == 0:
        continue
    h = kernel32.OpenProcess(0x0410, False, pid)
    if not h:
        continue
    try:
        name = (ctypes.c_char * 260)()
        psapi.GetModuleBaseNameA(h, None, name, 260)
        if name.value.decode('gbk', 'ignore').lower() == 'electron.exe':
            try:
                os.kill(pid, signal.SIGTERM)
                killed += 1
            except Exception:
                pass
    finally:
        kernel32.CloseHandle(h)

# 删除临时文件
for f in [r'D:\.Meowlisis\.desktopet\.run.py', r'D:\.Meowlisis\.desktopet\.run.log',
          r'D:\.Meowlisis\.desktopet\npm.log', r'D:\.Meowlisis\clean.py']:
    try:
        if os.path.exists(f):
            os.remove(f)
    except Exception:
        pass
print('killed electron:', killed, '| temp cleaned')
