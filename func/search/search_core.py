# 搜索功能
import os
import json
import re
import jieba
import jieba.analyse
import jieba.posseg as pseg
from datetime import datetime
from func.config.default_config import defaultConfig
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.gobal.data import SearchData
from func.gobal.data import LLmData
from func.search.baidu_websearch import BaiduWebsearch
from func.tools.string_util import StringUtil
from func.tts.tts_core import TTsCore
from func.llm.llm_core import LLmCore

# 尝试导入语义搜索依赖
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    import faiss
    SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False

class SemanticSearch:
    """基于向量的语义检索器"""
    def __init__(self, model_name, use_gpu=False, top_k=3):
        self.model = SentenceTransformer(model_name)
        if use_gpu:
            self.model = self.model.to('cuda')
        self.top_k = top_k
        self.index = None
        self.metadata = []  # 每个向量对应的 (文件路径, 关键词)
        self.dimension = self.model.get_sentence_embedding_dimension()

    def encode(self, texts):
        return self.model.encode(texts, normalize_embeddings=True)

    def build_index(self, file_texts, file_paths, keywords):
        """构建 FAISS 索引（内积，假设向量已归一化）"""
        if not file_texts:
            return
        embeddings = self.encode(file_texts)
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings.astype('float32'))
        self.metadata = list(zip(file_paths, keywords))

    def search(self, query, threshold=None):
        if self.index is None or self.index.ntotal == 0:
            return []
        query_vec = self.encode([query])
        scores, indices = self.index.search(query_vec.astype('float32'), min(self.top_k, self.index.ntotal))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            if threshold is not None and score < threshold:
                continue
            file_path, keyword = self.metadata[idx]
            results.append({
                'score': float(score),
                'file_path': file_path,
                'keyword': keyword
            })
        return results


