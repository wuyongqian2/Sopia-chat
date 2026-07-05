"""
FAISS HNSW 向量索引 + RRF 融合排序单元测试

测试覆盖：
- VectorStore 基本操作（创建、添加、检索、降级）
- RRF 融合排序逻辑（单路、双路、互补场景）
"""

import pytest
import os
import sys
import numpy as np

# 让测试能 import 项目根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestVectorStore:
    """FAISS HNSW 向量索引单元测试"""

    def test_create_empty_index(self):
        """空索引初始化后向量数为 0"""
        from vector_store import VectorStore
        vs = VectorStore()
        vs._fallback_mode = False
        vs._loaded = True
        # 模拟空索引（不实际创建 FAISS 索引，只测逻辑）
        vs._index = None
        assert vs.total_vectors == 0

    def test_add_and_search(self):
        """添加向量后能检索到最近邻"""
        try:
            import faiss
        except ImportError:
            pytest.skip("faiss-cpu 未安装")

        from vector_store import VectorStore
        vs = VectorStore()
        vs.load()

        # 创建 3 个正交向量
        vectors = np.array([
            [1.0, 0.0, 0.0] + [0.0] * 509,
            [0.0, 1.0, 0.0] + [0.0] * 509,
            [0.0, 0.0, 1.0] + [0.0] * 509,
        ], dtype=np.float32)
        vs.add([100, 200, 300], vectors)

        # 查询一个接近第一个向量的向量
        query = np.array([0.9, 0.1, 0.0] + [0.0] * 509, dtype=np.float32)
        results = vs.search(query, top_k=1)
        assert len(results) == 1
        assert results[0][0] == 100  # 应该找到 chunk_id=100

    def test_fallback_without_faiss(self):
        """FAISS 不可用时降级不崩溃"""
        from vector_store import VectorStore
        vs = VectorStore()
        vs._fallback_mode = True
        vs._loaded = True
        results = vs.search(np.zeros(512, dtype=np.float32), top_k=5)
        assert results == []

    def test_remove_by_chunk_ids(self):
        """删除指定 chunk 后，id_map 正确缩减"""
        try:
            import faiss
        except ImportError:
            pytest.skip("faiss-cpu 未安装")

        from vector_store import VectorStore
        vs = VectorStore()
        vs.load()

        vectors = np.array([
            [1.0, 0.0, 0.0] + [0.0] * 509,
            [0.0, 1.0, 0.0] + [0.0] * 509,
            [0.0, 0.0, 1.0] + [0.0] * 509,
        ], dtype=np.float32)
        vs.add([100, 200, 300], vectors)

        removed = vs.remove_by_chunk_ids([200])
        assert removed == 1
        assert 200 not in vs._id_map
        assert 100 in vs._id_map
        assert 300 in vs._id_map


class TestRRFFusion:
    """RRF 融合排序测试"""

    @pytest.fixture(scope="class")
    def test_db(self, tmp_path_factory):
        """创建临时数据库用于 RRF 测试"""
        import database as db_module

        tmp_db_dir = tmp_path_factory.mktemp("test_rrf")
        tmp_db_path = os.path.join(str(tmp_db_dir), "test_rrf.db")

        original_db_dir = db_module.DB_DIR
        original_db_path = db_module.DB_PATH

        db_module.DB_DIR = str(tmp_db_dir)
        db_module.DB_PATH = tmp_db_path
        db_module.init_db()

        # 创建测试用户和文档
        conn = db_module.get_db()
        conn.execute(
            """INSERT OR IGNORE INTO users (id, username, password_hash)
               VALUES (1, 'testuser', 'testhash')"""
        )
        conn.execute(
            """INSERT INTO documents (id, user_id, filename, chunk_count)
               VALUES ('test-doc-1', 1, 'test.md', 3)"""
        )
        conn.commit()
        conn.close()

        yield db_module

        db_module.DB_DIR = original_db_dir
        db_module.DB_PATH = original_db_path

    def test_rrf_both_paths_agree(self, test_db):
        """两路检索结果一致时，RRF 保持排序"""
        # 先插入测试数据
        conn = test_db.get_db()
        for i, (chunk_id, text) in enumerate([
            (1, "Python Flask 框架"),
            (2, "JavaScript React"),
            (3, "Java Spring"),
        ]):
            conn.execute(
                """INSERT OR IGNORE INTO document_chunks
                   (id, document_id, chunk_index, text, heading, hierarchy_json)
                   VALUES (?, 'test-doc-1', ?, ?, '', '[]')""",
                (chunk_id, i, text)
            )
        conn.commit()
        conn.close()

        faiss = {1: 0.9, 2: 0.8, 3: 0.7}
        fts = {1: 10.0, 2: 8.0, 3: 6.0}
        results = test_db._rrf_fusion(faiss, fts, None, top_k=3)
        assert len(results) == 3
        # chunk_id=1 在两路都排第一，RRF 分数最高
        assert results[0]["id"] == 1

    def test_rrf_one_path_only(self, test_db):
        """只有一路有结果时，RRF 退化为单路排序"""
        faiss = {1: 0.9, 2: 0.8}
        fts = {}
        results = test_db._rrf_fusion(faiss, fts, None, top_k=2)
        assert len(results) == 2
        assert results[0]["id"] == 1

    def test_rrf_complementary(self, test_db):
        """两路结果互补时，RRF 能提升只在一路出现的候选"""
        # 确保 chunk 3 在数据库中存在
        conn = test_db.get_db()
        conn.execute(
            """INSERT OR IGNORE INTO document_chunks
               (id, document_id, chunk_index, text, heading, hierarchy_json)
               VALUES (3, 'test-doc-1', 2, 'Java Spring', '', '[]')"""
        )
        conn.commit()
        conn.close()

        faiss = {1: 0.9, 2: 0.8}
        fts = {3: 10.0, 1: 5.0}
        results = test_db._rrf_fusion(faiss, fts, None, top_k=3)
        ids = [r["id"] for r in results]
        # chunk 1 在两路都出现，应排第一
        assert ids[0] == 1
        assert len(results) == 3


class TestFTS5Query:
    """FTS5 查询语法转换测试"""

    def test_chinese_text(self):
        """中文文本能正确提取关键词"""
        from database import _text_to_fts5_query
        result = _text_to_fts5_query("如何配置 Flask API Key")
        assert "Flask" in result
        assert "API" in result

    def test_empty_text(self):
        """空文本返回空字符串"""
        from database import _text_to_fts5_query
        assert _text_to_fts5_query("") == ""
        assert _text_to_fts5_query("   ") == ""

    def test_punctuation_filtered(self):
        """标点符号被过滤"""
        from database import _text_to_fts5_query
        result = _text_to_fts5_query("你好，世界！")
        # 应该只包含中文字符，不含标点
        assert "，" not in result
        assert "！" not in result
