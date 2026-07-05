"""
数据库模块 — SQLite 持久化存储
用户、会话、消息、知识库文档的 CRUD 操作
"""

import sqlite3
import os
import uuid
from datetime import datetime

# ============================================================
# 数据库路径
# ============================================================

DB_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy")
DB_PATH = os.path.join(DB_DIR, "chat.db")


def get_db():
    """获取数据库连接（启用 WAL 模式支持并发读写）"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表结构（幂等操作）"""
    conn = get_db()
    conn.executescript("""
        -- 用户表
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(128) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 会话表
        CREATE TABLE IF NOT EXISTS conversations (
            id VARCHAR(36) PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title VARCHAR(200) DEFAULT '新对话',
            provider VARCHAR(50),
            model VARCHAR(100),
            system_prompt TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        -- 消息表
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id VARCHAR(36) NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        -- 知识库文档表
        CREATE TABLE IF NOT EXISTS documents (
            id VARCHAR(36) PRIMARY KEY,
            user_id INTEGER NOT NULL,
            filename VARCHAR(255) NOT NULL,
            file_size INTEGER DEFAULT 0,
            chunk_count INTEGER DEFAULT 0,
            provider VARCHAR(50) DEFAULT '',
            provider_file_id VARCHAR(100) DEFAULT '',
            upload_mode VARCHAR(20) DEFAULT 'local',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        -- 文档分块表（含向量 BLOB）
        CREATE TABLE IF NOT EXISTS document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id VARCHAR(36) NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            heading VARCHAR(500) DEFAULT '',
            hierarchy_json TEXT DEFAULT '[]',
            embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        -- 索引
        CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_user_filename ON documents(user_id, filename);

        -- FTS5 全文索引（中文分词使用 unicode61 tokenizer）
        CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts
            USING fts5(text, heading, content='document_chunks', content_rowid='id',
                       tokenize='unicode61');

        -- 自动同步触发器
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON document_chunks BEGIN
            INSERT INTO document_chunks_fts(rowid, text, heading)
            VALUES (new.id, new.text, new.heading);
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON document_chunks BEGIN
            INSERT INTO document_chunks_fts(document_chunks_fts, rowid, text, heading)
            VALUES('delete', old.id, old.text, old.heading);
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON document_chunks BEGIN
            INSERT INTO document_chunks_fts(document_chunks_fts, rowid, text, heading)
            VALUES('delete', old.id, old.text, old.heading);
            INSERT INTO document_chunks_fts(rowid, text, heading)
            VALUES (new.id, new.text, new.heading);
        END;
    """)
    # ---- 迁移：为旧表添加新列（幂等，重复执行无副作用） ----
    migrations = [
        "ALTER TABLE documents ADD COLUMN provider VARCHAR(50) DEFAULT ''",
        "ALTER TABLE documents ADD COLUMN provider_file_id VARCHAR(100) DEFAULT ''",
        "ALTER TABLE documents ADD COLUMN upload_mode VARCHAR(20) DEFAULT 'local'",
        "ALTER TABLE messages ADD COLUMN original_text TEXT DEFAULT NULL",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # 列已存在，跳过
    conn.commit()
    conn.close()


# ============================================================
# 用户操作
# ============================================================

def create_user(username, password_hash):
    """创建用户，返回用户 ID"""
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash)
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None  # 用户名已存在
    finally:
        conn.close()


def get_user_by_username(username):
    """根据用户名查询用户"""
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_id(user_id):
    """根据 ID 查询用户"""
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


# ============================================================
# 会话操作
# ============================================================

