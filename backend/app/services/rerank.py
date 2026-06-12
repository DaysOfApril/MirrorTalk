# MirrorTalk - Rerank 服务 (本地优先 + 云端回退)
from __future__ import annotations

import logging
from typing import Optional

from app.config import settings
from app.services.database import get_config

logger = logging.getLogger(__name__)

_local_reranker: Optional[object] = None
_local_ready: bool = False


def _db(key: str, fallback: str = "") -> str:
    val = get_config(key)
    return val if val else fallback


def _load_local_reranker() -> Optional[object]:
    global _local_reranker, _local_ready
    if _local_ready:
        return _local_reranker
    try:
        from FlagEmbedding import FlagReranker
        _local_reranker = FlagReranker(settings.rerank_local_model, use_fp16=True)
        _local_ready = True
        logger.info(f"本地 Rerank 模型加载成功: {settings.rerank_local_model}")
        return _local_reranker
    except Exception as e:
        logger.info(f"本地 Rerank 不可用: {e}，将通过云端回退")
        _local_ready = True
        return None


async def rerank(
    query: str,
    documents: list[str],
    top_n: int = 10,
) -> list[dict]:
    """重排序，返回 [{index, score}]"""
    if not documents:
        return []

    if _db("rerank_mode", settings.rerank_mode) == "local":
        model = _load_local_reranker()
        if model is not None:
            pairs = [[query, doc] for doc in documents]
            scores = model.compute_score(pairs, normalize=True)
            if isinstance(scores, float):
                scores = [scores]
            ranked = sorted(
                [{"index": i, "score": float(s)} for i, s in enumerate(scores)],
                key=lambda x: x["score"],
                reverse=True,
            )
            return ranked[:top_n]

    # 云端回退
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_db('rerank_remote_base_url', settings.rerank_remote_base_url)}/rerank",
            headers={"Authorization": f"Bearer {_db('rerank_remote_api_key', settings.rerank_remote_api_key)}"},
            json={
                "model": _db("rerank_remote_model", settings.rerank_remote_model),
                "query": query,
                "documents": documents,
                "top_n": top_n,
            },
            timeout=30,
        )
        data = resp.json()
        results = data.get("results", [])
        return [{"index": r.get("index", 0), "score": r.get("relevance_score", 0)} for r in results]
