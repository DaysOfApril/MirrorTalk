# MirrorTalk - GraphRAG: 知识图谱增强检索
""""实体关系抽取 → networkx 图存储 → 图遍历检索"""
from __future__ import annotations

import json
import logging
from typing import Optional

import networkx as nx
from langchain_core.messages import SystemMessage

from app.models import ProviderConfig, MemoryItem
from app.services.provider import create_llm

logger = logging.getLogger(__name__)

# 全局图实例
_knowledge_graph: Optional[nx.Graph] = None

ENTITY_EXTRACTION_PROMPT = """"从以下文本中提取实体和关系，构建知识图谱三元组。

文本:
{text}

规则:
- 实体: 人名、物名、地点、事件、偏好、属性值
- 关系: likes(喜欢), dislikes(讨厌), friend_of(是好友), has_trait(有的特质), happened_at(发生在), prefers(偏好)
- 只提取明确提到的，不要编造

输出 JSON 数组（只输出 JSON）:
[{{"head": "实体名", "relation": "关系类型", "tail": "实体名或属性值"}}]
"""


def get_graph() -> nx.Graph:
    global _knowledge_graph
    if _knowledge_graph is None:
        _knowledge_graph = nx.Graph()
    return _knowledge_graph


async def extract_triples(text: str) -> list[dict]:
    """"从文本中提取 (head, relation, tail) 三元组"""
    if not text or len(text) < 10:
        return []

    try:
        llm = create_llm(ProviderConfig())
        resp = await llm.ainvoke([
            SystemMessage(content=ENTITY_EXTRACTION_PROMPT.format(text=text[:1500])),
        ])
        content = resp.content.strip()
        if "`" in content:
            content = content.split("`")[1]
            if content.startswith("json"):
                content = content[4:]

        triples = json.loads(content)
        if isinstance(triples, list):
            return triples
    except Exception as e:
        logger.debug("实体抽取失败: %s", e)

    return []


def add_triples_to_graph(triples: list[dict]) -> int:
    """"将三元组加入知识图谱，返回新增边数"""
    g = get_graph()
    count = 0
    for t in triples:
        head = t.get("head", "").strip()
        rel = t.get("relation", "related_to").strip()
        tail = t.get("tail", "").strip()
        if not head or not tail:
            continue

        # 添加节点
        if not g.has_node(head):
            g.add_node(head, type="entity")
        if not g.has_node(tail):
            g.add_node(tail, type="entity")

        # 添加边
        if not g.has_edge(head, tail):
            g.add_edge(head, tail, relation=rel, weight=1.0)
            count += 1
        else:
            # 加强已有边
            g[head][tail]["weight"] = g[head][tail].get("weight", 1.0) + 0.5

    return count


async def build_graph_from_memories(items: list[MemoryItem]) -> int:
    """"批量从 MemoryItem 构建知识图谱"""
    total = 0
    for item in items:
        triples = await extract_triples(item.content)
        if triples:
            added = add_triples_to_graph(triples)
            total += added
    logger.info("GraphRAG 构建: %d 条记忆 → %d 条新边", len(items), total)
    return total


def graph_search(
    query_entities: list[str],
    max_hops: int = 2,
    max_results: int = 10,
) -> list[dict]:
    """"图遍历检索：从查询实体出发，沿边遍历找关联知识"""
    g = get_graph()
    if g.number_of_nodes() == 0:
        return []

    results = []
    seen = set()

    for entity in query_entities:
        if not g.has_node(entity):
            # 模糊匹配
            matches = [n for n in g.nodes() if entity.lower() in n.lower()]
            for match in matches[:3]:
                entity = match
                break

        if not g.has_node(entity):
            continue

        # BFS 遍历 max_hops 跳
        visited = {entity: 0}
        queue = [(entity, 0)]

        while queue:
            current, hop = queue.pop(0)
            if hop > max_hops:
                continue

            for neighbor in g.neighbors(current):
                if neighbor in visited:
                    continue
                visited[neighbor] = hop + 1
                edge_data = g.get_edge_data(current, neighbor)
                relation = edge_data.get("relation", "related_to") if edge_data else "related_to"
                weight = edge_data.get("weight", 1.0) if edge_data else 1.0

                result_key = f"{current}|{relation}|{neighbor}"
                if result_key not in seen:
                    seen.add(result_key)
                    results.append({
                        "head": current,
                        "relation": relation,
                        "tail": neighbor,
                        "hops": hop + 1,
                        "weight": weight,
                    })

                if hop + 1 < max_hops:
                    queue.append((neighbor, hop + 1))

    # 按跳数和权重排序
    results.sort(key=lambda r: (r["hops"], -r["weight"]))
    return results[:max_results]


def format_graph_results(results: list[dict]) -> str:
    """"格式化图检索结果"""
    if not results:
        return "（图谱中未找到相关知识）"

    lines = [f"知识图谱检索 ({len(results)} 条):"]
    for r in results:
        lines.append(f"  {r['head']} --[{r['relation']}]--> {r['tail']}")
    return "\n".join(lines)


def graph_stats() -> dict:
    g = get_graph()
    return {
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "density": round(nx.density(g), 4) if g.number_of_nodes() > 1 else 0.0,
    }
