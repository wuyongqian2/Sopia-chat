"""
分层响应缓存管理器
L1: 精确匹配缓存（内存 dict，零额外成本）
L2: 语义相似度缓存（Embedding 向量 + 余弦相似度）

用于减少重复 LLM 调用，节省 Token 消耗和响应延迟。
"""

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict

# ============================================================
# 配置
# ============================================================

# L1 精确匹配缓存
_L1_MAX_SIZE = 500          # 最大条目数
_L1_TTL = 7200              # 存活时间：2小时（秒）

# L2 语义缓存
_L2_MAX_SIZE = 2000         # 最大条目数
_L2_TTL = 86400             # 存活时间：24小时（秒）
_L2_SIMILARITY_THRESHOLD = 0.93  # 相似度阈值（0.93-0.97 推荐）

# 本地 Embedding 模型配置
_LOCAL_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"  # 中文优化模型，~90MB
_EMBEDDING_DIMENSION = 512  # bge-small-zh-v1.5 维度

# 持久化路径
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy")
L2_CACHE_FILE = os.path.join(CACHE_DIR, "semantic_cache.json")


# ============================================================
# L1: 精确匹配缓存
# ============================================================

class ExactCache:
    """基于哈希的精确匹配缓存，零额外成本"""

    def __init__(self, max_size=_L1_MAX_SIZE, ttl=_L1_TTL):
        self._cache = OrderedDict()  # key → {"response": str, "ts": float, "hits": int}
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.RLock()
        self._stats = {"hits": 0, "misses": 0}

    @staticmethod
    def _make_key(question: str, model: str, provider: str) -> str:
        """生成缓存 Key：model + provider + question 的哈希"""
        raw = f"{provider}:{model}:{question.strip().lower()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get(self, question: str, model: str, provider: str):
        """查询缓存，命中返回响应字符串，未命中返回 None"""
        key = self._make_key(question, model, provider)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None
            # 检查 TTL
            if time.monotonic() > entry["expire_at"]:
                self._cache.pop(key, None)
                self._stats["misses"] += 1
                return None
            # LRU：移到末尾
            self._cache.move_to_end(key)
            entry["hits"] += 1
            self._stats["hits"] += 1
            return entry["response"]

    def put(self, question: str, model: str, provider: str, response: str):
        """写入缓存"""
        key = self._make_key(question, model, provider)
        with self._lock:
            # 若已存在，先移除
            self._cache.pop(key, None)
            self._cache[key] = {
                "response": response,
                "expire_at": time.monotonic() + self._ttl,
                "hits": 0,
                "created_at": time.time()
            }
            # LRU 淘汰
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._stats = {"hits": 0, "misses": 0}

    def stats(self):
        """返回统计信息"""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total if total > 0 else 0
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": round(hit_rate, 3)
            }


# ============================================================
# L2: 语义相似度缓存
# ============================================================

class SemanticCache:
    """基于 Embedding 向量余弦相似度的语义缓存"""

    def __init__(self, max_size=_L2_MAX_SIZE, ttl=_L2_TTL, threshold=_L2_SIMILARITY_THRESHOLD):
        self._cache = OrderedDict()  # key → {"vector": list, "response": str, "question": str, ...}
        self._max_size = max_size
        self._ttl = ttl
        self._threshold = threshold
        self._lock = threading.RLock()
        self._stats = {"hits": 0, "misses": 0, "total_searches": 0}

    @staticmethod
    def _cosine_similarity(vec_a: list, vec_b: list) -> float:
        """计算两个向量的余弦相似度"""
        import math
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    def get(self, query_vector: list, model: str, provider: str):
        """
        查询语义缓存（numpy 向量化批量计算余弦相似度，O(n) for 循环 → 0.5ms）。
        返回 (response, similarity) 或 (None, 0)
        """
        import numpy as np

        if not query_vector:
            return None, 0

        with self._lock:
            self._stats["total_searches"] += 1
            now = time.monotonic()
            valid_keys, vectors = [], []

            for key, entry in self._cache.items():
                if now > entry["expire_at"]:
                    self._cache.pop(key, None)
                    continue
                if entry.get("model") != model or entry.get("provider") != provider:
                    continue
                valid_keys.append(key)
                vectors.append(entry["vector"])

            if not vectors:
                self._stats["misses"] += 1
                return None, 0

            q = np.array(query_vector, dtype=np.float32)
            q_norm = np.linalg.norm(q)
            if q_norm == 0:
                self._stats["misses"] += 1
                return None, 0

            matrix = np.array(vectors, dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1)
            norms = np.where(norms == 0, 1, norms)
            sims = (matrix @ q) / (norms * q_norm)

            best_idx = int(np.argmax(sims))
            if float(sims[best_idx]) >= self._threshold:
                key = valid_keys[best_idx]
                self._cache.move_to_end(key)
                self._stats["hits"] += 1
                return self._cache[key]["response"], float(sims[best_idx])

            self._stats["misses"] += 1
            return None, float(sims[best_idx])

    def put(self, query_vector: list, question: str, model: str, provider: str, response: str):
        """写入语义缓存"""
        if not query_vector:
            return

        key = hashlib.md5(f"{provider}:{model}:{question}".encode()).hexdigest()
        with self._lock:
            self._cache.pop(key, None)
            self._cache[key] = {
                "vector": query_vector,
                "response": response,
                "question": question,
                "model": model,
                "provider": provider,
                "expire_at": time.monotonic() + self._ttl,
                "created_at": time.time()
            }
            # LRU 淘汰
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._stats = {"hits": 0, "misses": 0, "total_searches": 0}

    def stats(self):
        """返回统计信息"""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total if total > 0 else 0
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "threshold": self._threshold,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": round(hit_rate, 3)
            }


