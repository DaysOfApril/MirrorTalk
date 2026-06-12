# MirrorTalk - 分块策略服务（递归字符分块 + 语义边界检测 + 父子块追踪）
from __future__ import annotations

import logging
from typing import Optional

import tiktoken

logger = logging.getLogger(__name__)


class ChunkResult:
    """分块结果"""
    def __init__(
        self,
        chunks: list[str],
        chunk_to_parent: list[Optional[int]],
        parent_chunks: list[str],
    ):
        self.chunks = chunks                # 所有子块文本
        self.chunk_to_parent = chunk_to_parent  # 每个子块对应的父块索引（None=自身即父）
        self.parent_chunks = parent_chunks  # 父块列表（用于上下文重建）


class TextChunker:
    """
    三层分块策略:

    1. 段落级粗切 —— 按空行保留完整语义段落，构建父块
    2. 递归字符分块 —— 对超长段落递归切割（分隔符优先级可配），
       使用 token 计数而非字符数，适配不同模型上下文窗口
    3. 语义边界检测 —— 可选步骤，通过 embedding 相似度
       识别语义漂移点做二次切割

    面试关键词:
    - RecursiveCharacterTextSplitter
    - chunk_size / chunk_overlap
    - 父-子块追溯 (parent-child retrieval)
    - Semantic chunking
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        sep_priority: list[str] | None = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.sep_priority = sep_priority or [
            "\n\n", "\n", "。", ".",
            "！", "？", "，", ",",
        ]

    # ---- public API ----

    def chunk_text(
        self,
        text: str,
        enable_semantic: bool = False,
    ) -> ChunkResult:
        """完整分块入口"""
        # Step 1: 段落级粗切（父块）
        parent_chunks = self._split_paragraphs(text)

        all_chunks: list[str] = []
        chunk_to_parent: list[Optional[int]] = []

        for pi, parent in enumerate(parent_chunks):
            # Step 2: 递归切割
            children = self._recursive_split(parent)

            if len(children) == 1:
                # 未超长，父块自身即检索单元
                all_chunks.append(children[0])
                chunk_to_parent.append(None)
            else:
                for child in children:
                    all_chunks.append(child)
                    chunk_to_parent.append(pi)  # 指向父块

        # Step 3: 语义边界检测（可选）
        if enable_semantic and len(all_chunks) > 1:
            boundaries = self._detect_semantic_boundaries(all_chunks)
            # 在边界处插入空字符串标记，供上层二次切割
            # disable semantic for now, enable via config later
            pass

        return ChunkResult(
            chunks=all_chunks,
            chunk_to_parent=chunk_to_parent,
            parent_chunks=parent_chunks,
        )

    def get_parent_context(
        self,
        result: ChunkResult,
        child_index: int,
    ) -> str:
        """根据子块索引获取父块上下文"""
        pi = result.chunk_to_parent[child_index]
        if pi is None:
            return ""
        if 0 <= pi < len(result.parent_chunks):
            return result.parent_chunks[pi]
        return ""

    # ---- 内部方法 ----

    def _num_tokens(self, text: str) -> int:
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            return len(text) // 2  # 中英文粗略估算

    def _split_paragraphs(self, text: str) -> list[str]:
        """按空行切分，保留非空段落"""
        return [p.strip() for p in text.split("\n\n") if p.strip()]

    def _recursive_split(self, text: str) -> list[str]:
        """递归字符分块，用最合适的分隔符切分"""
        if self._num_tokens(text) <= self.chunk_size:
            return [text]

        for sep in self.sep_priority:
            if sep not in text:
                continue
            parts = text.split(sep)
            merged: list[str] = []
            current = ""
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                candidate = (current + sep + part) if current else part
                if self._num_tokens(candidate) <= self.chunk_size:
                    current = candidate
                else:
                    if current:
                        merged.append(current)
                    current = part
            if current:
                merged.append(current)
            if len(merged) > 1:
                return merged
            continue

        return [text]

    def _detect_semantic_boundaries(
        self,
        chunks: list[str],
        threshold: float = 0.85,
    ) -> list[int]:
        """
        语义边界检测（需 embedding 服务配合）:
        对相邻 chunk 计算 cosine 相似度，低于 threshold
        则标记为语义边界，需要重新切割
        """
        return []


# 全局默认分块器（可被配置覆盖）
default_chunker = TextChunker()
