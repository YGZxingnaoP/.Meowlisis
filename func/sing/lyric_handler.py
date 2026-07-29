# -*- coding: utf-8 -*-
import os
import re
import glob
from collections import defaultdict
from threading import Lock

class LyricHandler:
    def __init__(self, song_cache_dir, log):
        self.song_cache_dir = song_cache_dir
        self.log = log
        self._lyric_index = None
        self._lyric_sentences = []
        self._index_lock = Lock()
        self._rebuild_lyric_index()

    def _rebuild_lyric_index(self):
        with self._index_lock:
            self._lyric_sentences = []
            word_to_idx = defaultdict(set)
            lrc_files = glob.glob(os.path.join(self.song_cache_dir, "*.lrc"))
            for lrc_path in lrc_files:
                song_name = os.path.splitext(os.path.basename(lrc_path))[0]
                sentences = self._parse_lrc_sentences(lrc_path)
                for timestamp, text in sentences:
                    idx = len(self._lyric_sentences)
                    self._lyric_sentences.append((song_name, timestamp, text))
                    words = re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]+', text)
                    for w in words:
                        if len(w) >= 2:
                            word_to_idx[w].add(idx)
            self._lyric_index = {w: list(idx_set) for w, idx_set in word_to_idx.items()}
            self.log.info(f"歌词索引构建完成，共 {len(self._lyric_sentences)} 句，{len(self._lyric_index)} 个词")

    def _parse_lrc_sentences(self, lrc_path):
        sentences = []
        try:
            with open(lrc_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    pattern = r'\[(\d{2}):(\d{2})(?:\.(\d{2}))?\]'
                    matches = re.findall(pattern, line)
                    if matches:
                        for m in matches:
                            minutes = int(m[0])
                            seconds = int(m[1])
                            centi = int(m[2]) if m[2] else 0
                            total_sec = minutes * 60 + seconds + centi / 100.0
                            lyric_text = re.sub(pattern, '', line).strip()
                            if lyric_text:
                                sentences.append((total_sec, lyric_text))
                                break
        except Exception as e:
            self.log.warning(f"解析歌词文件失败 {lrc_path}: {e}")
        return sentences

    def get_all_sentences(self, song_name):
        lrc_path = os.path.join(self.song_cache_dir, f"{song_name}.lrc")
        if not os.path.exists(lrc_path):
            return []
        return self._parse_lrc_sentences(lrc_path)

    def match_lyric(self, user_text, threshold):
        if not self._lyric_index or not self._lyric_sentences:
            return None
        words = set(re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]+', user_text))
        candidate_indices = set()
        for w in words:
            if w in self._lyric_index:
                candidate_indices.update(self._lyric_index[w])
        if not candidate_indices:
            return None
        from rapidfuzz import fuzz
        best_sim = 0
        best = None
        for idx in candidate_indices:
            _, _, lyric_text = self._lyric_sentences[idx]
            sim = fuzz.partial_ratio(user_text, lyric_text)
            if sim > best_sim:
                best_sim = sim
                best = idx
        if best_sim >= threshold:
            song_name, timestamp, text = self._lyric_sentences[best]
            return (song_name, timestamp, text, best_sim)
        return None

    def rebuild_index(self):
        self._rebuild_lyric_index()