import os
import threading
import datetime
import json
import re
import jieba
import logging
from typing import List, Dict, Optional, Callable, Any
from mem0 import Memory
from chromadb import Client
from .bm25 import BM25
from .memory import MemoryManager

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 可选：添加控制台处理器，确保日志输出
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# 全局 mem0 客户端（单例）
_mem0_client = None
_mem0_lock = threading.Lock()

def get_mem0_client(config: Optional[Dict] = None):
    """获取或创建全局 mem0 客户端（线程安全）"""
    global _mem0_client
    if _mem0_client is None:
        with _mem0_lock:
            if _mem0_client is None:
                if config is None:
                    # 默认配置（实际会在 llm_core 中传入具体配置）
                    config = {
                        "vector_store": {
                            "provider": "chroma",
                            "config": {
                                "collection_name": "mem0",
                                "path": "./mem0_data",
                            }
                        },
                        "embedder": {
                            "provider": "huggingface",
                            "config": {
                                "model": "./mem0model-small",
                            }
                        },
                        "llm": {
                            "provider": "ollama",
                            "config": {
                                "api_key": "dummy",
                                "model": "qwen2.5:1.5b",
                                "ollama_base_url": "http://localhost:11434"
                            }
                        }
                    }
                try:
                    logger.info("正在创建 mem0 客户端...")
                    _mem0_client = Memory.from_config(config)
                    logger.info("mem0 客户端创建成功")
                except Exception as e:
                    logger.error(f"创建 mem0 客户端失败: {e}", exc_info=True)
                    raise
    return _mem0_client


