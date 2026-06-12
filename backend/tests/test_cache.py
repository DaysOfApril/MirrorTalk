""""测试: 语义缓存"""
import pytest
import time
from app.services.cache import cache_store, cache_lookup, cache_stats, cache_clear


class TestSemanticCache:
    def test_cache_store_and_stats(self):
        cache_clear()
        # Store without embedding (lookup will need embedding)
        cache_store("今天天气真好", "是啊，阳光明媚", "persona_1")
        stats = cache_stats()
        assert stats["total_entries"] == 1

    def test_cache_clear(self):
        cache_store("test query", "test reply", "p1")
        count = cache_clear()
        assert count >= 1
        stats = cache_stats()
        assert stats["total_entries"] == 0