# ============================================================
# 本地 Embedding 模型管理器
# ============================================================


class LocalEmbeddingModel:
    '''Local embedding using onnxruntime + tokenizers (replaces sentence-transformers).'''
    
    def __init__(self, model_dir: str = None):
        if model_dir is None:
            # Look for model in project models/ dir, then ~/.workbuddy/models/
            project_models = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
            user_models = os.path.join(os.path.expanduser('~'), '.workbuddy', 'models')
            if os.path.isdir(project_models) and any(f.endswith('.onnx') for f in os.listdir(project_models)):
                model_dir = project_models
            elif os.path.isdir(user_models) and any(f.endswith('.onnx') for f in os.listdir(user_models)):
                model_dir = user_models
            else:
                model_dir = user_models  # default download location
        self._model_dir = model_dir
        self._session = None
        self._tokenizer = None
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._loading = False
        self._loaded = False
        self._load_error = None
    
    def _load_model_async(self):
        '''Load ONNX model and tokenizer in background thread.'''
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
            
            onnx_path = None
            tokenizer_path = None
            for f in os.listdir(self._model_dir):
                if f.endswith('.onnx'):
                    onnx_path = os.path.join(self._model_dir, f)
                if f == 'tokenizer.json':
                    tokenizer_path = os.path.join(self._model_dir, f)
            
            if not onnx_path:
                raise FileNotFoundError('No .onnx file found in ' + self._model_dir)
            if not tokenizer_path:
                raise FileNotFoundError('No tokenizer.json found in ' + self._model_dir)
            
            print(f'[Cache] Loading ONNX embedding model from {self._model_dir}')
            start_time = time.time()
            
            # Load tokenizer
            tok = Tokenizer.from_file(tokenizer_path)
            tok.enable_truncation(max_length=512)
            tok.enable_padding(length=512)
            
            # Load ONNX model
            sess_opts = ort.SessionOptions()
            sess_opts.inter_op_num_threads = 2
            sess_opts.intra_op_num_threads = 2
            session = ort.InferenceSession(onnx_path, sess_opts, providers=['CPUExecutionProvider'])
            
            with self._lock:
                self._tokenizer = tok
                self._session = session
                self._loaded = True
                self._loading = False
            
            load_time = time.time() - start_time
            print(f'[Cache] ONNX embedding model loaded in {load_time:.2f}s')
            self._ready.set()
            
        except Exception as e:
            with self._lock:
                self._load_error = str(e)
                self._loading = False
            self._ready.set()
            print(f'[Cache] ONNX embedding model load failed: {e}')
    
    def _ensure_loading(self):
        '''Ensure model loading has started (non-blocking).'''
        with self._lock:
            if not self._loaded and not self._loading:
                self._loading = True
                thread = threading.Thread(target=self._load_model_async, daemon=True)
                thread.start()
    
    def encode(self, text: str, timeout: float = 10.0) -> list:
        '''Encode text to embedding vector.'''
        if not text or not text.strip():
            return []
        self._ensure_loading()
        if self._loaded and self._session is not None:
            return self._run_inference_long(text[:8000])
        if self._loading:
            self._ready.wait(timeout=timeout)
            if self._loaded and self._session is not None:
                return self._run_inference_long(text[:8000])
        return []
    
    def _run_inference(self, text: str) -> list:
        '''Run ONNX inference for a single text.'''
        try:
            import numpy as np
            encoding = self._tokenizer.encode(text)
            input_ids = np.array([encoding.ids], dtype=np.int64)
            attention_mask = np.array([encoding.attention_mask], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids)
            
            inputs = {
                'input_ids': input_ids,
                'attention_mask': attention_mask,
                'token_type_ids': token_type_ids,
            }
            outputs = self._session.run(None, inputs)
            # Take [CLS] token embedding (first token) and L2-normalize
            cls_emb = outputs[0][0][0]  # (batch=0, seq=0, hidden)
            norm = np.linalg.norm(cls_emb)
            if norm > 0:
                cls_emb = cls_emb / norm
            return cls_emb.tolist()
        except Exception as e:
            print(f'[Cache] ONNX inference failed: {e}')
            return []
    
    def _run_inference_long(self, text: str) -> list:
        '''
        对长文本采用滑动窗口编码 + 均值池化。
        将文本按 1800 字符切分（留 200 字符重叠），分别编码后取均值。
        '''
        import numpy as np

        MAX_LEN = 2000
        OVERLAP = 200
        STEP = MAX_LEN - OVERLAP  # 1800

        if len(text) <= MAX_LEN:
            return self._run_inference(text)

        segments = []
        start = 0
        while start < len(text):
            end = min(start + MAX_LEN, len(text))
            segments.append(text[start:end])
            if end >= len(text):
                break
            start += STEP

        vectors = []
        for seg in segments:
            vec = self._run_inference(seg)
            if vec:
                vectors.append(np.array(vec, dtype=np.float32))

        if not vectors:
            return []

        mean_vec = np.mean(vectors, axis=0)
        norm = np.linalg.norm(mean_vec)
        if norm > 0:
            mean_vec = mean_vec / norm
        return mean_vec.tolist()
    
    def encode_batch(self, texts: list, batch_size: int = 32) -> list:
        '''Batch encode multiple texts.'''
        if not texts:
            return []
        self._ensure_loading()
        if not self._loaded or self._session is None:
            return [[] for _ in texts]
        try:
            import numpy as np
            results = []
            truncated = [t[:8000] if t else '' for t in texts]
            for i in range(0, len(truncated), batch_size):
                batch = truncated[i:i+batch_size]
                encodings = [self._tokenizer.encode(t) for t in batch]
                input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
                attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
                token_type_ids = np.zeros_like(input_ids)
                inputs = {
                    'input_ids': input_ids,
                    'attention_mask': attention_mask,
                    'token_type_ids': token_type_ids,
                }
                outputs = self._session.run(None, inputs)
                cls_embs = outputs[0][:, 0, :]  # [CLS] for each item
                norms = np.linalg.norm(cls_embs, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1, norms)
                cls_embs = cls_embs / norms
                results.extend(cls_embs.tolist())
            # 对长文本使用滑动窗口均值池化（单条处理）
            final_results = []
            for i, text in enumerate(truncated):
                if len(text) > 2000 and i < len(results):
                    long_vec = self._run_inference_long(text)
                    if long_vec:
                        final_results.append(long_vec)
                    else:
                        final_results.append(results[i])
                else:
                    final_results.append(results[i] if i < len(results) else [])
            return final_results
        except Exception as e:
            print(f'[Cache] Batch ONNX inference failed: {e}')
            return [[] for _ in texts]

    def get_status(self) -> dict:
        """获取模型状态信息"""
        with self._lock:
            return {
                "model_dir": self._model_dir,
                "loaded": self._loaded,
                "loading": self._loading,
                "error": self._load_error,
                "model_name": _LOCAL_EMBEDDING_MODEL,
                "dimension": _EMBEDDING_DIMENSION
            }


