# -*- coding: utf-8 -*-
import os
import requests

class RVCHandler:
    def __init__(self, enabled, api_url, voice_id, song_cache_dir, log):
        self.enabled = enabled
        self.api_url = api_url
        self.voice_id = voice_id
        self.song_cache_dir = song_cache_dir
        self.log = log

    def generate_cover(self, original_mp3, song_name):
        if not self.enabled:
            return None
        cover_name = f"[喵呜翻唱]{song_name}.mp3"
        cover_path = os.path.join(self.song_cache_dir, cover_name)
        if os.path.exists(cover_path):
            return cover_path
        try:
            with open(original_mp3, 'rb') as f:
                files = {'audio': f}
                data = {'voice_id': self.voice_id}
                resp = requests.post(f"{self.api_url}/infer", files=files, data=data, timeout=60)
            if resp.status_code == 200:
                with open(cover_path, 'wb') as f:
                    f.write(resp.content)
                self.log.info(f"RVC 翻唱生成成功: {cover_path}")
                return cover_path
            else:
                self.log.warning(f"RVC 生成失败: {resp.text}")
        except requests.exceptions.ConnectionError:
            self.log.warning(f"RVC 服务未启动，跳过翻唱生成: {self.api_url}")
        except Exception as e:
            self.log.warning(f"RVC 调用异常: {e}")
        return None

    def get_cover_path(self, song_name):
        cover_path = os.path.join(self.song_cache_dir, f"[喵呜翻唱]{song_name}.mp3")
        return cover_path if os.path.exists(cover_path) else None