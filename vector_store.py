"""
vector_store.py — FAISS HNSW 向量索引封装

职责：
- 管理 FAISS IndexHNSWFlat 索引的加载/保存/增/查
- 与 SQLite 解耦：本模块不感知 chunk 文本，只处理 (id, vector) 对
- 索引文件持久化到 ~/.workbuddy/faiss.index
"""

import os
import json
import threading
import numpy as np

# 索引文件路径
_INDEX_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy")
_INDEX_PATH = os.path.join(_INDEX_DIR, "faiss.index")
_ID_MAP_PATH = os.path.join(_INDEX_DIR, "faiss_id_map.json")

# HNSW 参数（针对个人知识库规模优化）
_DIMENSION = 512         # bge-small-zh-v1.5 输出维度
_M = 16                  # 每节点最大连接数（16 对万级数据足够，内存友好）
_EF_CONSTRUCTION = 100   # 构建时搜索宽度（100 在精度和构建速度间平衡）
_EF_SEARCH = 64          # 查询时搜索宽度（64 在万级数据上 < 5ms）


class VectorStore:
    """FAISS HNSW 向量索引的线程安全封装"""

    def __init__(self):
        self._index = None
        self._id_map = []          # FAISS 内部下标 → chunk_id (int)
        self._id_to_internal = {}  # chunk_id → FAISS 内部下标（反向映射）
        self._lock = threading.RLock()
        self._loaded = False
        self._fallback_mode = False  # FAISS 不可用时降级标记

    def load(self):
        """从磁盘加载索引。文件不存在则创建空索引。FAISS 不可用时降级。"""
        try:
            import faiss
        except ImportError:
            print("[VectorStore] faiss-cpu 未安装，使用暴力扫描降级模式")
            self._loaded = True
            self._fallback_mode = True
            return

        with self._lock:
            if os.path.exists(_INDEX_PATH) and os.path.exists(_ID_MAP_PATH):
                self._index = faiss.read_index(_INDEX_PATH)
                with open(_ID_MAP_PATH, "r") as f:
                    self._id_map = json.load(f)
                self._id_to_internal = {cid: i for i, cid in enumerate(self._id_map)}
                print(f"[VectorStore] 已加载 FAISS 索引: {self._index.ntotal} 条向量")
            else:
                self._index = faiss.IndexHNSWFlat(_DIMENSION, _M)
                self._index.hnsw.efConstruction = _EF_CONSTRUCTION
                self._index.hnsw.efSearch = _EF_SEARCH
                self._id_map = []
                self._id_to_internal = {}
                print("[VectorStore] 创建新的空 FAISS HNSW 索引")
            self._loaded = True
            self._fallback_mode = False

    def save(self):
        """持久化索引和 ID 映射到磁盘"""
        import faiss
        with self._lock:
            if self._index is None or self._fallback_mode:
                return
            os.makedirs(_INDEX_DIR, exist_ok=True)
            faiss.write_index(self._index, _INDEX_PATH)
            with open(_ID_MAP_PATH, "w") as f:
                json.dump(self._id_map, f)

    def add(self, chunk_ids: list, vectors: np.ndarray):
        """
        批量添加向量到索引。

        参数:
            chunk_ids: chunk 的数据库 row id 列表
            vectors: shape=(N, 512) 的 float32 numpy 数组，必须 L2 归一化
        """
        with self._lock:
            if self._fallback_mode:
                return
            if self._index is None:
                self.load()
            vectors = np.ascontiguousarray(vectors, dtype=np.float32)
            self._index.add(vectors)
            start_id = len(self._id_map)
            for i, cid in enumerate(chunk_ids):
                self._id_map.append(cid)
                self._id_to_internal[cid] = start_id + i

    def search(self, query_vector: np.ndarray, top_k: int = 20) -> list:
        """
        FAISS ANN 检索。

        返回:
            list of (chunk_id, similarity_score) 元组，按相似度降序
        """
        with self._lock:
            if self._fallback_mode or self._index is None or self._index.ntotal == 0:
                return []

            query = np.array([query_vector], dtype=np.float32)
            # HNSW 返回 L2 距离，归一化向量转余弦相似度：sim = 1 - d²/2
            distances, indices = self._index.search(query, min(top_k, self._index.ntotal))

            results = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx < 0 or idx >= len(self._id_map):
                    continue
                chunk_id = self._id_map[idx]
                similarity = 1.0 - dist / 2.0
                results.append((chunk_id, float(similarity)))
            return results

    def remove_by_chunk_ids(self, chunk_ids: list):
        """
        标记删除指定 chunk 的向量。
        HNSW 不支持高效单条删除，采用标记 + 延迟重建策略。
        """
        with self._lock:
            if self._fallback_mode:
                return 0
            removed = 0
            new_id_map = []
            for cid in self._id_map:
                if cid in chunk_ids:
                    removed += 1
                else:
                    new_id_map.append(cid)
            self._id_map = new_id_map
            self._id_to_internal = {cid: i for i, cid in enumerate(self._id_map)}
            return removed

    def rebuild_index(self, all_vectors: np.ndarray, all_chunk_ids: list):
        """完全重建索引，清除删除产生的僵尸向量"""
        import faiss
        with self._lock:
            if self._fallback_mode:
                return
            self._index = faiss.IndexHNSWFlat(_DIMENSION, _M)
            self._index.hnsw.efConstruction = _EF_CONSTRUCTION
            self._index.hnsw.efSearch = _EF_SEARCH
            all_vectors = np.ascontiguousarray(all_vectors, dtype=np.float32)
            self._index.add(all_vectors)
            self._id_map = list(all_chunk_ids)
            self._id_to_internal = {cid: i for i, cid in enumerate(self._id_map)}

    @property
    def total_vectors(self) -> int:
        if self._index is None:
            return 0
        return self._index.ntotal

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_fallback(self) -> bool:
        return self._fallback_mode


# 全局单例
_vector_store = VectorStore()


def get_vector_store() -> VectorStore:
    return _vector_store


def init_vector_store():
    """应用启动时调用，加载 FAISS 索引"""
    _vector_store.load()
