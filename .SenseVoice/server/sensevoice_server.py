#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SenseVoice WebSocket 识别服务端
# 支持：整段识别、声纹识别、多语言识别

import asyncio
import json
import sys
import os
import wave
import time
import argparse
import ssl
import numpy as np
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from scipy.spatial.distance import cosine

import torch
import websockets
from funasr import AutoModel


# ==================== 参数解析 ====================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

parser = argparse.ArgumentParser()
parser.add_argument("--host", type=str, default="0.0.0.0")
parser.add_argument("--port", type=int, default=10095)
parser.add_argument("--model_dir", type=str, 
    default=os.path.join(PROJECT_ROOT, "localmodels", "SenseVoiceSmall"))
parser.add_argument("--device", type=str, default="cuda")
parser.add_argument("--ngpu", type=int, default=1)
parser.add_argument("--ncpu", type=int, default=4)

parser.add_argument("--sv_model", type=str, 
    default=os.path.join(PROJECT_ROOT, "localmodels", "speech_campplus_sv_zh-cn_16k-common"))
parser.add_argument("--speaker_db_path", type=str, 
    default=os.path.join(PROJECT_ROOT, "voicetexture", "speaker_db.json"))
parser.add_argument("--sv_threshold", type=float, default=0.2)
parser.add_argument("--speaker_db_reload_sec", type=int, default=5)

parser.add_argument("--worker_threads", type=int, default=4)
parser.add_argument("--concurrent_asr", type=int, default=4)
parser.add_argument("--concurrent_sv", type=int, default=2)

args = parser.parse_args()

# ==================== 模型加载 ====================
print("正在加载 SenseVoice 模型...")
model_asr = AutoModel(
    model=args.model_dir,
    trust_remote_code=True,
    device=args.device,
    ngpu=args.ngpu,
    ncpu=args.ncpu,
    disable_pbar=True,
    disable_log=False,
    disable_update=True,
)
print("SenseVoice 模型加载完成")

# 加载声纹模型（CAM++）
print("正在加载声纹模型...")
model_sv = AutoModel(
    model=args.sv_model,
    device=args.device,
    ngpu=args.ngpu,
    disable_pbar=True,
    disable_log=False,
    disable_update=True,
)
print("声纹模型加载完成")

# 线程池
executor = ThreadPoolExecutor(max_workers=args.worker_threads)

# 并发信号量
sem_asr = asyncio.Semaphore(args.concurrent_asr)
sem_sv = asyncio.Semaphore(args.concurrent_sv)

# 音频参数
SAMPLE_RATE = 16000

