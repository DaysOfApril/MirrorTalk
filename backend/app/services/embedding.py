# MirrorTalk - Embedding 服务 (本地优先 + 云端回退)
from __future__ import annotations

import logging
from typing import Optional

from app.config import settings
from app.services.database import get_db
from app.services.database import get_config

logger = logging.getLogger(__name__)

_local_model: Optional[object] = None
_local_ready: bool = False


def _db(key: str, fallback: str = "") -> str:
    val = get_config(key)
    return val if val else fallback


def _load_local_model() -> Optional[object]:
    global _local_model, _local_ready
    if _local_ready:
        return _local_model
    try:
        from sentence_transformers import SentenceTransformer
        _local_model = SentenceTransformer(settings.embed_local_model)
        _local_ready = True
        logger.info(f"本地 Embedding 模型加载成功: {settings.embed_local_model}")
        return _local_model
    except Exception as e:
        logger.info(f"本地 Embedding 不可用: {e}，将通过云端回退")
        _local_ready = True
        return None


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量嵌入，自动选择本地/云端"""
    if not texts:
        return []

    if _db("embed_mode", settings.embed_mode) == "local":
        model = _load_local_model()
        if model is not None:
            result = model.encode(texts, normalize_embeddings=True)
            return result.tolist()

    # 云端回退
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=_db("embed_remote_api_key", settings.embed_remote_api_key),
        base_url=_db("embed_remote_base_url", settings.embed_remote_base_url) or None,
    )
    resp = await client.embeddings.create(
        model=_db("embed_remote_model", settings.embed_remote_model),
        input=texts,
    )
    return [d.embedding for d in resp.data]


async def embed_query(text: str) -> list[float]:
    """单条嵌入"""
    results = await embed_texts([text])
    return results[0] if results else []


async def embed_texts_and_index(texts: list[str], ids: list[str]) -> None:
    """??????? ChromaDB"""
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from app.config import settings as app_settings

        embeddings = await embed_texts(texts)
        if not embeddings:
            return

        client = chromadb.PersistentClient(
            path=str(app_settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(
            name="memory_items",
            metadata={"hnsw:space": "cosine"},
        )

        # ? SQLite ???????
        conn = get_db()
        metadata_list = []
        for mem_id in ids:
            row = conn.execute(
                "SELECT source, parent_id, chunk_index, chunk_count FROM memory_items WHERE id = ?",
                (int(mem_id),),
            ).fetchone()
            meta = {"source": "external_file"}
            if row:
                meta["source"] = row["source"]
                if row["parent_id"] is not None:
                    meta["parent_id"] = row["parent_id"]
                    meta["chunk_index"] = row["chunk_index"]
                    meta["chunk_count"] = row["chunk_count"]
            metadata_list.append(meta)
        conn.close()

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadata_list,
            documents=texts,
        )
        logger.info("??? %d ???????", len(texts))
    except Exception as e:
        logger.warning("??????: %s", e)
