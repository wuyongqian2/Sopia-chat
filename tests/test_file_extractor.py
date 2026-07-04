"""
file_extractor 模块测试
覆盖：extract_text_only 聊天附件路径（全文返回，不分块）
"""

from file_extractor import extract_text_only
from werkzeug.datastructures import FileStorage
from io import BytesIO


def _make_file_storage(path):
    """将磁盘文件包装为 Flask FileStorage"""
    content = path.read_bytes()
    return FileStorage(
        stream=BytesIO(content),
        filename=path.name,
        content_type="application/octet-stream"
    )


class TestExtractTextOnly:
    """聊天附件上传路径：必须返回全文，不分块"""

    def test_txt_file_returns_full_text(self, sample_txt):
        """TXT 文件应返回完整文本内容"""
        fs = _make_file_storage(sample_txt)
        result = extract_text_only(fs)
        assert result["success"] is True
        assert "测试文本" in result["text"]
        assert "第二行" in result["text"]

    def test_large_file_returns_full_text(self, large_txt):
        """大文件（>15000 字符）也必须返回全文，不能返回占位符"""
        fs = _make_file_storage(large_txt)
        result = extract_text_only(fs)
        assert result["success"] is True
        assert len(result["text"]) > 15000
        assert "文件较大" not in result["text"]  # 不应出现旧占位符

    def test_empty_file_returns_error(self, tmp_path):
        """空文件应返回错误"""
        empty = tmp_path / "empty.txt"
        empty.write_bytes(b"")
        fs = _make_file_storage(empty)
        result = extract_text_only(fs)
        assert result["success"] is False
        assert "为空" in result["error"]

    def test_unsupported_extension_returns_error(self, tmp_path):
        """不支持的文件格式应返回错误"""
        bad = tmp_path / "test.xyz123"
        bad.write_bytes(b"some content")
        fs = _make_file_storage(bad)
        result = extract_text_only(fs)
        assert result["success"] is False
        assert "不支持" in result["error"]

    def test_result_contains_filename(self, sample_txt):
        """返回结果应包含 filename 字段"""
        fs = _make_file_storage(sample_txt)
        result = extract_text_only(fs)
        assert result["success"] is True
        assert "filename" in result
        assert result["filename"] == sample_txt.name