def create_conversation(user_id, title="新对话", provider=None, model=None, system_prompt=None):
    """创建会话，返回会话 ID"""
    conv_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        """INSERT INTO conversations (id, user_id, title, provider, model, system_prompt)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (conv_id, user_id, title, provider, model, system_prompt)
    )
    conn.commit()
    conn.close()
    return conv_id


def get_user_conversations(user_id, limit=100):
    """获取用户的会话列表"""
    conn = get_db()
    rows = conn.execute(
        """SELECT id, title, provider, model, created_at, updated_at
           FROM conversations
           WHERE user_id = ?
           ORDER BY updated_at DESC
           LIMIT ?""",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation(conv_id, user_id=None):
    """获取会话详情（可选验证 user_id）"""
    conn = get_db()
    if user_id:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_conversation(conv_id, **kwargs):
    """更新会话字段"""
    allowed = {"title", "provider", "model", "system_prompt"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [conv_id]

    conn = get_db()
    conn.execute(
        f"UPDATE conversations SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values
    )
    conn.commit()
    conn.close()


def delete_conversation(conv_id, user_id=None):
    """删除会话（级联删除消息）"""
    conn = get_db()
    if user_id:
        conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id)
        )
    else:
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()


# ============================================================
# 消息操作
# ============================================================

def save_message(conversation_id, role, content, original_text=None):
    """保存单条消息，original_text 用于保存用户原始输入（仅 user 角色有意义）"""
    conn = get_db()
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, original_text) VALUES (?, ?, ?, ?)",
        (conversation_id, role, content, original_text)
    )
    # 同时更新会话的 updated_at
    conn.execute(
        "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (conversation_id,)
    )
    conn.commit()
    conn.close()


def get_conversation_messages(conversation_id, limit=200):
    """获取会话的消息列表"""
    conn = get_db()
    rows = conn.execute(
        """SELECT role, content, created_at, original_text
           FROM messages
           WHERE conversation_id = ?
           ORDER BY id ASC
           LIMIT ?""",
        (conversation_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation_message_count(conversation_id):
    """获取会话消息数量"""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?",
        (conversation_id,)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


# ============================================================
# 知识库文档操作
# ============================================================

def create_document(user_id, filename, file_size=0, chunk_count=0, provider="", provider_file_id="", upload_mode="local"):
    """创建文档记录，返回文档 ID。若同名文件已存在返回 None"""
    doc_id = str(uuid.uuid4())
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO documents (id, user_id, filename, file_size, chunk_count, provider, provider_file_id, upload_mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, user_id, filename, file_size, chunk_count, provider, provider_file_id, upload_mode)
        )
        conn.commit()
        return doc_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def find_document_by_filename(user_id, filename):
    """查找用户是否已有同名文档，返回文档记录或 None"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, filename, file_size, chunk_count, provider, provider_file_id, upload_mode, created_at FROM documents WHERE user_id = ? AND filename = ?",
            (user_id, filename)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_documents(user_id):
    """获取用户的所有文档列表"""
    conn = get_db()
    rows = conn.execute(
        """SELECT id, filename, file_size, chunk_count, provider, provider_file_id, upload_mode, created_at
           FROM documents
           WHERE user_id = ?
           ORDER BY created_at DESC""",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_document(doc_id, user_id=None):
    """获取文档详情，可选验证 user_id"""
    conn = get_db()
    if user_id:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ? AND user_id = ?",
            (doc_id, user_id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def rename_document(doc_id, user_id, new_filename):
    """重命名文档，返回受影响行数"""
    if not new_filename or not isinstance(new_filename, str):
        return 0
    new_filename = new_filename.strip()[:500]
    conn = get_db()
    try:
        if user_id:
            cursor = conn.execute(
                "UPDATE documents SET filename = ? WHERE id = ? AND user_id = ?",
                (new_filename, doc_id, user_id)
            )
        else:
            cursor = conn.execute(
                "UPDATE documents SET filename = ? WHERE id = ?",
                (new_filename, doc_id)
            )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def delete_document(doc_id, user_id=None):
    """删除文档（级联删除分块），同时清理 FAISS 索引。返回受影响行数"""
    from vector_store import get_vector_store

    conn = get_db()
    try:
        # 先获取 chunk IDs 用于清理 FAISS
        chunk_rows = conn.execute(
            "SELECT id FROM document_chunks WHERE document_id = ?",
            (doc_id,)
        ).fetchall()
        chunk_ids = [r["id"] for r in chunk_rows]

        if user_id:
            cursor = conn.execute(
                "DELETE FROM documents WHERE id = ? AND user_id = ?",
                (doc_id, user_id)
            )
        else:
            cursor = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
        # FTS5 由触发器自动清理
    finally:
        conn.close()

    # 清理 FAISS 索引
    if chunk_ids:
        vs = get_vector_store()
        vs.remove_by_chunk_ids(chunk_ids)

    return cursor.rowcount


def save_chunks(document_id, chunks):
    """
    批量保存文档分块及其向量。
    文本 + embedding BLOB → SQLite（保留 BLOB 作为降级备份）
    向量 → FAISS HNSW 索引
    FTS5 由触发器自动同步，无需手动写入

    整个写入在单个事务中完成，失败时全部回滚。
    """
    import json
    import numpy as np
    from cache_manager import get_embeddings_batch
    from vector_store import get_vector_store

    conn = get_db()
    try:
        # 所有文件统一计算 embedding（包括单 chunk 的小文件）
        texts = [c["text"] for c in chunks]
        embeddings = get_embeddings_batch(texts)

        chunk_db_ids = []
        valid_vectors = []
        valid_chunk_ids = []

        for i, chunk in enumerate(chunks):
            embedding_blob = None
            vec = embeddings[i] if i < len(embeddings) else []
            if vec:
                arr = np.array(vec, dtype=np.float32)
                embedding_blob = arr.tobytes()

            hierarchy_json = json.dumps(chunk.get("hierarchy", []), ensure_ascii=False)
            cursor = conn.execute(
                """INSERT INTO document_chunks
                   (document_id, chunk_index, text, heading, hierarchy_json, embedding)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (document_id, i, chunk["text"], chunk.get("heading", ""),
                 hierarchy_json, embedding_blob)
            )
            chunk_db_id = cursor.lastrowid
            chunk_db_ids.append(chunk_db_id)

            if vec:
                valid_vectors.append(vec)
                valid_chunk_ids.append(chunk_db_id)

        conn.commit()

        # 写入 FAISS 索引
        if valid_vectors:
            vs = get_vector_store()
            if not vs.is_fallback:
                vectors_array = np.array(valid_vectors, dtype=np.float32)
                vs.add(valid_chunk_ids, vectors_array)
                vs.save()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_chunks_by_document(document_id):
    """获取文档的所有分块（含 embedding 反序列化）"""
    import json
    import numpy as np

    conn = get_db()
    rows = conn.execute(
        """SELECT id, chunk_index, text, heading, hierarchy_json, embedding
           FROM document_chunks
           WHERE document_id = ?
           ORDER BY chunk_index""",
        (document_id,)
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        r = dict(r)
        hierarchy = json.loads(r["hierarchy_json"]) if r["hierarchy_json"] else []
        embedding = None
        if r["embedding"]:
            arr = np.frombuffer(r["embedding"], dtype=np.float32)
            embedding = arr.tolist()
        result.append({
            "id": r["id"],
            "chunk_index": r["chunk_index"],
            "text": r["text"],
            "heading": r["heading"],
            "hierarchy": hierarchy,
            "embedding": embedding
        })
    return result


def search_chunks_by_embedding(query_vector, document_ids=None, top_k=5):
    """
    向量语义检索：numpy 批量计算查询向量与所有分块向量的余弦相似度。
    document_ids: 限定检索范围，None 则表示全部文档。
    返回 Top-K 分块列表，按相似度降序排列。
    """
    import json
    import numpy as np

    if not query_vector:
        return []

    q = np.array(query_vector, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []

    conn = get_db()
    try:
        # 限制查询范围防止内存溢出（最多加载 5000 条带向量的分块）
        FETCH_LIMIT = 5000
        if document_ids:
            placeholders = ",".join(["?"] * len(document_ids))
            rows = conn.execute(
                f"""SELECT id, document_id, chunk_index, text, heading, hierarchy_json, embedding
                   FROM document_chunks
                   WHERE document_id IN ({placeholders})
                   AND embedding IS NOT NULL
                   LIMIT ?""",
                document_ids + [FETCH_LIMIT]
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, document_id, chunk_index, text, heading, hierarchy_json, embedding
                   FROM document_chunks
                   WHERE embedding IS NOT NULL
                   LIMIT ?""",
                (FETCH_LIMIT,)
            ).fetchall()
    finally:
        conn.close()

    # 收集有效向量和元数据
    ids_meta, vectors = [], []
    for r in rows:
        emb_blob = r["embedding"]
        if not emb_blob:
            continue
        v = np.frombuffer(emb_blob, dtype=np.float32)
        if np.linalg.norm(v) == 0:
            continue
        ids_meta.append(r)
        vectors.append(v)

    if not vectors:
        return []

    # numpy 批量计算余弦相似度（O(n) for 循环 → 矩阵乘法）
    matrix = np.stack(vectors)
    norms = np.linalg.norm(matrix, axis=1)
    norms = np.where(norms == 0, 1, norms)
    sims = (matrix @ q) / (norms * q_norm)

    top_idx = np.argsort(sims)[::-1][:top_k]

    results = []
    for i in top_idx:
        r = ids_meta[i]
        hierarchy = json.loads(r["hierarchy_json"]) if r["hierarchy_json"] else []
        results.append({
            "id": r["id"],
            "document_id": r["document_id"],
            "chunk_index": r["chunk_index"],
            "text": r["text"],
            "heading": r["heading"],
            "hierarchy": hierarchy,
            "score": float(sims[i])
        })
    return results


def _text_to_fts5_query(text: str) -> str:
    """
    将用户输入转为 FTS5 查询语法。
    提取关键词，用 OR 连接，提高召回率。
    """
    import re
    # 提取中文词组和英文单词（过滤标点和停用词）
    tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text)
    # 过滤过短的词
    tokens = [t for t in tokens if len(t) >= 2 or t.isascii() is False]
    if not tokens:
        return ""
    # 用 OR 连接，每个词用双引号包裹防止语法错误
    return " OR ".join(f'"{t}"' for t in tokens[:10])  # 最多 10 个关键词


def _rrf_fusion(faiss_results: dict, fts_results: dict,
                document_ids=None, top_k=5) -> list:
    """
    Reciprocal Rank Fusion 融合排序。

    RRF 公式：score(d) = Σ 1/(k + rank_i(d))
    其中 k=60 是常数，rank 从 1 开始。
    """
    import json

    RRF_K = 60

    # 按各自排序分配 rank
    faiss_ranked = sorted(faiss_results.items(), key=lambda x: x[1], reverse=True)
    fts_ranked = sorted(fts_results.items(), key=lambda x: x[1], reverse=True)

    # 计算 RRF 分数
    rrf_scores = {}
    for rank, (chunk_id, _) in enumerate(faiss_ranked, 1):
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1.0 / (RRF_K + rank)
    for rank, (chunk_id, _) in enumerate(fts_ranked, 1):
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1.0 / (RRF_K + rank)

    if not rrf_scores:
        return []

    # 按 RRF 分数降序取 top_k
    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:top_k * 2]

    # 回 SQLite 取文本内容
    conn = get_db()
    try:
        placeholders = ",".join(["?"] * len(sorted_ids))
        sql = f"""
            SELECT dc.id, dc.document_id, dc.chunk_index, dc.text,
                   dc.heading, dc.hierarchy_json
            FROM document_chunks dc
            WHERE dc.id IN ({placeholders})
        """
        params = list(sorted_ids)
        if document_ids:
            doc_placeholders = ",".join(["?"] * len(document_ids))
            sql += f" AND dc.document_id IN ({doc_placeholders})"
            params.extend(document_ids)

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    # 组装结果，按 RRF 分数排序
    chunk_map = {}
    for row in rows:
        row = dict(row)
        hierarchy = json.loads(row["hierarchy_json"]) if row["hierarchy_json"] else []
        chunk_map[row["id"]] = {
            "id": row["id"],
            "document_id": row["document_id"],
            "chunk_index": row["chunk_index"],
            "text": row["text"],
            "heading": row["heading"],
            "hierarchy": hierarchy,
            "score": rrf_scores.get(row["id"], 0.0),
            # 标记来源，便于调试
            "source": []
        }
        if row["id"] in faiss_results:
            chunk_map[row["id"]]["source"].append("semantic")
        if row["id"] in fts_results:
            chunk_map[row["id"]]["source"].append("keyword")

    # 按 RRF 分数排序返回
    results = sorted(chunk_map.values(), key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def search_chunks_hybrid(query_text, query_vector, document_ids=None, top_k=5):
    """
    混合检索入口。同时接收原始文本（给 FTS5）和向量（给 FAISS）。
    替代原 search_chunks_by_embedding 作为新的主入口。
    """
    import json
    import numpy as np
    from vector_store import get_vector_store

    if not query_text and not query_vector:
        return []

    vs = get_vector_store()

    # ===== 第一路：FAISS ANN 语义检索 =====
    faiss_results = {}  # chunk_id → similarity_score
    if query_vector and not vs.is_fallback and vs.total_vectors > 0:
        fetch_k = max(top_k * 4, 40)
        raw_results = vs.search(np.array(query_vector, dtype=np.float32), top_k=fetch_k)
        for chunk_id, score in raw_results:
            faiss_results[chunk_id] = score

    # ===== 第二路：SQLite FTS5 全文检索 =====
    fts_results = {}  # chunk_id → bm25_score
    if query_text:
        conn = get_db()
        try:
            terms = _text_to_fts5_query(query_text)
            if terms:
                if document_ids:
                    doc_placeholders = ",".join(["?"] * len(document_ids))
                    sql = f"""
                        SELECT dc.id, rank
                        FROM document_chunks_fts fts
                        JOIN document_chunks dc ON dc.id = fts.rowid
                        WHERE document_chunks_fts MATCH ?
                          AND dc.document_id IN ({doc_placeholders})
                        ORDER BY rank
                        LIMIT ?
                    """
                    params = [terms] + document_ids + [max(top_k * 4, 40)]
                else:
                    sql = """
                        SELECT dc.id, rank
                        FROM document_chunks_fts fts
                        JOIN document_chunks dc ON dc.id = fts.rowid
                        WHERE document_chunks_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """
                    params = [terms, max(top_k * 4, 40)]

                rows = conn.execute(sql, params).fetchall()
                for row in rows:
                    # rank 是 BM25 分数（负数，越小越相关）
                    # 转换为正分数：取绝对值的倒数
                    fts_results[row["id"]] = abs(row["rank"]) if row["rank"] != 0 else 0.001
        except Exception as e:
            print(f"[FTS5] 全文检索异常，降级到纯语义检索: {e}")
        finally:
            conn.close()

    # 如果两路都没有结果，回退到旧的暴力扫描
    if not faiss_results and not fts_results and query_vector:
        return _brute_force_search(query_vector, document_ids, top_k)

    return _rrf_fusion(faiss_results, fts_results, document_ids, top_k)


def _brute_force_search(query_vector, document_ids=None, top_k=5) -> list:
    """
    暴力扫描兜底 — 当 FAISS 和 FTS5 都无结果时使用。
    保留原 search_chunks_by_embedding 的完整逻辑。
    """
    return search_chunks_by_embedding(query_vector, document_ids, top_k)


# ============================================================
# 初始化（模块加载时自动执行）
# ============================================================

try:
    init_db()
    print(f"[DB] 数据库已初始化: {DB_PATH}")
except OSError as e:
    print(f"[DB] 数据库初始化失败: {e}")

