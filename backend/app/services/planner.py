# MirrorTalk - Agentic RAG Planner 节点
""""查询规划节点：分析用户意图 → 分解子查询 → 执行检索 → 聚合结果"""
from __future__ import annotations

import json
import logging
from typing import Annotated

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from app.models import ProviderConfig
from app.services.provider import create_llm
from app.services.memory import recall as do_recall

logger = logging.getLogger(__name__)

PLANNER_PROMPT = """"你是一个查询规划助手。分析用户的输入，决定是否需要多步检索。

用户输入：{user_input}

判断规则：
1. 简单问候/闲聊 → strategy: "direct"（不需要检索）
2. 单一事实查询 → strategy: "single"（一条查询即可）
3. 需要对比/关联多个事实 → strategy: "multi_hop"（拆成多条子查询）
4. 需要反思/追问 → strategy: "reflection"（先搜一次，看结果再搜）

输出 JSON（只输出 JSON，不要其他内容）：
{{
    "strategy": "direct|single|multi_hop|reflection",
    "reasoning": "一句话说明为什么选这个策略",
    "sub_queries": ["子查询1", "子查询2"]
}}
"""


async def plan_query(user_input: str, persona_name: str = "") -> dict:
    """"调用 LLM 规划检索策略"""
    if not user_input or len(user_input) < 3:
        return {"strategy": "direct", "reasoning": "输入太短", "sub_queries": []}

    # 快速启发式：短问候直接跳过
    short_greetings = {"你好", "在吗", "hi", "hello", "早", "晚安", "拜拜", "嗯", "好"}
    if user_input.strip() in short_greetings:
        return {"strategy": "direct", "reasoning": "短问候", "sub_queries": []}

    try:
        llm = create_llm(ProviderConfig())
        resp = await llm.ainvoke([
            SystemMessage(content=PLANNER_PROMPT.format(user_input=user_input[:500])),
        ])
        content = resp.content.strip()
        if "`" in content:
            content = content.split("`")[1]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content)
        return {
            "strategy": result.get("strategy", "single"),
            "reasoning": result.get("reasoning", ""),
            "sub_queries": result.get("sub_queries", [user_input]),
        }
    except Exception as e:
        logger.info("规划器降级为 single: %s", e)
        return {
            "strategy": "single",
            "reasoning": "规划器降级",
            "sub_queries": [user_input],
        }


async def execute_plan(plan: dict, limit_per_query: int = 5) -> str:
    """"执行检索计划，聚合结果"""
    strategy = plan.get("strategy", "direct")
    sub_queries = plan.get("sub_queries", [])

    if strategy == "direct" or not sub_queries:
        return ""

    all_items = []
    seen_ids = set()

    for sq in sub_queries[:3]:  # 最多 3 条子查询
        result = await do_recall(query=sq, limit=limit_per_query)
        for item in result.items:
            if item.id not in seen_ids:
                all_items.append(item)
                seen_ids.add(item.id)

    if not all_items:
        return "（未找到相关记忆）"

    lines = [f"检索规划: {plan.get('reasoning', '')}", f"执行 {len(sub_queries)} 条子查询，共找到 {len(all_items)} 条记忆："]
    for item in all_items[:10]:
        source_tag = f"[{item.source.value}]"
        lines.append(f"- {source_tag} {item.content[:120]}")
    return "\n".join(lines)
