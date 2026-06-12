# MirrorTalk - Semantic Cache (embedding-based query dedup)
from __future__ import annotations

import json
import logging
import time
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.services.embedding import embed_query

logger = logging.getLogger(__name__)

# Cache collection name
CACHE_COLLECTION = "semantic_cache"

_chroma_client: chromadb.PersistentClient | None = None


def _get_cache_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        cache_dir = settings.data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=str(cache_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


def _get_cache_collection() -> chromadb.Collection:
    client = _get_cache_client()
    return client.get_or_create_collection(
        name=CACHE_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


async def get_cached_reply(
    query: str,
    persona_id: str,
    threshold: float = 0.95,
    max_age_seconds: int = 86400,  # 24h
) -> Optional[str]:
    """Check semantic cache for similar query. Returns cached reply if found."""
    try:
        q_vec = await embed_query(query)
        if not q_vec:
            return None

        collection = _get_cache_collection()
        results = collection.query(
            query_embeddings=[q_vec],
            n_results=1,
            where={"persona_id": persona_id},
        )

        if not results["ids"] or not results["ids"][0]:
            return None

        distance = results["distances"][0][0] if results.get("distances") else 1.0
        similarity = 1.0 - distance

        if similarity < threshold:
            return None

        meta = results["metadatas"][0][0] if results.get("metadatas") else {}
        cached_at = float(meta.get("cached_at", 0))
        if time.time() - cached_at > max_age_seconds:
            logger.info(f"Cache expired for query: {query[:40]}...")
            return None

        reply = meta.get("reply", "")
        if reply:
            logger.info(f"Semantic cache HIT (similarity={similarity:.3f}): {query[:20]}...")
            return reply

        return None

    except Exception as e:
        logger.debug(f"Cache lookup failed: {e}")
        return None


async def set_cached_reply(
    query: str,
    reply: str,
    persona_id: str,
) -> None:
    """Store query-reply pair in semantic cache."""
    try:
        q_vec = await embed_query(query)
        if not q_vec:
            return

        cache_id = f"{persona_id}:{hash(query)}"

        collection = _get_cache_collection()
        collection.upsert(
            ids=[cache_id],
            embeddings=[q_vec],
            documents=[query],
            metadatas=[{
                "persona_id": persona_id,
                "reply": reply,
                "query": query,
                "cached_at": str(time.time()),
            }],
        )
        logger.debug(f"Cached reply for query: {query[:30]}...")

    except Exception as e:
        logger.debug(f"Cache write failed: {e}")


def get_cache_stats() -> dict:
    """Return cache collection stats."""
    try:
        collection = _get_cache_collection()
        count = collection.count()
        return {"entry_count": count, "status": "active"}
    except Exception as e:
        return {"entry_count": 0, "status": f"error: {e}"}