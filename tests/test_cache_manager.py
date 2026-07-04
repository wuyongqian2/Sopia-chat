"""
cache_manager 模块测试
覆盖：L1 精确匹配缓存（ExactCache）的命中、未命中、淘汰逻辑
"""

import time
from cache_manager import ExactCache


class TestExactCache:
    """L1 精确匹配缓存：基于 provider:model:question 的 MD5 哈希"""

    def test_cache_hit_same_input(self):
        """相同 question/model/provider 应命中缓存"""
        cache = ExactCache(max_size=100, ttl=7200)
        cache.put("你好", "gpt-4", "openai", "你好！有什么可以帮你的？")
        result = cache.get("你好", "gpt-4", "openai")
        assert result == "你好！有什么可以帮你的？"

    def test_cache_miss_different_question(self):
        """不同 question 应未命中"""
        cache = ExactCache(max_size=100, ttl=7200)
        cache.put("你好", "gpt-4", "openai", "你好！")
        result = cache.get("再见", "gpt-4", "openai")
        assert result is None

    def test_cache_miss_different_model(self):
        """不同 model 应未命中（即使 question 相同）"""
        cache = ExactCache(max_size=100, ttl=7200)
        cache.put("你好", "gpt-4", "openai", "GPT-4 回复")
        result = cache.get("你好", "gpt-3.5", "openai")
        assert result is None

    def test_cache_miss_different_provider(self):
        """不同 provider 应未命中"""
        cache = ExactCache(max_size=100, ttl=7200)
        cache.put("你好", "deepseek-v4", "deepseek", "DS 回复")
        result = cache.get("你好", "deepseek-v4", "kimi")
        assert result is None

    def test_cache_case_insensitive_question(self):
        """question 大小写不敏感（内部 strip+lower）"""
        cache = ExactCache(max_size=100, ttl=7200)
        cache.put("Hello World", "gpt-4", "openai", "response")
        result = cache.get("hello world", "gpt-4", "openai")
        assert result == "response"

    def test_cache_lru_eviction(self):
        """超出 max_size 时 LRU 淘汰最早条目"""
        cache = ExactCache(max_size=2, ttl=7200)
        cache.put("q1", "m1", "p1", "r1")
        cache.put("q2", "m2", "p2", "r2")
        cache.put("q3", "m3", "p3", "r3")  # 触发淘汰
        assert cache.get("q1", "m1", "p1") is None  # 最早条目被淘汰
        assert cache.get("q2", "m2", "p2") == "r2"
        assert cache.get("q3", "m3", "p3") == "r3"

    def test_cache_ttl_expiry(self):
        """超过 TTL 的条目应过期"""
        cache = ExactCache(max_size=100, ttl=1)  # 1 秒 TTL
        cache.put("你好", "gpt-4", "openai", "response")
        time.sleep(1.5)  # 等待过期
        result = cache.get("你好", "gpt-4", "openai")
        assert result is None  # 已过期