# ==================== 辅助函数 ====================
def to_python(obj):
    """将numpy/torch类型转换为Python原生类型"""
    try:
        import numpy as np
        import torch
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, torch.Tensor):
            return obj.cpu().tolist()
    except Exception:
        pass
    if isinstance(obj, dict):
        return {k: to_python(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_python(v) for v in obj]
    return obj


def save_audio_to_wav(audio_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """将PCM音频字节保存为临时WAV文件，返回文件路径"""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    with wave.open(tmp_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)
    return tmp_path


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算余弦相似度"""
    return 1.0 - cosine(a, b)


# ==================== 声纹识别模块 ====================
class SpeakerVerification:
    """声纹识别管理器"""
    
    def __init__(self, model, db_path: str, reload_sec: int, threshold: float):
        self.model = model
        self.db_path = db_path
        self.reload_sec = reload_sec
        self.threshold = threshold
        self._cache = {}
        self._cache_ts = 0.0
    
    def _load_db(self) -> Dict:
        """加载声纹数据库"""
        if not os.path.exists(self.db_path):
            return {}
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    
    def _get_db_cached(self) -> Dict:
        """获取缓存的声纹数据库"""
        now = time.time()
        if now - self._cache_ts >= self.reload_sec:
            self._cache = self._load_db()
            self._cache_ts = now
        return self._cache
    
    def extract_embedding(self, audio_bytes: bytes) -> Optional[np.ndarray]:
        tmp_path = None
        try:
            tmp_path = save_audio_to_wav(audio_bytes)
            result = self.model.generate(input=tmp_path, embedding=True)
            if result and len(result) > 0:
                embedding = result[0].get("spk_embedding")
                if embedding is not None:
                    # 转换为 numpy 数组
                    if torch.is_tensor(embedding):
                        embedding = embedding.cpu().numpy()
                    # 处理多维：如果形状是 (1, dim)，取第一个元素
                    if embedding.ndim == 2 and embedding.shape[0] == 1:
                        embedding = embedding[0]
                    elif embedding.ndim > 2:
                        embedding = embedding.flatten()
                    # 最终确保是一维
                    if embedding.ndim != 1:
                        raise ValueError(f"无法转换为1维向量，形状: {embedding.shape}")
                    return embedding.astype(np.float32)
            return None
        except Exception as e:
            print(f"声纹提取失败: {e}")
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)    

    def verify(self, audio_bytes: bytes) -> tuple:
        """
        验证说话人身份
        返回: (speaker_name, score)
        """
        embedding = self.extract_embedding(audio_bytes)
        if embedding is None:
            return "unknown", 0.0
        
        best_name = "unknown"
        best_score = 0.0
        db = self._get_db_cached()
        
        for name, ref_embedding in db.items():
            if ref_embedding is None:
                continue
            ref_arr = np.array(ref_embedding, dtype=np.float32)
            similarity = cosine_similarity(embedding, ref_arr)
            print(f"声纹相似度 [{name}]: {similarity:.4f}")
            if similarity > best_score and similarity > self.threshold:
                best_score = similarity
                best_name = name
        
        return best_name, float(best_score)
    
    def register_speaker(self, name: str, audio_bytes: bytes) -> bool:
        """注册新说话人"""
        embedding = self.extract_embedding(audio_bytes)
        if embedding is None:
            return False
        
        db = self._load_db()
        db[name] = embedding.tolist()
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            # 刷新缓存
            self._cache_ts = 0
            return True
        except Exception as e:
            print(f"保存声纹数据库失败: {e}")
            return False


# ==================== WebSocket 处理 ====================
class SenseVoiceSession:
    """单个WebSocket会话"""
    
    def __init__(self, websocket, sv: SpeakerVerification):
        self.websocket = websocket
        self.sv = sv
        self.audio_buffer = bytearray()  # 累积的音频缓冲区（用于最终识别）
        self.is_speaking = True
        self.wav_name = "mic"
        self.language = "auto"
        self.itn = True
        self.hotwords = {}

    async def handle_text_message(self, message: dict):
        """处理文本配置消息"""
        if "is_speaking" in message:
            was_speaking = self.is_speaking
            self.is_speaking = message["is_speaking"]
            
            if not was_speaking and self.is_speaking:
                # 开始说话：重置缓冲区
                self.audio_buffer = bytearray()
                print("客户端开始说话")
            elif was_speaking and not self.is_speaking:
                # 结束说话：触发最终识别
                if len(self.audio_buffer) > 0:
                    print(f"说话结束，触发识别 ({len(self.audio_buffer)} bytes)")
                    await self._recognize_final()
                print("客户端结束说话")
        
        if "wav_name" in message:
            self.wav_name = message.get("wav_name", self.wav_name)
        if "language" in message:
            self.language = message.get("language", self.language)
        if "itn" in message:
            self.itn = bool(message.get("itn", self.itn))
        if "hotwords" in message:
            hotwords = message.get("hotwords", {})
            if isinstance(hotwords, str):
                try:
                    hotwords = json.loads(hotwords)
                except Exception:
                    hotwords = {}
            self.hotwords = hotwords if isinstance(hotwords, dict) else {}
    
    async def _recognize_final(self):
        """识别最终结果（说话结束时调用）"""
        if len(self.audio_buffer) == 0:
            return
        
        # 创建临时WAV文件
        tmp_path = save_audio_to_wav(bytes(self.audio_buffer))
        try:
            # ASR识别
            res = await run_blocking(
                model_asr.generate,
                input=tmp_path,
                language=self.language,
                use_itn=self.itn,
                hotwords=self.hotwords,
                sem=sem_asr
            )
            
            if res and len(res) > 0:
                text = res[0].get("text", "")
                # 清理特殊标签
                import re
                text = re.sub(r'<\|.*?\|>', '', text)
                
                # 声纹识别
                spk_name, spk_score = await run_blocking(
                    self.sv.verify,
                    bytes(self.audio_buffer),
                    sem=sem_sv
                )
                
                # 发送结果
                message = {
                    "mode": "offline",
                    "spk_name": spk_name,
                    "spk_score": spk_score,
                    "text": text,
                    "wav_name": self.wav_name,
                    "is_final": True,
                }
                await self.websocket.send(json.dumps(message, ensure_ascii=False))
                print(f"识别结果: [{spk_name}] {text}")
        except Exception as e:
            print(f"识别失败: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    async def handle_audio(self, audio_chunk: bytes):
        if self.is_speaking:
            self.audio_buffer.extend(audio_chunk)

# ==================== 辅助函数 ====================
async def run_blocking(fn, *args, sem: Optional[asyncio.Semaphore] = None, **kwargs):
    """在线程池中执行阻塞函数"""
    loop = asyncio.get_running_loop()
    if sem is None:
        return await loop.run_in_executor(executor, lambda: fn(*args, **kwargs))
    async with sem:
        return await loop.run_in_executor(executor, lambda: fn(*args, **kwargs))


# ==================== WebSocket 服务 ====================
connected_sessions = set()

async def ws_handler(websocket, path=None):
    """WebSocket连接处理器"""
    sv = SpeakerVerification(model_sv, args.speaker_db_path, args.speaker_db_reload_sec, args.sv_threshold)
    session = SenseVoiceSession(websocket, sv)
    connected_sessions.add(websocket)
    
    print(f"新客户端连接，当前连接数: {len(connected_sessions)}")
    
    try:
        async for message in websocket:
            if isinstance(message, str):
                # 文本配置消息
                try:
                    msg_json = json.loads(message)
                    await session.handle_text_message(msg_json)
                except json.JSONDecodeError as e:
                    print(f"JSON解析错误: {e}")
                    continue
            else:
                # 二进制音频数据
                await session.handle_audio(message)
    except websockets.exceptions.ConnectionClosed:
        print("客户端连接关闭")
    except Exception as e:
        print(f"连接异常: {e}")
    finally:
        connected_sessions.discard(websocket)
        print(f"客户端断开，当前连接数: {len(connected_sessions)}")


async def main():
    """启动WebSocket服务"""
    ssl_context = None
    # 如需启用SSL，取消注释
    # if os.path.exists(args.certfile) and os.path.exists(args.keyfile):
    #     ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    #     ssl_context.load_cert_chain(args.certfile, keyfile=args.keyfile)
    
    server = await websockets.serve(
        ws_handler,
        args.host,
        args.port,
        subprotocols=["binary"],
        ping_interval=60,
        ping_timeout=30,
        ssl=ssl_context,
    )
    
    print(f"SenseVoice WebSocket 服务已启动")
    print(f"地址: ws://{args.host}:{args.port}")
    print(f"声纹识别: {args.sv_model}")
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        executor.shutdown(wait=False)