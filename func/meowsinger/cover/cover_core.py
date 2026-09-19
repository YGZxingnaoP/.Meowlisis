# -*- coding: utf-8 -*-
# func/meowsinger/cover/cover_core.py
# 翻唱核心：调 RVC 服务分离三轨与变声，保存到 meow_list，混音播放
import os
import shutil

import numpy as np
import requests
import soundfile as sf

from func.log.default_log import DefaultLog
from func.meowsinger.config import MeowSingerConfig

MEOW_DIR = os.path.join("character", "songs", "meow_list")
RAW_DIR = os.path.join("character", "songs", "raw_list")


class MeowCoverCore:
    """翻唱核心：人声分离、RVC 变声、混音播放（音频处理全在模块内部）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowSingerConfig()
        self._last_source = ""
        self._last_remote_f0 = None

    def separate(self, input_path, output_dir):
        input_path = os.path.abspath(input_path)
        output_dir = os.path.abspath(output_dir)
        self._last_source = input_path
        self._last_remote_f0 = None

        data = self._post_separate(input_path, output_dir, quiet=True)
        if data is not None:
            return {
                "vocal": data.get("vocal_path"),
                "accomp": data.get("accomp_path"),
                "harmony": data.get("harmony_path"),
            }

        remote_in, work_dir = self._upload(input_path)
        if not remote_in:
            return None
        data = self._post_separate(remote_in, work_dir)
        if data is None:
            return None

        self._last_remote_f0 = data.get("f0_up_key")
        base = os.path.splitext(os.path.basename(input_path))[0]
        out = {"vocal": data.get("vocal_path") or ""}
        for key, suffix in (("accomp", "_accomp.wav"), ("harmony", "_harmony.wav")):
            remote_path = data.get(f"{key}_path") or ""
            local_path = os.path.join(output_dir, f"{base}{suffix}")
            out[key] = local_path if (remote_path and self._download(remote_path, local_path)) else ""
        return out

    def _post_separate(self, input_path, output_dir, quiet=False):
        try:
            resp = requests.post(
                f"{self.config.rvc_url}/api/separate",
                json={"input_path": input_path, "output_dir": output_dir},
                timeout=3600,
            )
            data = resp.json()
        except Exception:
            if not quiet:
                self.log.exception("[Cover] 调 RVC 分离异常")
            return None
        if not isinstance(data, dict) or data.get("code") != 200:
            if not quiet:
                msg = data.get("msg") if isinstance(data, dict) else f"HTTP {resp.status_code}"
                self.log.error(f"[Cover] 分离失败: {msg}")
            return None
        return data

    @staticmethod
    def _is_remote_path(path):
        p = str(path or "")
        return bool(p) and p.startswith("/") and not os.path.exists(p)

    def _upload(self, local_path):
        name = os.path.basename(local_path)
        try:
            with open(local_path, "rb") as f:
                resp = requests.post(
                    f"{self.config.rvc_url}/api/upload",
                    files={"file": (name, f, "application/octet-stream")},
                    timeout=1800,
                )
        except Exception:
            self.log.exception("[Cover] 上传音频异常")
            return "", ""
        if resp.status_code == 404:
            return "", ""
        if resp.status_code != 200:
            self.log.error(f"[Cover] 上传失败 HTTP {resp.status_code}: {resp.text[:120]}")
            return "", ""
        data = resp.json() or {}
        self.log.info(f"[Cover] 已上传 {name} -> {data.get('path')}")
        return data.get("path", ""), data.get("work_dir", "")

    def _download(self, remote_path, local_path, timeout=1800):
        try:
            resp = requests.get(f"{self.config.rvc_url}/api/download",
                                params={"path": remote_path}, stream=True,
                                timeout=(30, timeout))
            if resp.status_code != 200:
                self.log.error(f"[Cover] 下载失败 HTTP {resp.status_code}: {remote_path}")
                return False
            parent = os.path.dirname(local_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = local_path + ".part"
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    if chunk:
                        f.write(chunk)
            if os.path.getsize(tmp) <= 0:
                os.remove(tmp)
                return False
            os.replace(tmp, local_path)
            self.log.info(f"[Cover] 已下载 {os.path.basename(local_path)}")
            return True
        except Exception:
            self.log.exception("[Cover] 下载产物异常")
            return False

    def convert(self, vocal_path, output_path, f0_up_key=None, formant=None):
        output_path = os.path.abspath(output_path)
        remote_vocal = self._is_remote_path(vocal_path)

        if f0_up_key is None:
            if remote_vocal and self._last_remote_f0:
                f0_up_key = int(self._last_remote_f0)
                self.log.info(f"[Cover] 使用服务端变调值: {f0_up_key}")
            else:
                f0_up_key = self._resolve_f0_up_key(
                    self._last_source if (remote_vocal and self._last_source) else vocal_path)
        if formant is None:
            formant = self._resolve_formant()

        out_req = output_path
        if remote_vocal:
            out_req = str(vocal_path).rsplit("/", 1)[0] + "/cover.wav"
        data = self._post_convert(vocal_path, out_req, f0_up_key, formant, quiet=True)
        if data is None and not remote_vocal:
            remote_in, work_dir = self._upload(os.path.abspath(vocal_path))
            if not remote_in:
                return ""
            data = self._post_convert(remote_in, os.path.join(work_dir, "cover.wav"),
                                     f0_up_key, formant)
        if data is None:
            return ""

        produced = data.get("output_path") or ""
        if not self._is_remote_path(produced):
            return produced
        if self._download(produced, output_path):
            return output_path
        self.log.error("[Cover] 变声产物下载失败")
        return ""

    def _post_convert(self, input_path, output_path, f0_up_key, formant, quiet=False):
        payload = {
            "model": self.config.rvc_model,
            "index": self.config.rvc_index,
            "input_path": input_path,
            "output_path": output_path,
            "f0_up_key": f0_up_key,
            "formant": formant,
            "f0_method": self.config.rvc_f0_method,
            "index_rate": self.config.rvc_index_rate,
            "protect": self.config.rvc_protect,
            "rms_mix_rate": self.config.rvc_rms_mix_rate,
            "resample_sr": self.config.rvc_resample_sr,
        }
        try:
            resp = requests.post(f"{self.config.rvc_url}/api/convert", json=payload, timeout=3600)
            data = resp.json()
        except Exception:
            if not quiet:
                self.log.exception("[Cover] 调 RVC 变声异常")
            return None
        if not isinstance(data, dict) or data.get("code") != 200:
            if not quiet:
                msg = data.get("msg") if isinstance(data, dict) else f"HTTP {resp.status_code}"
                self.log.error(f"[Cover] 变声失败: {msg}")
            return None
        return data


    def _resolve_f0_up_key(self, vocal_path):
        """动态变调：实测干声 F0 中位，向目标音高靠拢（不分男女，只认实际音高）"""
        try:
            import librosa
            y, sr = librosa.load(vocal_path, sr=16000, mono=True)
            f0, voiced_flag, _ = librosa.pyin(
                y, fmin=60, fmax=800, sr=sr
            )
            if voiced_flag is None or not np.any(voiced_flag):
                return 0
            med = float(np.median(f0[voiced_flag]))
            if med <= 0:
                return 0
            target = float(self.config.target_f0 or 325)
            semitones = 12.0 * np.log2(target / med)
            return int(round(np.clip(semitones, -24, 24)))
        except Exception:
            self.log.exception("[Cover] F0 检测失败，按不转调处理")
            return 0

    def _resolve_formant(self):
        """音色偏移：直接取配置的 formant（半音，正=更细更年轻，负=更粗更成熟）"""
        try:
            return float(self.config.formant or 0)
        except (TypeError, ValueError):
            return 0.0

    def learn_song(self, title, mp3_path):
        """学习一首歌：分离 → 变声 → 三轨与歌词保存到 meow_list，返回是否成功"""
        title = self._safe_name(title)
        folder = os.path.abspath(os.path.join(MEOW_DIR, title))
        os.makedirs(folder, exist_ok=True)

        separated = self.separate(mp3_path, folder)
        if not separated or not separated.get("vocal"):
            return False

        cover_path = os.path.join(folder, f"{title}_vocal.wav")
        converted = self.convert(separated["vocal"], cover_path)
        if not converted or not os.path.exists(converted):
            return False

        converted = os.path.abspath(converted)
        if converted != cover_path:
            shutil.move(converted, cover_path)

        if separated.get("accomp"):
            _src = separated["accomp"]
            _dst = os.path.join(folder, f"{title}_accomp.wav")
            if os.path.abspath(_src) != os.path.abspath(_dst):
                try:
                    shutil.copy(_src, _dst)
                except Exception:
                    self.log.exception("[Cover] 复制伴奏失败")
        if separated.get("harmony"):
            _src = separated["harmony"]
            _dst = os.path.join(folder, f"{title}_harmony.wav")
            if os.path.abspath(_src) != os.path.abspath(_dst):
                try:
                    shutil.copy(_src, _dst)
                except Exception:
                    self.log.exception("[Cover] 复制和声失败")

        lrc_src = os.path.join(RAW_DIR, title, f"{title}.lrc")
        if os.path.exists(lrc_src):
            try:
                shutil.copy(lrc_src, os.path.join(folder, f"{title}.lrc"))
            except Exception:
                self.log.exception("[Cover] 复制歌词失败")

        # 生成音高缓存 npy（学歌成功即生成，失败下次启动补生成）
        try:
            from func.toolbox.meowsongs.pass_the_baton.hum_match import TBHumMatch
            TBHumMatch().build_pitch_cache(title, cover_path)
        except Exception:
            self.log.exception("[Cover] 生成音高缓存失败")

        # 学歌成功后清理中间产物（分离器带模型名的原始 wav、lead 等）
        self._cleanup_intermediates(folder, title)
        return True

    def _cleanup_intermediates(self, folder, title):
        """学歌成功后删除中间 wav，只保留三轨（vocal/accomp/harmony）"""
        keep = {
            f"{title}_vocal.wav",
            f"{title}_accomp.wav",
            f"{title}_harmony.wav",
        }
        try:
            for name in os.listdir(folder):
                if not name.lower().endswith(".wav"):
                    continue
                if name in keep:
                    continue
                p = os.path.join(folder, name)
                if os.path.isfile(p):
                    os.remove(p)
                    self.log.info(f"[Cover] 清理中间产物: {name}")
        except Exception:
            self.log.exception("[Cover] 清理中间产物失败")

    def mix_tracks(self, vocal_path, accomp_path, harmony_path):
        """把三轨对齐长度混音，返回 (audio, sr) 或 None"""
        try:
            vocal, sr = sf.read(vocal_path, dtype="float32")
            tracks = [self._to_stereo(vocal, sr)]
            for p in (accomp_path, harmony_path):
                if p and os.path.exists(p):
                    data, rate = sf.read(p, dtype="float32")
                    if rate != sr:
                        data = self._resample(data, rate, sr)
                    tracks.append(self._to_stereo(data, sr))
            if not tracks:
                return None
            min_len = min(t.shape[0] for t in tracks)
            mixed = sum(t[:min_len] for t in tracks)
            # 整体音量：按配置轻一点（cover_volume，默认 0.85）
            mixed = mixed * self.config.cover_volume
            mixed = np.clip(mixed, -1.0, 1.0)
            return mixed.astype(np.float32), sr
        except Exception:
            self.log.exception("[Cover] 混音失败")
            return None

    def _to_stereo(self, data, sr):
        if data.ndim == 1:
            return np.column_stack([data, data])
        return data

    def _resample(self, data, orig_sr, target_sr):
        import librosa
        if data.ndim == 1:
            return librosa.resample(data, orig_sr=orig_sr, target_sr=target_sr)
        return librosa.resample(data.T, orig_sr=orig_sr, target_sr=target_sr).T

    def has_learned(self, title):
        title = self._safe_name(title)
        folder = os.path.join(MEOW_DIR, title)
        vocal = os.path.join(folder, f"{title}_vocal.wav")
        accomp = os.path.join(folder, f"{title}_accomp.wav")
        return os.path.exists(vocal) and os.path.exists(accomp)

    def raw_mp3_path(self, title):
        title = self._safe_name(title)
        return os.path.join(RAW_DIR, title, f"{title}.mp3")

    @staticmethod
    def _safe_name(name):
        import re
        return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip() or "未命名"
