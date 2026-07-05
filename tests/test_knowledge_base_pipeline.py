"""
知识库完整链路集成测试

测试流程：
1. 准备测试文档（含多个章节的 Markdown）
2. 语义分块（chunk_markdown）
3. Embedding 向量化（本地 ONNX 模型）
4. 存入 SQLite（含 embedding BLOB）
5. 用户提问 → 转向量 → 余弦相似度检索
6. 验证检索结果的相关性和排序
"""

import pytest
import os
import sys
import uuid
import sqlite3

# 让测试能 import 项目根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="module")
def test_db(tmp_path_factory):
    """
    创建一个临时 SQLite 数据库，避免污染真实数据。
    使用 module scope 确保 ONNX 模型只加载一次。
    """
    import database as db_module

    # 将数据库路径指向临时目录
    tmp_db_dir = tmp_path_factory.mktemp("test_kb")
    tmp_db_path = os.path.join(str(tmp_db_dir), "test_kb.db")

    # 保存原始值
    original_db_dir = db_module.DB_DIR
    original_db_path = db_module.DB_PATH

    # 替换为临时路径
    db_module.DB_DIR = str(tmp_db_dir)
    db_module.DB_PATH = tmp_db_path

    # 初始化表结构
    db_module.init_db()

    # 创建测试用户（满足 documents 表的外键约束）
    conn = db_module.get_db()
    conn.execute(
        """INSERT OR IGNORE INTO users (id, username, password_hash)
           VALUES (1, 'testuser', 'testhash')"""
    )
    conn.commit()
    conn.close()

    yield db_module

    # 恢复原始路径
    db_module.DB_DIR = original_db_dir
    db_module.DB_PATH = original_db_path


@pytest.fixture(scope="module")
def sample_markdown():
    """一份包含多个主题章节的测试文档"""
    return """# Python 编程指南

## 基础语法

Python 是一种动态类型语言，支持多种编程范式。变量声明不需要指定类型，
解释器会根据赋值自动推断。Python 使用缩进来表示代码块，而不是大括号。

常见的数据类型包括：列表（list）、元组（tuple）、字典（dict）、集合（set）。
列表是可变的有序序列，元组是不可变的有序序列。

## 面向对象编程

Python 支持面向对象编程（OOP）。类（class）是对象的蓝图，
通过 class 关键字定义。__init__ 方法是构造函数，self 代表实例本身。

继承允许子类复用父类的代码。Python 支持多继承，通过方法解析顺序（MRO）
来决定调用优先级。抽象基类（ABC）可以定义接口规范。

## Web 开发框架

Flask 是一个轻量级的 Python Web 框架，适合构建小型到中型应用。
它提供了路由、模板渲染、请求处理等核心功能。Flask 的设计哲学是
"微框架"，核心简单但可通过扩展增强。

Django 是一个全功能的 Web 框架，内置 ORM、管理后台、认证系统等。
适合构建大型复杂应用。Django 遵循 MTV（Model-Template-View）架构模式。

## 数据科学

NumPy 是 Python 科学计算的基础库，提供了高性能的多维数组对象。
Pandas 基于 NumPy 构建，提供了 DataFrame 数据结构，适合处理结构化数据。

Matplotlib 是最常用的可视化库，可以绘制折线图、柱状图、散点图等。
Seaborn 基于 Matplotlib 封装，提供了更美观的默认样式和统计图表。

# JavaScript 入门

## 变量与类型

JavaScript 有三种声明变量的方式：var、let 和 const。
let 和 const 是 ES6 引入的块级作用域变量。const 声明的变量不可重新赋值。

JavaScript 的基本数据类型包括：number、string、boolean、null、undefined、
symbol 和 bigint。对象（object）是引用类型，包括普通对象、数组和函数。

## 异步编程

JavaScript 是单线程语言，通过事件循环（Event Loop）实现异步操作。
Promise 是异步编程的核心概念，代表一个尚未完成但预期会完成的操作。

async/await 是 Promise 的语法糖，让异步代码看起来像同步代码。
async 函数总是返回一个 Promise，await 会暂停函数执行直到 Promise 完成。
"""


