# MirrorTalk - Retrieval Evaluation Script (MRR, Recall@K, NDCG@K)
import json, sys, math, asyncio
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.memory import recall
from app.models import EvalQuery, RetrievalEvalResult
from app.services.database import init_db


def load_eval_dataset(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    queries = []
    for q in data.get("queries", []):
        queries.append(EvalQuery(
            id=q.get("id", "unknown"),
            query=q.get("query", ""),
            relevant_ids=q.get("relevant_ids", []),
            relevance_scores=q.get("relevance_scores", []),
        ))
    return queries


def recall_at_k(retrieved_ids, relevant_ids, k):
    if not relevant_ids:
        return 0.0
    hit = sum(1 for rid in retrieved_ids[:k] if rid in relevant_ids)
    return hit / len(relevant_ids)


def dcg_at_k(ranks, k):
    ranks = ranks[:k]
    dcg = ranks[0] if ranks else 0.0
    for i, rel in enumerate(ranks[1:], start=2):
        dcg += rel / math.log2(i)
    return dcg


def ndcg_at_k(retrieved_ids, relevance, k):
    actual_ranks = [relevance.get(rid, 0) for rid in retrieved_ids[:k]]
    ideal_ranks = sorted(relevance.values(), reverse=True)[:k]
    actual_dcg = dcg_at_k(actual_ranks, k)
    ideal_dcg = dcg_at_k(ideal_ranks, k)
    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0


async def run_eval(dataset_path="", top_k=None):
    if top_k is None:
        top_k = [1, 3, 5, 10]
    if not dataset_path:
        dataset_path = str(backend_dir / "data" / "eval" / "queries.json")
    init_db()
    queries = load_eval_dataset(dataset_path)
    if not queries:
        print("[WARN] No eval queries found")
        return RetrievalEvalResult()
    print(f"Loaded {len(queries)} eval queries, top_k={top_k}")
    print("=" * 60)
    max_k = max(top_k)
    total_mrr = 0.0
    total_recall = {k: 0.0 for k in top_k}
    total_ndcg = {5: 0.0, 10: 0.0}
    for q in queries:
        if not q.query.strip():
            continue
        result = await recall(query=q.query, limit=max_k)
        retrieved_ids = [item.id for item in result.items]
        relevant_set = set(q.relevant_ids)
        rr = 0.0
        for rank, rid in enumerate(retrieved_ids[:max_k], start=1):
            if rid in relevant_set:
                rr = 1.0 / rank
                break
        total_mrr += rr
        for k in top_k:
            total_recall[k] += recall_at_k(retrieved_ids, relevant_set, k)
        relevance = {}
        for idx, rid in enumerate(q.relevant_ids):
            relevance[rid] = q.relevance_scores[idx] if idx < len(q.relevance_scores) else 1
        for k in [5, 10]:
            if k <= max_k:
                total_ndcg[k] += ndcg_at_k(retrieved_ids, relevance, k)
    n = len(queries)
    return RetrievalEvalResult(
        mrr=round(total_mrr / n, 4),
        recall_at_1=round(total_recall[1] / n, 4),
        recall_at_3=round(total_recall[3] / n, 4),
        recall_at_5=round(total_recall[5] / n, 4),
        recall_at_10=round(total_recall[10] / n, 4),
        ndcg_at_5=round(total_ndcg[5] / n, 4),
        ndcg_at_10=round(total_ndcg[10] / n, 4),
        query_count=n,
    )

async def main():
    result = await run_eval()
    print("=" * 60)
    print("Evaluation Results:")
    print(f"  Queries:          {result.query_count}")
    print(f"  MRR:              {result.mrr:.4f}")
    print(f"  Recall@1:         {result.recall_at_1:.4f}")
    print(f"  Recall@3:         {result.recall_at_3:.4f}")
    print(f"  Recall@5:         {result.recall_at_5:.4f}")
    print(f"  Recall@10:        {result.recall_at_10:.4f}")
    print(f"  NDCG@5:           {result.ndcg_at_5:.4f}")
    print(f"  NDCG@10:          {result.ndcg_at_10:.4f}")
    print("=" * 60)
    out_path = Path(backend_dir / "data" / "eval" / "latest_result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)
    print(f"Result saved to: {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
