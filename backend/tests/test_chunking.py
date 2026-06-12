""""测试: 文本分块策略"""
import pytest
from app.services.chunking import TextChunker


class TestChunking:
    def test_short_text_no_split(self):
        chunker = TextChunker(chunk_size=512)
        result = chunker.chunk_text("你好，这是一条短文本。")
        assert len(result.chunks) == 1
        assert "你好" in result.chunks[0]

    def test_paragraph_split(self):
        chunker = TextChunker(chunk_size=512)
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        result = chunker.chunk_text(text)
        assert len(result.chunks) == 3

    def test_chunk_to_parent_tracking(self):
        chunker = TextChunker(chunk_size=512)
        text = "短段落A。\n\n" + "这是一个很长的段落" * 200 + "\n\n短段落B。"
        result = chunker.chunk_text(text)
        assert len(result.chunks) >= 1
        # 长段落应产生子块引用父块
        has_child = any(pi is not None for pi in result.chunk_to_parent)
        assert len(result.parent_chunks) >= 1

    def test_parent_context_retrieval(self):
        chunker = TextChunker(chunk_size=512)
        text = "第一章概述\n\n" + "这是一个很长的段落" * 200 + "\n\n第三章总结"
        result = chunker.chunk_text(text)
        # find a child chunk
        for i, pi in enumerate(result.chunk_to_parent):
            if pi is not None:
                ctx = chunker.get_parent_context(result, i)
                assert len(ctx) > 0
                break