# ============================================================
# 全局 Embedding 模型实例
# ============================================================
_local_embedding_model = LocalEmbeddingModel()


def warmup_embedding_model():
    """后台预热 Embedding 模型（在应用启动时调用）"""
    # 直接触发异步加载，立即返回
    _local_embedding_model._ensure_loading()


def get_embedding(text: str, **kwargs) -> list:
    """
    获取文本的 Embedding 向量（使用本地模型）。
    
    参数:
        text: 要编码的文本
        **kwargs: 保留参数，用于向后兼容（provider_key, api_key 等会被忽略）
    
    返回:
        list: Embedding 向量（512维），失败返回空列表
    """
    if not text or not text.strip():
        return []
    
    # 使用本地模型
    vector = _local_embedding_model.encode(text.strip())
    
    # 验证向量维度
    if vector and len(vector) != _EMBEDDING_DIMENSION:
        print(f"[Cache] 警告：向量维度不匹配，期望 {_EMBEDDING_DIMENSION}，实际 {len(vector)}")
        return []
    
    return vector


def get_embeddings_batch(texts: list, batch_size: int = 32) -> list:
    """
    批量获取文本的 Embedding 向量（使用本地模型）。
    内部调用 ONNX model batch inference 的批量推理，大幅优于逐条编码。

    参数:
        texts: 文本列表
        batch_size: 每批处理的数量，默认 32

    返回:
        list[list[float]]: 每个文本对应的向量列表，失败项返回空列表
    """
    if not texts:
        return []
    return _local_embedding_model.encode_batch(texts, batch_size)


def get_embedding_status() -> dict:
    """获取 Embedding 模型状态"""
    return _local_embedding_model.get_status()


# ============================================================
# 全局缓存实例
# ============================================================

_exact_cache = ExactCache()
_semantic_cache = SemanticCache()


def get_exact_cache() -> ExactCache:
    return _exact_cache


def get_semantic_cache() -> SemanticCache:
    return _semantic_cache


def cache_stats() -> dict:
    """返回缓存整体统计"""
    return {
        "l1_exact": _exact_cache.stats(),
        "l2_semantic": _semantic_cache.stats(),
        "embedding_model": get_embedding_status()
    }


def clear_all_caches():
    """清空所有缓存"""
    _exact_cache.clear()
    _semantic_cache.clear()
