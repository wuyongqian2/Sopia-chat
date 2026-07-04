"""
API 端点测试
覆盖：/api/chat/upload 聊天附件上传端点
"""

import os
import sys
import pytest
from io import BytesIO


class TestChatUploadEndpoint:
    """聊天附件上传 API：必须返回 extracted_text，is_large 永远为 false"""

    @pytest.fixture
    def client(self):
        """创建 Flask 测试客户端"""
        # 必须在 import app 之前设置环境变量
        os.environ.setdefault("DATABASE_URL", ":memory:")
        from app import app
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["LOGIN_DISABLED"] = True
        # 禁用限流
        app.config["RATELIMIT_ENABLED"] = False
        with app.test_client() as c:
            yield c

    def test_upload_txt_returns_extracted_text(self, client, sample_txt):
        """POST /api/chat/upload 上传 TXT 应返回 extracted_text"""
        content = sample_txt.read_bytes()
        data = {"file": (BytesIO(content), sample_txt.name)}
        resp = client.post(
            "/api/chat/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert "extracted_text" in body
        assert len(body["extracted_text"]) > 0
        assert body["is_large"] is False

    def test_upload_without_file_returns_400(self, client):
        """无文件上传应返回 400"""
        resp = client.post(
            "/api/chat/upload",
            content_type="multipart/form-data"
        )
        assert resp.status_code == 400

    def test_upload_large_txt_returns_full_text(self, client, large_txt):
        """大文件上传也应返回全文，is_large 为 false"""
        content = large_txt.read_bytes()
        data = {"file": (BytesIO(content), large_txt.name)}
        resp = client.post(
            "/api/chat/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert len(body["extracted_text"]) > 15000
        assert body["is_large"] is False
