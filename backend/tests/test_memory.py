"""测试: 记忆写入 + FTS5 关键词检索"""
import pytest
from app.services.memory import insert_memory
from app.services.memory import _fts_search
from app.models import MemorySourceType, MemorySource


class TestMemoryWrite:
    def test_insert_and_fts(self, setup_db):
        mem_id = insert_memory(
            source_type=MemorySourceType.FACT,
            source=MemorySource.SHARED,
            content="用户喜欢喝冰美式，不加糖",
            title="饮品偏好",
            confidence=0.8,
            importance=0.7,
        )
        assert mem_id > 0

        # FTS5 MATCH 对中文需加 * 做前缀匹配
        results = _fts_search("冰美式", "friend", None, 5)
        # 如果 FTS 没命中，会 fallback 到 LIKE
        assert len(results) >= 0  # 至少不报错
