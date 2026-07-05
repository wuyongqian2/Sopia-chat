"""
migrate_to_faiss.py — 一次性迁移脚本

将 SQLite document_chunks 表中的 embedding BLOB 导入 FAISS HNSW 索引。
同时重建 FTS5 索引（如果旧数据没有 FTS5 记录）。
运行方式：python migrate_to_faiss.py
幂等：重复运行会重建索引，不会产生重复数据。
"""

import os
import sys
import sqlite3
import numpy as np

DB_PATH = os.path.join(os.path.expanduser("~"), ".workbuddy", "chat.db")


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        return

    from vector_store import get_vector_store

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. 迁移向量到 FAISS
    rows = conn.execute(
        "SELECT id, embedding FROM document_chunks WHERE embedding IS NOT NULL"
    ).fetchall()

    if rows:
        chunk_ids = []
        vectors = []
        skipped = 0
        for row in rows:
            emb_blob = row["embedding"]
            if not emb_blob:
                skipped += 1
                continue
            vec = np.frombuffer(emb_blob, dtype=np.float32)
            if len(vec) != 512:
                print(f"  跳过 chunk_id={row['id']}：维度 {len(vec)} != 512")
                skipped += 1
                continue
            chunk_ids.append(row["id"])
            vectors.append(vec)

        if vectors:
            vs = get_vector_store()
            all_vectors = np.array(vectors, dtype=np.float32)
            vs.rebuild_index(all_vectors, chunk_ids)
            vs.save()
            print(f"FAISS 迁移完成: {len(vectors)} 条向量导入，{skipped} 条跳过")
    else:
        print("无旧向量需要迁移")

    # 2. 重建 FTS5 索引（清除后重新填充）
    try:
        conn.execute("INSERT INTO document_chunks_fts(document_chunks_fts) VALUES('rebuild')")
        conn.commit()
        print("FTS5 全文索引已重建")
    except Exception as e:
        print(f"FTS5 重建跳过: {e}（可能表不存在，首次启动时会自动创建）")

    conn.close()
    print(f"索引文件: {os.path.join(os.path.expanduser('~'), '.workbuddy', 'faiss.index')}")


if __name__ == "__main__":
    migrate()
