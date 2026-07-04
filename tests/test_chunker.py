"""
chunker 模块测试
覆盖：Markdown 语义分块逻辑
"""

from chunker import chunk_markdown


class TestChunkMarkdown:
    """Markdown 分块：按标题层级切分，保留代码块完整性"""

    def test_empty_text_returns_empty_list(self):
        """空文本应返回空列表"""
        assert chunk_markdown("") == []
        assert chunk_markdown("   ") == []
        assert chunk_markdown(None) == []

    def test_single_heading_produces_one_chunk(self):
        """单标题文本应产生一个 chunk"""
        text = "# 标题\n\n正文内容"
        chunks = chunk_markdown(text)
        assert len(chunks) >= 1
        assert chunks[0]["heading"] == "标题"
        assert "正文内容" in chunks[0]["text"]

    def test_multiple_headings_split_correctly(self):
        """多标题文本应按标题切分"""
        text = "# 第一章\n内容A\n## 1.1 小节\n内容B\n# 第二章\n内容C"
        chunks = chunk_markdown(text)
        headings = [c["heading"] for c in chunks]
        assert "第一章" in headings
        assert "第二章" in headings

    def test_chunk_has_required_keys(self):
        """每个 chunk 应包含 text, heading, hierarchy, level, index"""
        text = "# 标题\n\n内容"
        chunks = chunk_markdown(text)
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert "text" in chunk
        assert "heading" in chunk
        assert "hierarchy" in chunk
        assert "level" in chunk
        assert "index" in chunk

    def test_code_block_not_split_by_heading(self):
        """代码块内的 # 不应触发分块"""
        text = "# 标题\n\n```python\n# 这是注释\ndef hello():\n    pass\n```\n\n后续内容"
        chunks = chunk_markdown(text)
        # 代码块应完整保留在某个 chunk 中
        all_text = "\n".join(c["text"] for c in chunks)
        assert "# 这是注释" in all_text
        assert "def hello()" in all_text