class TestKnowledgeBasePipeline:
    """知识库完整链路测试：文档 → 分块 → 向量化 → 存储 → 检索"""

    def test_01_embedding_model_loads(self, test_db):
        """Step 1: ONNX Embedding 模型能正常加载"""
        from cache_manager import get_embedding

        vector = get_embedding("测试文本")
        assert vector is not None, "Embedding 模型返回了空向量"
        assert len(vector) == 512, f"向量维度应为 512，实际 {len(vector)}"
        # 验证是 L2 归一化的（模长约为 1.0）
        import numpy as np
        norm = np.linalg.norm(vector)
        assert 0.99 < norm < 1.01, f"向量应 L2 归一化，实际模长 {norm}"

    def test_02_chunk_markdown(self, test_db, sample_markdown):
        """Step 2: Markdown 语义分块正确"""
        from chunker import chunk_markdown

        chunks = chunk_markdown(sample_markdown)
        assert len(chunks) >= 5, f"文档应至少分为 5 个块，实际 {len(chunks)}"

        # 验证每个 chunk 都有必要字段
        for chunk in chunks:
            assert "text" in chunk and len(chunk["text"]) > 0
            assert "heading" in chunk
            assert "hierarchy" in chunk

        # 验证分块内容包含不同主题
        all_text = " ".join(c["text"] for c in chunks)
        assert "Python" in all_text
        assert "JavaScript" in all_text
        assert "Flask" in all_text or "Django" in all_text

    def test_03_batch_embedding(self, test_db, sample_markdown):
        """Step 3: 批量 Embedding 向量化"""
        from chunker import chunk_markdown
        from cache_manager import get_embeddings_batch

        chunks = chunk_markdown(sample_markdown)
        texts = [c["text"] for c in chunks]

        embeddings = get_embeddings_batch(texts)
        assert len(embeddings) == len(chunks), "每块文本都应获得一个向量"

        for i, vec in enumerate(embeddings):
            assert len(vec) == 512, f"第 {i} 块向量维度错误：{len(vec)}"
            import numpy as np
            assert np.linalg.norm(vec) > 0.5, f"第 {i} 块向量不应为零向量"

    def test_04_store_chunks_with_embeddings(self, test_db, sample_markdown):
        """Step 4: 分块 + 向量存入 SQLite"""
        from chunker import chunk_markdown

        chunks = chunk_markdown(sample_markdown)
        doc_id = str(uuid.uuid4())

        # 创建文档记录
        conn = test_db.get_db()
        conn.execute(
            """INSERT INTO documents (id, user_id, filename, chunk_count)
               VALUES (?, ?, ?, ?)""",
            (doc_id, 1, "test_guide.md", len(chunks))
        )
        conn.commit()
        conn.close()

        # 存入分块（含向量）
        test_db.save_chunks(doc_id, chunks)

        # 验证数据库中确实存了带向量的分块
        conn = test_db.get_db()
        rows = conn.execute(
            """SELECT COUNT(*) as cnt,
                      SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) as with_emb
               FROM document_chunks
               WHERE document_id = ?""",
            (doc_id,)
        ).fetchone()
        conn.close()

        assert rows["cnt"] == len(chunks), f"应存入 {len(chunks)} 条分块"
        assert rows["with_emb"] == len(chunks), "所有分块都应有 embedding"

    def test_05_semantic_search_relevant(self, test_db):
        """Step 5: 混合检索 — 相关问题应召回对应章节"""
        # 使用独立文档，避免其他测试数据干扰
        from chunker import chunk_markdown

        doc_text = """# Web 开发技术

## 前端框架

React 是由 Facebook 开发的声明式 UI 库，使用虚拟 DOM 提高渲染性能。
组件化开发是 React 的核心理念，每个组件封装自己的状态和渲染逻辑。

## 后端框架

Flask 是 Python 的轻量级 Web 框架，适合快速开发小型应用。
它提供了路由、模板引擎和请求处理等基础功能，扩展性很强。

Django 是 Python 的全功能 Web 框架，内置 ORM、管理后台和认证系统。
适合构建复杂的大型 Web 应用，遵循 MTV 架构模式。

## 数据库

MySQL 是最流行的开源关系型数据库之一，广泛用于 Web 应用。
PostgreSQL 功能更强大，支持 JSON、全文检索和地理空间数据。
"""
        chunks = chunk_markdown(doc_text)
        doc_id = str(uuid.uuid4())

        conn = test_db.get_db()
        conn.execute(
            """INSERT INTO documents (id, user_id, filename, chunk_count)
               VALUES (?, ?, ?, ?)""",
            (doc_id, 1, "test_web_dev.md", len(chunks))
        )
        conn.commit()
        conn.close()
        test_db.save_chunks(doc_id, chunks)

        # 查询后端框架相关问题
        from cache_manager import get_embedding
        query_text = "Flask 和 Django 哪个更适合做 Web 开发？"
        query_vector = get_embedding(query_text)
        assert query_vector is not None, "查询向量化失败"

        results = test_db.search_chunks_hybrid(query_text, query_vector, [doc_id], top_k=3)
        assert len(results) > 0, "检索应返回至少 1 条结果"

        # 验证 top-1 结果与后端框架相关
        top1_text = results[0]["text"].lower()
        assert any(kw in top1_text for kw in ["flask", "django", "后端", "web", "框架"]), \
            f"Top-1 结果应与 Web 框架相关，实际内容：{results[0]['text'][:100]}"

        # 验证分数合理（RRF 分数通常较小但为正）
        assert results[0]["score"] > 0, \
            f"Top-1 分数应为正数，实际 {results[0]['score']:.4f}"

    def test_06_semantic_search_cross_topic(self, test_db, sample_markdown):
        """Step 6: 跨主题检索 — JavaScript 问题不应召回 Python 章节"""
        from chunker import chunk_markdown

        chunks = chunk_markdown(sample_markdown)
        doc_id = str(uuid.uuid4())

        conn = test_db.get_db()
        conn.execute(
            """INSERT INTO documents (id, user_id, filename, chunk_count)
               VALUES (?, ?, ?, ?)""",
            (doc_id, 1, "test_guide_cross.md", len(chunks))
        )
        conn.commit()
        conn.close()
        test_db.save_chunks(doc_id, chunks)

        # 查询 JavaScript 相关问题
        from cache_manager import get_embedding
        query_text = "JavaScript 的 async/await 怎么用？"
        query_vector = get_embedding(query_text)
        results = test_db.search_chunks_hybrid(query_text, query_vector, [doc_id], top_k=3)

        assert len(results) > 0, "检索应返回结果"

        # top-1 应该与 JavaScript 异步编程相关
        top1_text = results[0]["text"].lower()
        assert any(kw in top1_text for kw in ["javascript", "promise", "async", "await", "事件循环"]), \
            f"Top-1 结果应与 JS 异步相关，实际：{results[0]['text'][:100]}"

        # 验证排序：JavaScript 章节的分数应高于 Python 章节
        js_scores = []
        py_scores = []
        for r in results:
            text_lower = r["text"].lower()
            if "javascript" in text_lower or "promise" in text_lower or "async" in text_lower:
                js_scores.append(r["score"])
            elif "python" in text_lower or "flask" in text_lower or "django" in text_lower:
                py_scores.append(r["score"])

        if js_scores and py_scores:
            assert max(js_scores) > max(py_scores), \
                f"JavaScript 相关结果分数应高于 Python 结果：JS={js_scores}, PY={py_scores}"

    def test_07_embedding_similarity_semantics(self, test_db):
        """Step 7: 语义相似度验证 — 同义句应比无关句更接近"""
        from cache_manager import get_embedding
        import numpy as np

        # 三组文本
        anchor = "Python 的 Flask 框架怎么安装？"
        similar = "如何安装 Flask？pip install flask"  # 语义相近
        unrelated = "JavaScript 的 Promise 是什么？"     # 语义无关

        v_anchor = np.array(get_embedding(anchor))
        v_similar = np.array(get_embedding(similar))
        v_unrelated = np.array(get_embedding(unrelated))

        # 计算余弦相似度
        sim_score = float(v_anchor @ v_similar / (np.linalg.norm(v_anchor) * np.linalg.norm(v_similar)))
        unsim_score = float(v_anchor @ v_unrelated / (np.linalg.norm(v_anchor) * np.linalg.norm(v_unrelated)))

        assert sim_score > unsim_score, \
            f"同义句相似度({sim_score:.4f})应高于无关句({unsim_score:.4f})"
        # 额外验证：同义句相似度应较高
        assert sim_score > 0.6, f"同义句相似度应 > 0.6，实际 {sim_score:.4f}"

    def test_08_full_pipeline_end_to_end(self, test_db, tmp_path):
        """Step 8: 端到端 — 从原始文本文件到检索结果"""
        from file_extractor import extract_text_only
        from chunker import chunk_markdown
        from cache_manager import get_embedding
        from werkzeug.datastructures import FileStorage
        from io import BytesIO

        # 1. 创建测试文件
        test_content = """# React 组件开发

## 函数组件

React 函数组件是最简单的组件形式，就是一个返回 JSX 的 JavaScript 函数。
函数组件接收 props 对象作为参数，返回要渲染的 UI 元素。

## Hooks

useState 是最基础的 Hook，用于在函数组件中添加状态变量。
useEffect 用于处理副作用，如数据获取、订阅、DOM 操作等。
useEffect 的第二个参数是依赖数组，决定 effect 何时重新执行。

## 状态管理

Redux 是 React 生态中最流行的状态管理库。它使用单一数据源（store）
管理整个应用的状态。Action 描述发生了什么变化，Reducer 根据 Action 更新状态。

Zustand 是一个轻量级的状态管理方案，比 Redux 更简洁。
它不需要 Provider 包裹，也不需要写 Action 和 Reducer 的样板代码。
"""
        txt_path = tmp_path / "react_guide.md"
        txt_path.write_text(test_content, encoding="utf-8")

        # 2. 模拟文件上传解析
        fs = FileStorage(
            stream=BytesIO(txt_path.read_bytes()),
            filename="react_guide.md",
            content_type="application/octet-stream"
        )
        extract_result = extract_text_only(fs)
        assert extract_result["success"], f"文件解析失败：{extract_result.get('error')}"

        # 3. 分块
        chunks = chunk_markdown(extract_result["text"])
        assert len(chunks) >= 3, f"应至少分 3 块，实际 {len(chunks)}"

        # 4. 存入数据库
        doc_id = str(uuid.uuid4())
        conn = test_db.get_db()
        conn.execute(
            """INSERT INTO documents (id, user_id, filename, chunk_count)
               VALUES (?, ?, ?, ?)""",
            (doc_id, 1, "react_guide.md", len(chunks))
        )
        conn.commit()
        conn.close()
        test_db.save_chunks(doc_id, chunks)

        # 5. 检索：问一个关于 React Hooks 的问题
        query_text = "React useEffect 的依赖数组有什么作用？"
        query_vector = get_embedding(query_text)
        results = test_db.search_chunks_hybrid(query_text, query_vector, [doc_id], top_k=3)

        assert len(results) > 0, "端到端检索应返回结果"
        assert results[0]["score"] > 0, \
            f"端到端检索 Top-1 分数应为正数，实际 {results[0]['score']:.4f}"

        # 验证 top-1 与 Hooks 相关
        top1_text = results[0]["text"].lower()
        assert any(kw in top1_text for kw in ["useeffect", "hook", "副作用", "依赖"]), \
            f"Top-1 应与 Hooks 相关，实际：{results[0]['text'][:100]}"
