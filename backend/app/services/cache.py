# MirrorTalk - Semantic Cache (vector similarity-based query caching)
from __future__ import annotations

import hashlib
import logging
import time
from typing import Optional

from app.config import settings
from app.services.embedding import embed_query

logger = logging.getLogger(__name__)

# In-memory cache for fast lookups
_cache: dict[str, dict] = {}

# Cache configurable from settings
CACHE_SIMILARITY_THRESHOLD = 0.95
CACHE_TTL_SECONDS = 3600

try:
    CACHE_SIMILARITY_THRESHOLD = float(
        getattr(settings, "cache_similarity_threshold", 0.95)
    )
    CACHE_TTL_SECONDS = int(
        getattr(settings, "cache_ttl_seconds", 3600)
    )
except Exception:
    pass


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Fast cosine similarity"""
    dot = sum(x * y for x, y in zip(a, b))
    na = (sum(x * x for x in a) ** 0.5)
    nb = (sum(y * y for y in b) ** 0.5)
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def cache_lookup(
    query: str,
    persona_id: str,
) -> Optional[dict]:
    """Look up cached reply by semantic similarity to query"""
    if not query:
        return None

    # Generate query embedding
    query_vec = None
    try:
        query_vec = await embed_query(query[:200])
    except Exception:
        return None

    if not query_vec:
        return None

    best_score = 0.0
    best_entry = None
    now = time.time()

    for key, entry in _cache.items():
        # Check TTL
        if now - entry.get("timestamp", 0) > CACHE_TTL_SECONDS:
            continue
        # Check persona_id match
        if entry.get("persona_id") != persona_id:
            continue
        # Compare embeddings
        cached_vec = entry.get("embedding")
        if not cached_vec:
            continue
        score = _cosine_similarity(query_vec, cached_vec)
        if score > best_score and score >= CACHE_SIMILARITY_THRESHOLD:
            best_score = score
            best_entry = entry

    if best_entry:
        logger.info(
            "Semantic cache HIT (score=%.3f, saved LLM call)", best_score
        )
        return {
            "reply": best_entry["reply"],
            "similarity": round(best_score, 4),
            "original_query": best_entry["query"],
        }

    return None


def cache_store(
    query: str,
    reply: str,
    persona_id: str,
    embedding: list[float] | None = None,
) -> None:
    """Store a query-reply pair with its embedding"""
    if not query or not reply:
        return

    key = hashlib.md5(
        f"{persona_id}:{query[:100]}".encode()
    ).hexdigest()

    # If no embedding provided, skip (will be generated on next lookup)
    _cache[key] = {
        "query": query,
        "reply": reply,
        "persona_id": persona_id,
        "embedding": embedding,
        "timestamp": time.time(),
    }


def cache_stats() -> dict:
    """Return cache statistics"""
    now = time.time()
    total = len(_cache)
    active = sum(
        1 for e in _cache.values()
        if now - e.get("timestamp", 0) <= CACHE_TTL_SECONDS
    )
    return {
        "total_entries": total,
        "active_entries": active,
        "ttl_seconds": CACHE_TTL_SECONDS,
        "threshold": CACHE_SIMILARITY_THRESHOLD,
    }


def cache_clear() -> int:
    """Clear all cache entries"""
    count = len(_cache)
    _cache.clear()
    return count