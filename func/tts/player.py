# 播放器
import subprocess
import os
import time
from func.tools.singleton_mode import singleton

@singleton
class MpvPlay:
    def __init__(self):
        self.current_process = None

    # 播放器播放（非阻塞）
    def mpv_play(self, mpv_name, song_path, volume, start):
        """启动播放，不再自动停止之前的播放"""
        try:
            # 使用Popen非阻塞播放
            self.current_process = subprocess.Popen(
                f'{mpv_name} -vo null --volume={volume} --start={start} "{song_path}"',
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
        except Exception as e:
            print(f"播放启动失败: {e}")
            self.current_process = None

    # 立即停止播放
    def stop(self):
        """停止当前播放的进程"""
        if self.current_process:
            try:
                # 检查进程是否还在运行
                if self.current_process.poll() is None:
                    # Windows强制终止
                    if os.name == 'nt':
                        subprocess.run(
                            f"taskkill /F /PID {self.current_process.pid} /T",
                            shell=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        # 等待进程完全退出
                        try:
                            self.current_process.wait(timeout=0.5)
                        except:
                            pass
                    else:
                        # Linux/Mac
                        self.current_process.terminate()
                        time.sleep(0.1)
                        if self.current_process.poll() is None:
                            self.current_process.kill()
            except Exception as e:
                print(f"停止播放失败: {e}")
            finally:
                self.current_process = None
    
    def is_playing(self):
        """检查当前是否有播放进程在运行"""
        if self.current_process:
            return self.current_process.poll() is None
        return False