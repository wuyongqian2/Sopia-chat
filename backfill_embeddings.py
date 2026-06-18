"""补算已有文档分块的 embedding 向量（一次性运行）"""
import sqlite3
import os
import time
import numpy as np

DB_PATH = os.path.join(os.path.expanduser("~"), ".workbuddy", "chat.db")

def backfill():
    from cache_manager import get_embedding, _local_embedding_model

    # 确保模型已加载
    _local_embedding_model._ensure_loading()
    time.sleep(3)  # 等待模型加载完成（首次较慢）

    status = _local_embedding_model.get_status()
    if not status.get("loaded"):
        print(f"[ERROR] 模型未加载: {status}")
        return

    print(f"[INFO] 模型已就绪: {status}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, text FROM document_chunks WHERE embedding IS NULL"
    ).fetchall()

    if not rows:
        print("[OK] 所有分块已有 embedding，无需补算")
        conn.close()
        return

    print(f"[INFO] 需要补算 {len(rows)} 个分块...")

    success, fail = 0, 0
    for i, row in enumerate(rows):
        vec = get_embedding(row["text"])
        if vec:
            blob = np.array(vec, dtype=np.float32).tobytes()
            conn.execute(
                "UPDATE document_chunks SET embedding = ? WHERE id = ?",
                (blob, row["id"])
            )
            success += 1
        else:
            fail += 1

        if (i + 1) % 20 == 0:
            conn.commit()
            print(f"  进度: {i+1}/{len(rows)} (成功 {success}, 失败 {fail})")

    conn.commit()
    conn.close()
    print(f"[完成] 补算结束: 成功 {success}, 失败 {fail}, 总计 {len(rows)}")

if __name__ == "__main__":
    backfill()
