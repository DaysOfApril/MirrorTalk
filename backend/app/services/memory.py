from __future__ import annotations

# MirrorTalk - 记�服务 (混合检索: FTS + 向量 -> RRF -> Rerank)
import uuid

import json
import logging

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.models import MemoryItem, MemorySource, MemorySourceType, RecallResult
from app.services.database import get_db
from app.services.hyde import generate_hypothetical_doc
from app.services.graph_rag import graph_search, format_graph_results, extract_triples

logger = logging.getLogger(__name__)

_chroma_client: chromadb.PersistentClient | None = None


def _get_chroma() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=str(settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


def _get_collection() -> chromadb.Collection:
    client = _get_chroma()
    return client.get_or_create_collection(
        name="memory_items",
        metadata={"hnsw:space": "cosine"},
    )


def _row_to_item(row) -> MemoryItem:
    return MemoryItem(
        id=row["id"],
        source_type=MemorySourceType(row["source_type"]),
        source=MemorySource(row["source"]),
        title=row["title"],
        content=row["content"],
        session_id=row["session_id"],
        confidence=row["confidence"],
        importance=row["importance"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
    )


# ========== 写入 ==========

def insert_memory(
    source_type: MemorySourceType,
    source: MemorySource,
    content: str,
    title: str = "",
    session_id: str | None = None,
    confidence: float = 0.5,
    importance: float = 0.5,
    parent_id: int | None = None,
    chunk_index: int = 0,
    chunk_count: int = 1,
) -> int:
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO memory_items (source_type, source, title, content, session_id, confidence, importance, tags, parent_id, chunk_index, chunk_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)""",
        (source_type.value, source.value, title, content, session_id, confidence, importance, parent_id, chunk_index, chunk_count),
    )
    conn.commit()
    mem_id = cur.lastrowid
    conn.close()
    return mem_id


# ========== 混合检索 ==========

async def recall(
    query: str,
    agent_type: str = "friend",
    session_id: str | None = None,
    limit: int = 10,
) -> RecallResult:
    """混合检索��FTS + 向量 -> RRF 融合 -> Rerank 精排"""
    candidate_limit = min(50, limit * 3)
    trace_id = uuid.uuid4().hex[:12]  # ???????? trace_id

    
    # ---- 0. HyDE 查询改写（可选）----
    search_query = query
    try:
        hypo = await generate_hypothetical_doc(query)
        if hypo and hypo != query:
            search_query = hypo
            logger.debug("HyDE 改写: %s -> %s", query[:30], hypo[:60])
    except Exception:
        pass

    # ---- 1. 关键词 FTS 检索 ----
    fts_items = _fts_search(search_query, agent_type, session_id, candidate_limit)

    # ---- 2. 尝试向量检索 ----
    vector_items: list[MemoryItem] = []
    mode = "keyword"
    try:
        from app.services.embedding import embed_query
        q_vec = await embed_query(query)
        if q_vec:
            vector_items = _vector_search(q_vec, agent_type, session_id, candidate_limit)
            if vector_items:
                mode = "hybrid"
    except Exception as e:
        logger.info(f"向量检索跳�: {e}")

    
    # ---- 3. 知识图谱检索 (GraphRAG) ----
    graph_items: list[MemoryItem] = []
    try:
        # 从 query 中提取关键实体
        triples = await extract_triples(query)
        entities = set()
        for t in triples:
            entities.add(t.get("head", ""))
            entities.add(t.get("tail", ""))
        entities.discard("")

        if entities:
            graph_results = graph_search(list(entities)[:5], max_hops=2, max_results=10)
            if graph_results:
                # 将图谱结果转换为可引用的格式
                graph_context = format_graph_results(graph_results)
                logger.debug("GraphRAG 命中: %d 条", len(graph_results))
    except Exception:
        pass

    # ---- 3. RRF 融合 ----
    if mode == "hybrid":
        merged, rrf_scores = _rrf_fusion(
            fts_items, vector_items,
            weight_fts=settings.rrf_weight_fts,
            weight_vector=settings.rrf_weight_vector,
        )
    else:
        merged = fts_items

    # ---- 4. Rerank 精排��失败时降级到 RRF 截断�� ----
    if len(merged) > limit:
        merged = await _rerank_items(search_query, merged, limit, rrf_scores)

    retrieval_info = {
        "keyword_count": len(fts_items),
        "vector_count": len(vector_items) if mode == "hybrid" else 0,
        "rrf_k": settings.rrf_k,
        "rrf_weight_fts": settings.rrf_weight_fts,
        "rrf_weight_vector": settings.rrf_weight_vector,
    }

    _log_retrieval_summary(search_query, len(merged), mode, retrieval_info, trace_id)

    return RecallResult(
        items=merged,
        mode=mode,
        retrieval_info=retrieval_info,
        trace_id=trace_id,
    )


def _fts_search(
    query: str,
    agent_type: str,
    session_id: str | None,
    limit: int,
) -> list[MemoryItem]:
    conn = get_db()
    # 权限��
    if agent_type == "friend":
        sources = [MemorySource.FRIEND_SPEECH.value, MemorySource.SHARED.value, MemorySource.EXTERNAL_FILE.value]
    else:
        sources = [s.value for s in MemorySource]

    placeholders = ",".join("?" for _ in sources)
    try:
        rows = conn.execute(
            f"""SELECT m.* FROM memory_fts f
                JOIN memory_items m ON m.id = f.rowid
                WHERE memory_fts MATCH ? AND m.source IN ({placeholders})
                ORDER BY rank LIMIT ?""",
            [query] + sources + [limit],
        ).fetchall()
    except Exception:
        # FTS 查询语法错误时回退 LIKE
        like_q = f"%{query}%"
        rows = conn.execute(
            f"""SELECT * FROM memory_items
                WHERE (content LIKE ? OR title LIKE ?) AND source IN ({placeholders})
                ORDER BY importance DESC LIMIT ?""",
            [like_q, like_q] + sources + [limit],
        ).fetchall()
    conn.close()
    return [_row_to_item(r) for r in rows]


def _vector_search(
    query_vec: list[float],
    agent_type: str,
    session_id: str | None,
    limit: int,
) -> list[MemoryItem]:
    collection = _get_collection()
    where_filter: dict = {}
    if agent_type == "friend":
        where_filter["source"] = {"$in": ["friend_speech", "shared", "external_file"]}

    results = collection.query(
        query_embeddings=[query_vec],
        n_results=limit,
        where=where_filter if where_filter else None,
    )
    conn = get_db()
    items: list[MemoryItem] = []
    if results["ids"] and results["ids"][0]:
        id_list = [int(i) for i in results["ids"][0]]
        placeholders = ",".join("?" for _ in id_list)
        rows = conn.execute(
            f"SELECT * FROM memory_items WHERE id IN ({placeholders})",
            id_list,
        ).fetchall()
        # �持向量相似度顺序
        row_map = {r["id"]: r for r in rows}
        items = [_row_to_item(row_map[i]) for i in id_list if i in row_map]
    conn.close()
    return items


def _rrf_fusion(
    fts_items: list[MemoryItem],
    vec_items: list[MemoryItem],
    k: int | None = None,
    weight_fts: float = 1.0,
    weight_vector: float = 1.0,
):
    """
    RRF (Reciprocal Rank Fusion) 融合

    参数:
        k: RRF 常数���认� settings.rrf_k �取
        weight_fts: FTS �果权重
        weight_vector: 向量�果权重
    """
    k = k or settings.rrf_k
    scores: dict[int, float] = {}
    id_to_item: dict[int, MemoryItem] = {}
    rrf_scores: dict[int, float] = {}

    for rank, item in enumerate(fts_items):
        score = 1.0 / (k + rank + 1)
        scores[item.id] = scores.get(item.id, 0) + score * weight_fts
        id_to_item[item.id] = item
        rrf_scores[item.id] = rrf_scores.get(item.id, 0) + score

    for rank, item in enumerate(vec_items):
        score = 1.0 / (k + rank + 1)
        scores[item.id] = scores.get(item.id, 0) + score * weight_vector
        id_to_item[item.id] = item
        rrf_scores[item.id] = rrf_scores.get(item.id, 0) + score

    sorted_ids = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)
    return [id_to_item[i] for i in sorted_ids], rrf_scores
def _record_retrieval_metrics(success: bool, item_count: int) -> None:
    """?? Rerank ????"""
    global _retrieval_call_count, _rerank_success_count, _rerank_fail_count
    if not settings.retrieval_metrics_enabled:
        return
    _retrieval_call_count += 1
    if success:
        _rerank_success_count += 1
    else:
        _rerank_fail_count += 1

    if _retrieval_call_count % settings.retrieval_metrics_log_interval == 0:
        total = _rerank_success_count + _rerank_fail_count
        success_rate = _rerank_success_count / total * 100 if total > 0 else 0.0
        logger.info(
            f"[????] Rerank ??: {total}, ???: {success_rate:.1f}%"
            f" (??={_rerank_success_count}, ??={_rerank_fail_count})"
        )


def _log_retrieval_summary(
    query: str, result_count: int, mode: str, info: dict, trace_id: str = ""
) -> None:
    """??????????? trace_id?"""
    logger.debug(
        f"[??] trace_id={trace_id} mode={mode} query={query[:40]!r} "
        f"results={result_count} k={info.get('rrf_k')} "
        f"fts_w={info.get('rrf_weight_fts')} vec_w={info.get('rrf_weight_vector')}"
    )


def get_retrieval_stats() -> dict:
    """????????????? API?"""
    total = _rerank_success_count + _rerank_fail_count
    return {
        "total_calls": _retrieval_call_count,
        "rerank_success": _rerank_success_count,
        "rerank_fail": _rerank_fail_count,
        "rerank_success_rate": round(_rerank_success_count / total, 3) if total > 0 else 0.0,
    }


async def _rerank_items(
    query: str,
    items: list[MemoryItem],
    top_n: int,
    rrf_scores: dict[int, float] | None = None,
) -> list[MemoryItem]:
    """Rerank ??????? RRF score ????"""
    from app.services.rerank import rerank as do_rerank

    docs = [f"{i.title}\n{i.content}" for i in items]
    try:
        result = await do_rerank(query, docs, top_n=top_n)
        _record_retrieval_metrics(True, len(items))
        return [items[r["index"]] for r in result]
    except Exception as e:
        logger.warning(f"Rerank ?????? RRF ??: {e}")
        _record_retrieval_metrics(False, len(items))
        if rrf_scores:
            scored = [(item, rrf_scores.get(item.id, 0.0)) for item in items]
            scored.sort(key=lambda x: x[1], reverse=True)
            return [item for item, _ in scored[:top_n]]
        return items[:top_n]

