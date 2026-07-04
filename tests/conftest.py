import pytest
import os
import sys

# 让测试能 import 项目根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def sample_txt(tmp_path):
    """创建一个纯文本文件"""
    txt_path = tmp_path / "test.txt"
    txt_path.write_text(
        "这是一段测试文本。\n第二行。\n第三行包含代码：print('hello')",
        encoding="utf-8"
    )
    return txt_path


@pytest.fixture
def large_txt(tmp_path):
    """创建一个超过 15000 字符的大文件"""
    txt_path = tmp_path / "large.txt"
    content = "测试段落内容，用于验证大文件全文返回。\n" * 1000  # 约 20000 字符
    txt_path.write_text(content, encoding="utf-8")
    return txt_path


@pytest.fixture
def sample_md(tmp_path):
    """创建一个 Markdown 文件"""
    md_path = tmp_path / "test.md"
    md_path.write_text(
        "# 第一章\n\n这是第一章的内容。\n\n## 1.1 小节\n\n小节内容。\n\n# 第二章\n\n第二章内容。",
        encoding="utf-8"
    )
    return md_path


@pytest.fixture
def sample_code(tmp_path):
    """创建一个 Python 代码文件"""
    py_path = tmp_path / "sample.py"
    py_path.write_text(
        'def hello():\n    print("hello world")\n\nif __name__ == "__main__":\n    hello()\n',
        encoding="utf-8"
    )
    return py_path