class Mem0Manager:
    STOPWORDS = MemoryManager.STOPWORDS

    """
    基于 mem0 的长期记忆管理器
    - 每 max_pending_rounds 轮对话生成摘要（若 enable_summary=True）或直接存储原文
    - 构建消息时注入短期记忆（最近 short_term_rounds 轮）和检索到的长期记忆
    - 新增：去重机制（相似度阈值 deduplication_threshold）
    - 新增：日期询问时自动插入时间戳前缀
    """

    def __init__(self, uid: str,
                 max_pending_rounds: int = 5,
                 short_term_rounds: int = 3,
                 summary_generator: Optional[Callable[[str], str]] = None,
                 enable_summary: bool = True,
                 mem0_config: Optional[Dict] = None,
                 shared_user_id: Optional[str] = None,
                 deduplication_threshold: float = 1.25,
                 date_query_keywords: Optional[List[str]] = None,
                 avoid_keywords: Optional[List[str]] = None,
                 template_type: str = "chatml",
                 long_term_dir: str = "./chatrecords",
                 ai_name: str = "喵呜",
                 chat_record_dir: str = "./chatrecords",
                 enable_mem0: bool = True,
                 enable_chat_record_retrieval: bool = True,
                 chat_record_days: int = 7,
                 chat_record_top_k: int = 3):
        self.uid = str(uid)
        self.shared_user_id = shared_user_id
        self.max_pending_rounds = max_pending_rounds
        self.short_term_rounds = short_term_rounds
        self.summary_generator = summary_generator
        self.enable_summary = enable_summary
        self.deduplication_threshold = deduplication_threshold

        self.date_query_keywords = date_query_keywords or ["哪天", "哪一天", "之前", "以前", "什么时候", "几号", "何时"]
        self.avoid_keywords = avoid_keywords or ["生日", "节日", "纪念日"]

        logger.info(f"初始化 Mem0Manager: uid={uid}, shared_user_id={shared_user_id}, "
                    f"max_pending_rounds={max_pending_rounds}, short_term_rounds={short_term_rounds}, "
                    f"enable_summary={enable_summary}, deduplication_threshold={deduplication_threshold}, "
                    f"template_type={template_type}, long_term_dir={long_term_dir}")

        try:
            self.mem0 = get_mem0_client(mem0_config)
            logger.info("mem0 客户端获取成功")
        except Exception as e:
            logger.error(f"获取 mem0 客户端失败: {e}", exc_info=True)
            self.mem0 = None  # 防止后续使用报错

        self.pending_dialogues: List[Dict[str, str]] = []
        self.lock = threading.RLock()
        self.pending_user_message = None
        self.pending_username = None
        self.template_type = template_type
        self.long_term_dir = long_term_dir
        os.makedirs(self.long_term_dir, exist_ok=True)
        self._file_lock = threading.Lock()

        self._chat_documents = []
        self._chat_bm25 = None
        self._last_index_time = 0
        self._chat_index_lock = threading.Lock()

        self.ai_name = ai_name
        self.chat_record_dir = chat_record_dir
        os.makedirs(self.chat_record_dir, exist_ok=True)

        self.enable_mem0 = enable_mem0
        self.enable_chat_record_retrieval = enable_chat_record_retrieval
        self.chat_record_days = chat_record_days
        self.chat_record_top_k = chat_record_top_k

    def add_user_message(self, message: str, username: str):
        """记录用户消息，等待 assistant 回复"""
        with self.lock:
            #logger.debug(f"添加用户消息: uid={self.uid}, username={username}, message={message[:50]}...")
            self.pending_user_message = message
            self.pending_username = username

    def add_assistant_message(self, message: str):
        with self.lock:
            if self.pending_user_message is None:
                raise RuntimeError("没有待处理的用户消息，请先调用 add_user_message")
            username = self.pending_username
            round_data = {
                "user": self.pending_user_message,
                "assistant": message,
                "username": username,
            }
            self.pending_dialogues.append(round_data)
            #logger.debug(f"添加助手消息，当前待存储轮次: {len(self.pending_dialogues)}/{self.max_pending_rounds}")

            if len(self.pending_dialogues) >= self.max_pending_rounds:
                to_store = self.pending_dialogues[:]
                self.pending_dialogues = []
                #logger.info(f"达到存储阈值，开始存储 {len(to_store)} 轮对话")
                threading.Thread(target=self._store_dialogues, args=(to_store,)).start()

            self.pending_user_message = None
            self.pending_username = None

    def _get_mem0_user_id(self):
        user_id = self.shared_user_id if self.shared_user_id is not None else self.uid
        logger.debug(f"获取 mem0 用户ID: {user_id}")
        return user_id

    def _store_dialogues(self, dialogues: List[Dict[str, str]]):
        """将多轮对话存储到 mem0（摘要或原文）"""
        try:
            dialogue_text = ""
            for d in dialogues:
                dialogue_text += f"({d['username']})：{d['user']}\n"
                dialogue_text += f"喵呜：{d['assistant']}\n"

            #logger.debug(f"开始存储 {len(dialogues)} 轮对话，原始文本长度: {len(dialogue_text)}")

            if self.enable_summary and self.summary_generator:
                #logger.info("使用摘要生成器生成记忆摘要")
                content = self.summary_generator(dialogue_text)
                mem_type = "summary"
            else:
                content = dialogue_text.strip()
                mem_type = "raw"
                #logger.info("未启用摘要或摘要生成器缺失，存储原始对话")

            if content:
                # 清理控制字符
                content = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', content)
                content = re.sub(r' +', ' ', content).strip()
                if len(content) > 1000:
                    content = content[:1000] + "…"
                    #logger.debug(f"内容截断至 1000 字符")

                metadata = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "type": mem_type,
                    "rounds": len(dialogues)
                }
                user_id = self._get_mem0_user_id()

                # 去重检查
                if self.mem0 is None:
                    logger.warning("mem0 客户端不可用，跳过存储")
                    return

                try:
                    search_results = self.mem0.search(content, user_id=user_id, limit=1)
                    if search_results and "results" in search_results:
                        for r in search_results["results"]:
                            score = r.get("score", 0)
                            if score > self.deduplication_threshold:
                                logger.info(f"记忆重复，相似度 {score:.2f}，跳过存储: {content[:50]}...")
                                return
                    logger.debug("去重检查通过，开始存储")
                except Exception as e:
                    logger.error(f"去重检查失败: {e}", exc_info=True)
                    # 继续尝试存储

                # 存储到 mem0
                try:
                    self.mem0.add(content, user_id=user_id, metadata=metadata)
                    logger.info(f"成功存储 {mem_type} 记忆（{len(dialogues)}轮）: {content[:50]}...")
                except Exception as e:
                    logger.error(f"存储记忆失败: {e}", exc_info=True)
                    logger.error(f"问题内容片段: {content[:200]}")

                # 写入文本文件
                username = dialogues[0].get("username", "unknown") if dialogues else "unknown"
                self._save_to_text_file(username, content, mem_type.upper())
            else:
                logger.warning("生成的内容为空，跳过存储")
        except Exception as e:
            logger.error(f"_store_dialogues 发生未捕获异常: {e}", exc_info=True)

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict]:
        """从 mem0 检索相关记忆，返回包含 memory 和 metadata 的字典列表"""
        if not query:
            logger.debug("检索查询为空，返回空列表")
            return []
        if self.mem0 is None:
            logger.warning("mem0 客户端不可用，返回空检索结果")
            return []

        user_id = self._get_mem0_user_id()
        logger.debug(f"检索查询: {query[:50]}..., user_id={user_id}, top_k={top_k}")
        try:
            response = self.mem0.search(query, user_id=user_id, limit=top_k)
            results = response.get("results", [])
            logger.info(f"检索到 {len(results)} 条相关记忆")
            # 可选：记录每条记忆的相似度
            for i, r in enumerate(results[:3]):  # 仅记录前3条
                logger.debug(f"记忆 {i+1}: score={r.get('score')}, memory={r.get('memory', '')[:50]}...")
            return [{"memory": r["memory"], "metadata": r.get("metadata", {})} for r in results if "memory" in r]
        except Exception as e:
            logger.error(f"检索记忆失败: {e}", exc_info=True)
            return []

    def build_messages(self, current_user_message: str, username: str, include_long_term: bool = True) -> List[Dict[str, str]]:
        """
        构建发送给 LLM 的消息列表
        - 短期记忆（最近 short_term_rounds 轮）
        - 长期记忆：mem0 检索 + 聊天记录文件检索（使用 BM25）
        - 当前用户消息
        """
        messages = []

        # ========== 短期记忆 ==========
        with self.lock:
            recent_dialogues = self.pending_dialogues[-self.short_term_rounds:] if self.pending_dialogues else []

        logger.debug(f"构建消息，短期记忆轮数: {len(recent_dialogues)}")

        if self.template_type == "mistral":
            for round_data in recent_dialogues:
                messages.append({"role": "user", "content": round_data["user"]})
                messages.append({"role": "assistant", "content": round_data["assistant"]})
        else:
            for round_data in recent_dialogues:
                messages.append({"role": "user", "content": f"{username}：{round_data['user']}"})
                messages.append({"role": "assistant", "content": round_data["assistant"]})

        # ========== 长期记忆 ==========
        memory_texts = []

        if include_long_term:
            # 1. 从 mem0 检索相关记忆（个性记忆）
            if self.enable_mem0:
                mem0_results = self.retrieve(current_user_message, top_k=5)
                if mem0_results:
                    logger.info(f"从 mem0 检索到 {len(mem0_results)} 条相关记忆")
                    # 处理日期查询（保持原有逻辑）
                    is_date_query = any(kw in current_user_message for kw in self.date_query_keywords)
                    has_avoid = any(kw in current_user_message for kw in self.avoid_keywords)
            
                    if is_date_query and not has_avoid:
                        for item in mem0_results:
                            ts = item.get("metadata", {}).get("timestamp")
                            if ts:
                                try:
                                    date_part = ts.split("T")[0]
                                    year, month, day = date_part.split("-")
                                    item["memory"] = f"[{year}年{month}月{day}日] {item['memory']}"
                                except Exception as e:
                                    logger.error(f"日期前缀添加失败: {e}")
            
                    # 按时间倒序排序（日期查询时）
                    if is_date_query:
                        import datetime
                        def get_timestamp(item):
                            ts = item.get("metadata", {}).get("timestamp")
                            if ts:
                                try:
                                    return datetime.datetime.fromisoformat(ts)
                                except:
                                    return datetime.datetime.min
                            return datetime.datetime.min
                        mem0_results.sort(key=get_timestamp, reverse=True)
                        logger.debug("日期查询，记忆按时间倒序排序")
            
                    # 提取记忆文本
                    for item in mem0_results:
                        memory_texts.append(item["memory"])
            else:
                logger.debug("个性记忆 (mem0) 已禁用")

            # 2. 从聊天记录文件检索相关对话片段（历史对话记忆）
            if self.enable_chat_record_retrieval and self.enable_summary and self.summary_generator:
                chat_fragments = self._retrieve_from_chat_records(
                    current_user_message, 
                    top_k=self.chat_record_top_k,
                    days_limit=self.chat_record_days
                )
                if chat_fragments:
                    logger.info(f"从聊天记录检索到 {len(chat_fragments)} 条相关对话片段")
                    for i, fragment in enumerate(chat_fragments):
                        try:
                            # 直接使用片段原文，不生成摘要
                            if fragment and len(fragment) > 5:
                                memory_texts.append(f"[曾经的对话记录] {fragment}")
                                logger.debug(f"片段 {i+1} 原文: {fragment[:20]}...")
                            else:
                                logger.warning(f"片段 {i+1} 内容过短或为空")
                        except Exception as e:
                            logger.error(f"处理片段失败: {e}", exc_info=True)
            else:
                if not self.enable_chat_record_retrieval:
                    logger.debug("聊天记录检索已禁用")
                elif not self.enable_summary:
                    logger.debug("摘要生成未启用，跳过聊天记录检索")
                elif not self.summary_generator:
                    logger.debug("摘要生成器不可用，跳过聊天记录检索")

            # 3. 合并所有长期记忆并插入消息
            if memory_texts:
                # 去重（基于内容相似度，简单去重）
                unique_memories = []
                seen = set()
                for mem in memory_texts:
                    # 使用前50个字符作为去重键
                    key = mem[:50] if len(mem) > 50 else mem
                    if key not in seen:
                        seen.add(key)
                        unique_memories.append(mem)
            
                memory_text = "；".join(unique_memories)
                logger.info(f"最终插入 {len(unique_memories)} 条长期记忆，总长度: {len(memory_text)}")
            
                # 根据模板类型决定插入方式
                if self.template_type == "mistral":
                    current_user_message = f"[背景记忆：{memory_text}]\n\n{current_user_message}"
                else:
                    messages.insert(0, {"role": "user", "content": f"[喵呜的记忆：{memory_text}]"})
            else:
                logger.debug("未找到相关长期记忆")

        # ========== 添加当前用户消息 ==========
        messages.append({"role": "user", "content": current_user_message})

        logger.debug(f"构建完成，消息总数: {len(messages)}")
        return messages

    def _save_to_text_file(self, username: str, content: str, mem_type: str):
        """将记忆写入文本文件，按用户名命名"""
        try:
            safe_username = re.sub(r'[\\/*?:"<>|]', "_", username)
            filepath = os.path.join(self.long_term_dir, f"{safe_username}.txt")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record = f"{timestamp} [{mem_type}] {content}\n"

            with self._file_lock:
                with open(filepath, "a", encoding="utf-8") as f:
                    f.write(record)
            logger.debug(f"记忆已写入文本文件: {filepath}")
        except Exception as e:
            logger.error(f"写入文本文件失败: {e}", exc_info=True)

    def _parse_chat_record_files(self, days_limit: int = 7) -> List[Dict[str, Any]]:
        """解析最近 days_limit 天的聊天记录文件，返回对话轮次列表（用户+助手配对或单独助手/用户消息）"""
        now = datetime.datetime.now()
        documents = []

        for i in range(days_limit):
            date_str = (now - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            filepath = os.path.join(self.chat_record_dir, f"{date_str}.txt")

            if not os.path.exists(filepath):
                continue

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                pending_user = None  # 暂存未配对的用户消息

                idx = 0
                while idx < len(lines):
                    line = lines[idx].strip()
                    if not line:
                        idx += 1
                        continue

                    match = re.match(r'\[(\d{2}:\d{2})\]\s*([^：]+)：\s*(.+)', line)
                    if not match:
                        logger.warning(f"无法解析行: {line}")
                        idx += 1
                        continue

                    timestamp = match.group(1)
                    role = match.group(2).strip()
                    content = match.group(3).strip()

                    if role == self.ai_name:
                        # 如果是助手消息
                        if pending_user:
                            # 有未配对的用户消息 → 形成完整对话轮次
                            round_text = f"{pending_user['role']}：{pending_user['content']}\n{self.ai_name}：{content}"
                            documents.append({
                                "text": round_text,
                                "timestamp": f"{date_str} {pending_user['timestamp']}",
                                "type": "user_assistant_pair",
                                "user_role": pending_user['role'],
                                "user_content": pending_user['content'],
                                "assistant_content": content,
                                "user_time": f"{date_str} {pending_user['timestamp']}",
                                "assistant_time": f"{date_str} {timestamp}"
                            })
                            pending_user = None
                        else:
                            # 没有配对的用户消息 → 孤立助手消息（自言自语），保留
                            round_text = f"{self.ai_name}：{content}"
                            documents.append({
                                "text": round_text,
                                "timestamp": f"{date_str} {timestamp}",
                                "type": "assistant_only",
                                "role": self.ai_name,
                                "content": content
                            })
                        idx += 1
                        continue

                    # 当前行是用户消息
                    if pending_user:
                        # 前一条用户消息尚未配对 → 作为单独的用户消息存储
                        round_text = f"{pending_user['role']}：{pending_user['content']}"
                        documents.append({
                            "text": round_text,
                            "timestamp": f"{date_str} {pending_user['timestamp']}",
                            "type": "user_only",
                            "role": pending_user['role'],
                            "content": pending_user['content']
                        })
                    # 暂存当前用户消息，等待可能的助手回复
                    pending_user = {
                        "role": role,
                        "content": content,
                        "timestamp": timestamp
                    }
                    idx += 1

                # 文件处理完后，若还有未配对的用户消息，单独存储
                if pending_user:
                    round_text = f"{pending_user['role']}：{pending_user['content']}"
                    documents.append({
                        "text": round_text,
                        "timestamp": f"{date_str} {pending_user['timestamp']}",
                        "type": "user_only",
                        "role": pending_user['role'],
                        "content": pending_user['content']
                    })

            except Exception as e:
                logger.error(f"解析聊天记录文件失败 {filepath}: {e}", exc_info=True)

        logger.debug(f"解析完成，共获取 {len(documents)} 条对话片段")
        return documents

    def _retrieve_from_chat_records(self, query: str, top_k: int = 3, days_limit: int = 7) -> List[str]:
        """从聊天记录文件中检索相关对话片段，返回片段文本列表"""
        # 检查是否需要重建索引（例如超过 1 小时更新一次）
        now = datetime.datetime.now().timestamp()
        with self._chat_index_lock:
            if now - self._last_index_time > 3600 or not self._chat_bm25:
                logger.debug(f"重建聊天记录索引 (上次索引时间: {self._last_index_time})")
                self._chat_documents = self._parse_chat_record_files(days_limit=days_limit)
                if self._chat_documents:
                    corpus = [doc["text"] for doc in self._chat_documents]
                    try:
                        self._chat_bm25 = BM25(corpus, self._tokenize)
                        logger.info(f"聊天记录索引构建完成，共 {len(self._chat_documents)} 条对话片段")
                    except Exception as e:
                        logger.error(f"BM25 索引构建失败: {e}", exc_info=True)
                        self._chat_bm25 = None
                else:
                    logger.warning(f"未找到聊天记录文件或解析结果为空 (days_limit={days_limit})")
                    self._chat_bm25 = None
                self._last_index_time = now
    
        if not self._chat_bm25:
            return []
    
        # 对查询进行分词
        query_tokens = self._tokenize(query)
        if not query_tokens:
            logger.debug("查询分词结果为空")
            return []
    
        query_str = " ".join(query_tokens)
        try:
            scores = self._chat_bm25.get_scores(query_str)
            # 取 top_k
            indexed = [(i, s) for i, s in enumerate(scores) if s > 0]
            indexed.sort(key=lambda x: x[1], reverse=True)
            top_indices = [idx for idx, _ in indexed[:top_k]]
        
            if top_indices:
                logger.debug(f"检索到 {len(top_indices)} 条相关对话片段，最高分: {indexed[0][1] if indexed else 0}")
                return [self._chat_documents[i]["text"] for i in top_indices]
            else:
                logger.debug("未检索到相关对话片段")
                return []
        except Exception as e:
            logger.error(f"聊天记录检索失败: {e}", exc_info=True)
            return []

    def _tokenize(self, text: str) -> List[str]:
        words = list(jieba.cut(text))
        # 过滤停用词（参考 MemoryManager 的 STOPWORDS）
        return [w for w in words if w not in self.STOPWORDS and len(w) > 1]