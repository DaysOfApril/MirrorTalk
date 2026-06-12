# MirrorTalk - 文档解析服务 (TXT/MD/PDF/DOCX/图片OCR)
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

from app.services.chunking import default_chunker, ChunkResult
from app.services.embedding import embed_texts_and_index
from app.services.database import get_db
from app.services.memory import insert_memory
from app.models import MemorySource, MemorySourceType

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".png", ".jpg", ".jpeg"}


async def parse_document(file_path: str | Path) -> tuple[str, str]:
    """"解析文档，返回 (纯文本, 文件类型标识)"""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型: {ext}；支持: {SUPPORTED_EXTENSIONS}")

    if ext == ".txt" or ext == ".md":
        text = path.read_text("utf-8")
        return text, ext.lstrip(".")

    if ext == ".pdf":
        return await _parse_pdf(path)

    if ext == ".docx":
        return _parse_docx(path)

    if ext in (".png", ".jpg", ".jpeg"):
        return await _parse_image(path)

    return "", ext.lstrip(".")


async def _parse_pdf(path: Path) -> tuple[str, str]:
    """"PyMuPDF (fitz) 解析 PDF"""
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF 未安装，尝试 pdfplumber 回退")
        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            return "\n\n".join(pages), "pdf"
        except ImportError:
            raise ImportError("PDF 解析需要安装 PyMuPDF 或 pdfplumber")

    doc = fitz.open(str(path))
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n\n".join(pages), "pdf"


def _parse_docx(path: Path) -> tuple[str, str]:
    """"python-docx 解析 DOCX"""
    try:
        from docx import Document
    except ImportError:
        raise ImportError("DOCX 解析需要安装 python-docx")

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs), "docx"


async def _parse_image(path: Path) -> tuple[str, str]:
    """"OCR 图片提取文字（本地 easyocr 优先 → LLM vision 回退）"""
    try:
        import easyocr
        reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
        results = reader.readtext(str(path), detail=0)
        text = "\n".join(results)
        if text.strip():
            return text, "image_ocr"
    except ImportError:
        logger.info("easyocr 未安装，尝试 LLM vision 回退")

    # LLM vision 回退
    try:
        import base64
        from openai import AsyncOpenAI
        from app.config import settings
        from app.services.database import get_config

        image_bytes = path.read_bytes()
        b64 = base64.b64encode(image_bytes).decode()

        client = AsyncOpenAI(
            api_key=get_config("llm_api_key") or settings.llm_api_key,
            base_url=get_config("llm_base_url") or settings.llm_base_url,
        )
        resp = await client.chat.completions.create(
            model=get_config("llm_model") or settings.llm_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "请提取这张图片中的所有文字内容，只输出文字，不要其他内容。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=2000,
        )
        return resp.choices[0].message.content or "", "image_vision"
    except Exception as e:
        logger.error("图片 OCR 失败: %s", e)
        return "", "image_failed"


async def ingest_document(
    file_path: str | Path,
    persona_id: str,
    source_label: str = "",
) -> dict:
    """"完整文档摄入管线: 解析 → 分块 → 索引"""
    path = Path(file_path)
    filename = source_label or path.name

    # 1. 解析
    text, doc_type = await parse_document(path)
    if not text.strip():
        return {"success": False, "error": "文档解析后无有效文本", "filename": filename}

    # 2. 分块
    chunk_result = default_chunker.chunk_text(text)
    chunks = chunk_result.chunks

    # 3. 写入 SQLite + ChromaDB
    conn = get_db()
    memory_ids = []
    for ci, chunk_text in enumerate(chunks):
        parent_idx = chunk_result.chunk_to_parent[ci] if ci < len(chunk_result.chunk_to_parent) else None
        parent_chunk = chunk_result.parent_chunks[parent_idx] if parent_idx is not None and parent_idx < len(chunk_result.parent_chunks) else ""

        mem_id = insert_memory(
            source_type=MemorySourceType.EXTERNAL,
            source=MemorySource.EXTERNAL_FILE,
            content=chunk_text,
            title=f"{filename} (分块 {ci + 1}/{len(chunks)})",
            confidence=0.7,
            importance=0.6,
            parent_id=None,
            chunk_index=ci,
            chunk_count=len(chunks),
        )
        memory_ids.append(str(mem_id))

        # 绑定到画像
        conn.execute(
            "INSERT OR IGNORE INTO knowledge_persona (knowledge_id, persona_id) VALUES (?, ?)",
            (mem_id, persona_id),
        )
    conn.commit()
    conn.close()

    # 4. 向量化索引
    try:
        await embed_texts_and_index(chunks, memory_ids)
    except Exception as e:
        logger.warning("向量化索引失败: %s", e)

    logger.info("文档摄入完成: %s → %d 块", filename, len(chunks))
    return {
        "success": True,
        "filename": filename,
        "doc_type": doc_type,
        "total_chunks": len(chunks),
        "memory_ids": memory_ids,
    }