@singleton
class SearchCore:
    log = DefaultLog().getLogger()
    config = defaultConfig().get_config()
    searchData = SearchData()
    llmData = LLmData()
    baiduWebsearch = BaiduWebsearch()

    def __init__(self):
        # 加载搜索配置
        search_cfg = self.config.get('searchWeb', {})
        self.triggers = search_cfg.get('triggers', ["查询", "查一下", "搜索"])
        self.max_results = search_cfg.get('max_results', 3)
        self.cache_dir = search_cfg.get('cache_dir', 'searchresult')
        self.use_keyword_extract = search_cfg.get('use_keyword_extract', True)
        self.use_llm_extract = search_cfg.get('use_llm_extract', False)  # 新增：是否用大模型提取关键词

        # 知识库匹配控制（原有）
        self.cache_match_mode = search_cfg.get('cache_match_mode', 'tag')
        self.cache_match_min_len = search_cfg.get('cache_match_min_len', 2)
        self.cache_match_max_items = search_cfg.get('cache_match_max_items', 3)

        # 语义搜索配置
        semantic_cfg = search_cfg.get('semantic_search', {})
        self.semantic_enabled = semantic_cfg.get('enabled', False) and SEMANTIC_AVAILABLE
        self.semantic_model_name = semantic_cfg.get('model_name', 'BAAI/bge-small-zh-v1.5')
        self.semantic_top_k = semantic_cfg.get('top_k', 3)
        self.semantic_use_gpu = semantic_cfg.get('use_gpu', False)
        self.semantic_threshold = semantic_cfg.get('threshold', 0.6)  # 相似度阈值
        self.semantic_update_index_on_start = semantic_cfg.get('update_index_on_start', True)

        self.semantic_search = None
        if self.semantic_enabled:
            self._init_semantic_search()

        self._ensure_cache_dir()

        # 停用词表
        self.stopwords = set(['的', '了', '是', '在', '和', '与', '这', '那', '你', '我', '他'])

        # 延迟初始化 LLM 客户端（避免循环依赖）
        self._llm_client = None

    def _ensure_cache_dir(self):
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
            self.log.info(f"创建搜索缓存目录: {self.cache_dir}")

    def _init_semantic_search(self):
        """初始化语义搜索：加载模型并构建索引"""
        self.log.info("初始化语义搜索，加载模型...")
        self.semantic_search = SemanticSearch(
            model_name=self.semantic_model_name,
            use_gpu=self.semantic_use_gpu,
            top_k=self.semantic_top_k
        )
        self._rebuild_semantic_index()

    def _rebuild_semantic_index(self):
        """扫描缓存目录，重建语义索引"""
        if not self.semantic_enabled or not self.semantic_search:
            return
        self.log.info("重建语义索引...")
        file_texts = []
        file_paths = []
        keywords = []
        if not os.path.exists(self.cache_dir):
            return
        for fname in os.listdir(self.cache_dir):
            if fname.endswith('.json'):
                filepath = os.path.join(self.cache_dir, fname)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    keyword = data.get('keyword', '')
                    results = data.get('results', [])
                    # 构造文本：关键词 + 所有结果的标题和摘要
                    content_parts = [keyword]
                    for res in results:
                        title = res.get('title', '')
                        abstract = res.get('abstract', '')
                        if title:
                            content_parts.append(title)
                        if abstract:
                            content_parts.append(abstract)
                    text = ' '.join(content_parts)
                    if text.strip():
                        file_texts.append(text)
                        file_paths.append(filepath)
                        keywords.append(keyword)
                except Exception as e:
                    self.log.error(f"读取缓存文件 {filepath} 失败: {e}")
        if file_texts:
            self.semantic_search.build_index(file_texts, file_paths, keywords)
            self.log.info(f"语义索引重建完成，共 {len(file_texts)} 条记录")
        else:
            self.semantic_search.index = None
            self.semantic_search.metadata = []
            self.log.info("缓存目录为空，语义索引已清空")

    # ================= 原有规则提取关键词 =================
    def _extract_keywords(self, text: str) -> str:
        """
        从用户消息中提取搜索关键词。
        策略：找到第一个触发词的位置，根据位置取前面的或后面的内容，
        然后去除标点符号和常见语气词，返回尽可能长的字符串。
        """
        text = text.strip()
        # 找到第一个触发词的位置
        first_trigger = None
        first_pos = len(text)
        for trigger in self.triggers:
            pos = text.find(trigger)
            if pos != -1 and pos < first_pos:
                first_pos = pos
                first_trigger = trigger
        if first_trigger is None:
            return ""

        # 提取候选文本
        if first_pos <= len(text) / 2:
            # 触发词在前半部分：取后面内容
            candidate = text[first_pos + len(first_trigger):].strip()
        else:
            # 触发词在后半部分：取前面内容
            candidate = text[:first_pos].strip()

        if not candidate:
            candidate = first_trigger

        # 去除标点符号（保留中文、字母、数字、空格）
        candidate = re.sub(r'[^\w\u4e00-\u9fff\s]', '', candidate)
        # 移除常见语气词（可根据需要扩展）
        useless_words = ['吗', '呢', '吧', '啊', '哦', '啦', '呀', '的', '了', '么', '嘛']
        for w in useless_words:
            candidate = candidate.replace(w, '')
        # 压缩多余空格
        candidate = re.sub(r'\s+', ' ', candidate).strip()
        # 限制长度（可选）
        if len(candidate) > 100:
            candidate = candidate[:100]
        return candidate
    # ====================================================

    # ================= 新增：用大模型提取关键词 =================
    def _get_llm_client(self):
        """根据配置获取 LLM 客户端实例（仅用于关键词提取）"""
        if self._llm_client is not None:
            return self._llm_client

        # 从全局数据中获取当前使用的 LLM 类型
        local_llm_type = self.llmData.local_llm_type

        if local_llm_type == "ollama":
            from func.llm.port.ollama import Ollama
            self._llm_client = Ollama()
        elif local_llm_type == "aliyun":
            from func.llm.port.aliyun_stream import AliyunStreamLLM
            self._llm_client = AliyunStreamLLM()
        elif local_llm_type == "deepseek":
            from func.llm.port.deepseek import DeepSeekLLM
            self._llm_client = DeepSeekLLM()
        elif local_llm_type == "bigmodel":
            from func.llm.port.bigmodel import BigModel
            self._llm_client = BigModel()
        else:
            self._llm_client = None
        return self._llm_client

    def _extract_keywords_with_llm(self, text: str, traceid: str = "") -> str:
        """使用本地 LLM 提取搜索关键词，如果失败则回退到规则提取"""
        llm = self._get_llm_client()
        if llm is None:
            self.log.info(f"[{traceid}] 无法使用 LLM 提取关键词，回退规则")
            return self._extract_keywords(text)

        # 构造提示词，要求只输出关键词
        prompt = f"请从以下用户消息中提取要搜索的核心关键词，只输出关键词本身，不要任何额外说明：\n{text}"
        messages = [{"role": "user", "content": prompt}]

        try:
            local_llm_type = self.llmData.local_llm_type
            if local_llm_type == "ollama":
                # 强制禁用思考：在系统消息前插入 /no_think 指令
                # 如果 messages 中没有 system 角色，插入一个临时的系统消息
                if not any(msg.get('role') == 'system' for msg in messages):
                    messages.insert(0, {"role": "system", "content": "/no_think\n"})
                else:
                    # 在第一个 system 消息前插入
                    for i, msg in enumerate(messages):
                        if msg.get('role') == 'system':
                            original = msg.get('content', '')
                            messages[i]['content'] = "/no_think\n" + original
                            break
                # Ollama 非流式调用
                response = llm.generate(messages)
            elif local_llm_type == "aliyun":
                # Aliyun 强制禁用思考
                options = {
                    "temperature": 0.1,
                    "max_tokens": 50,
                    "enable_thinking": False
                }
                response = ""
                for chunk in llm.generate_stream(messages, options=options):
                    response += chunk
                response = response.strip()
            elif local_llm_type in ("deepseek", "bigmodel"):
                # DeepSeek 和智谱都支持非流式 generate，且无 thinking 模式
                # 设置极低的 temperature 保证确定性
                options = {"temperature": 0.1, "max_tokens": 50}
                response = llm.generate(messages, options=options)
            else:
                return self._extract_keywords(text)

            keyword = response.strip().strip('"').strip("'")
            # 额外清理可能残留的 think 标签（保险）
            import re
            keyword = re.sub(r'<think>.*?</think>', '', keyword, flags=re.DOTALL).strip()
            if len(keyword) > 100:
                keyword = keyword[:100]
            self.log.info(f"[{traceid}] LLM 提取关键词: {keyword}")
            return keyword
        except Exception as e:
            self.log.error(f"[{traceid}] LLM 提取关键词失败: {e}，回退规则提取")
            return self._extract_keywords(text)

    def _extract_cache_candidates(self, text: str) -> list:
        """根据配置提取用于匹配知识库的候选词列表"""
        if self.cache_match_mode == 'tag':
            tags = jieba.analyse.extract_tags(text, topK=self.cache_match_max_items, withWeight=False)
            tags = [t for t in tags if len(t) >= self.cache_match_min_len]
            return tags
        else:
            words = pseg.cut(text)
            nouns = []
            for word, flag in words:
                if flag.startswith('n') and word not in self.stopwords and len(word) >= self.cache_match_min_len:
                    nouns.append(word)
            nouns = list(dict.fromkeys(nouns))
            nouns.sort(key=len, reverse=True)
            return nouns[:self.cache_match_max_items]

    def _get_cache_filepath(self, keyword: str) -> str:
        # 替换空格为下划线，并移除其他非法字符
        safe = re.sub(r'[\\/*?:"<>|\s]', '_', keyword).strip()
        safe = safe[:50]
        return os.path.join(self.cache_dir, f"{safe}.json")

    def _load_cache(self, keyword: str):
        filepath = self._get_cache_filepath(keyword)
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.log.error(f"读取缓存文件失败 {filepath}: {e}")
        return None

    def _save_cache(self, keyword: str, query: str, results: list):
        filepath = self._get_cache_filepath(keyword)
        data = {
            "date": datetime.now().isoformat(),
            "query": query,
            "keyword": keyword,          # 保存原始关键词（可能含空格）
            "results": results[:self.max_results]
        }
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log.info(f"搜索结果已缓存: {filepath}")
            # 新增缓存后重建语义索引
            if self.semantic_enabled:
                self._rebuild_semantic_index()
        except Exception as e:
            self.log.error(f"保存缓存文件失败 {filepath}: {e}")

    def _format_results_for_context(self, results: list) -> str:
        if not results:
            return "没有搜索到相关信息。"
        lines = ["搜索结果："]
        for i, res in enumerate(results[:self.max_results], 1):
            title = res.get('title', '无标题')
            abstract = res.get('abstract', '')
            if len(abstract) > 100:
                abstract = abstract[:100] + '…'
            lines.append(f"{i}. {title}：{abstract}")
        return '\n'.join(lines)

    def _build_search_prompt(self, original_query: str, results: list) -> str:
        context = self._format_results_for_context(results)
        prompt = f"{context}\n\n请根据以上搜索结果，回答用户的问题：{original_query}"
        return prompt

    def check_text_search(self):
        if not self.searchData.SearchTextList.empty() and self.searchData.is_SearchText == 2:
            self.searchData.is_SearchText = 1
            task = self.searchData.SearchTextList.get()
            traceid = task["traceid"]
            uid = task["uid"]
            username = task["username"]
            query = task["prompt"]
            keyword = task.get("keyword", query)

            self.log.info(f"[{traceid}] 开始搜索关键词: {keyword}")
            raw_results = self.baiduWebsearch.search(keyword, num_results=self.max_results)
            results = raw_results if isinstance(raw_results, list) else []

            # 缓存结果
            self._save_cache(keyword, query, results)

            # 构造带上下文的 prompt 并交给 LLM
            new_prompt = self._build_search_prompt(query, results)
            llm_json = {
                "traceid": traceid,
                "prompt": new_prompt,
                "uid": uid,
                "username": username
            }
            self.llmData.QuestionList.put(llm_json)
            self.log.info(f"[{traceid}] 搜索任务完成，已转为 LLM 任务")
            self.searchData.is_SearchText = 2

    def baidu_web_search(self, query):
        results = self.baiduWebsearch.search(query, num_results=self.max_results)
        return results if isinstance(results, list) else []

    def msg_deal(self, traceid, query, uid, user_name):
        # 1. 优先使用语义检索匹配缓存（主动调用）
        if self.semantic_enabled and self.semantic_search and self.semantic_search.index is not None:
            semantic_results = self.semantic_search.search(query, threshold=self.semantic_threshold)
            if semantic_results:
                best = semantic_results[0]  # 取最相似的一个
                filepath = best['file_path']
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        cached_data = json.load(f)
                    self.log.info(f"[{traceid}] 语义检索命中关键词: {best['keyword']}，相似度: {best['score']:.2f}")
                    new_prompt = self._build_search_prompt(query, cached_data.get('results', []))
                    llm_json = {
                        "traceid": traceid,
                        "prompt": new_prompt,
                        "uid": uid,
                        "username": user_name
                    }
                    self.llmData.QuestionList.put(llm_json)
                    return True
                except Exception as e:
                    self.log.error(f"[{traceid}] 读取缓存文件失败: {e}")

        # 2. 检查是否触发搜索（通过触发词）
        if any(trigger in query for trigger in self.triggers):
            # 根据配置决定用哪种方式提取关键词
            if self.use_llm_extract:
                keyword = self._extract_keywords_with_llm(query, traceid)
            else:
                keyword = self._extract_keywords(query)

            if not keyword:
                self.log.info(f"[{traceid}] 未提取到有效关键词，忽略搜索")
                return False

            # 如果有相同关键词的缓存，直接使用（避免重复搜索）
            cached = self._load_cache(keyword)
            if cached:
                self.log.info(f"[{traceid}] 命中关键词 {keyword} 的缓存，直接使用")
                new_prompt = self._build_search_prompt(query, cached.get('results', []))
                llm_json = {
                    "traceid": traceid,
                    "prompt": new_prompt,
                    "uid": uid,
                    "username": user_name
                }
                self.llmData.QuestionList.put(llm_json)
                return True

            # 无缓存，触发新搜索
            TTsCore().tts_say("喵呜去上网学习一下，等一下喵")
            self.log.info(f"[{traceid}] 触发搜索关键词: {keyword}")
            task = {
                "traceid": traceid,
                "prompt": query,
                "keyword": keyword,
                "uid": uid,
                "username": user_name
            }
            self.searchData.SearchTextList.put(task)
            return True

        # 3. 传统知识库匹配（TF-IDF/名词）作为兜底
        if self.use_keyword_extract:
            candidates = self._extract_cache_candidates(query)
            for cand in candidates:
                cached = self._load_cache(cand)
                if cached:
                    self.log.info(f"[{traceid}] 传统匹配命中关键词: {cand}")
                    new_prompt = self._build_search_prompt(query, cached.get('results', []))
                    llm_json = {
                        "traceid": traceid,
                        "prompt": new_prompt,
                        "uid": uid,
                        "username": user_name
                    }
                    self.llmData.QuestionList.put(llm_json)
                    return True

        # 未处理，交给普通 LLM 流程
        return False