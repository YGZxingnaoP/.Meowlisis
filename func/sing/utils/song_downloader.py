# utils/song_downloader.py
import os
import glob
import difflib
import requests
import shutil
from ..sing_config import SERVER_URL, SONG_CACHE_DIR

class SongDownloader:
    def __init__(self, log):
        self.log = log

    def find_local_song(self, songname):
        exact_path = os.path.join(SONG_CACHE_DIR, f"{songname}.mp3")
        if os.path.isfile(exact_path):
            return exact_path
        mp3_files = glob.glob(os.path.join(SONG_CACHE_DIR, "*.mp3"))
        if not mp3_files:
            return None
        names = [os.path.splitext(os.path.basename(f))[0] for f in mp3_files]
        matches = difflib.get_close_matches(songname, names, n=1, cutoff=0.6)
        if matches:
            best = matches[0]
            idx = names.index(best)
            return mp3_files[idx]
        return None

    def download_song(self, songname, username):
        try:
            resp = requests.post(f"{SERVER_URL}/api/sing", json={
                "songname": songname,
                "username": username
            }, timeout=30)
            data = resp.json()
            if data.get('code') == 200:
                song_id = data['song_id']
                real_name = data['songname']
                local_path = data['local_path']
                if not local_path.startswith(SONG_CACHE_DIR):
                    target_path = os.path.join(SONG_CACHE_DIR, f"{real_name}.mp3")
                    shutil.copy2(local_path, target_path)
                    local_path = target_path
                return local_path, real_name, song_id
            else:
                self.log.warning(f"服务端返回错误: {data.get('msg')}")
                return None, None, None
        except Exception as e:
            self.log.exception(f"下载歌曲失败: {e}")
            return None, None, None

    def download_lyric(self, song_id, songname, lyric_handler):
        try:
            resp = requests.get(f"{SERVER_URL}/api/lyric", params={"song_id": song_id}, timeout=10)
            data = resp.json()
            if data.get('code') == 200:
                lrc = data.get('lrc', '')
                if lrc:
                    lrc_path = os.path.join(SONG_CACHE_DIR, f"{songname}.lrc")
                    with open(lrc_path, 'w', encoding='utf-8') as f:
                        f.write(lrc)
                    self.log.info(f"歌词已保存: {lrc_path}")
                    lyric_handler.rebuild_index()
        except Exception as e:
            self.log.warning(f"下载歌词失败: {e}")