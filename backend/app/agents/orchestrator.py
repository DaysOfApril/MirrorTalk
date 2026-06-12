# MirrorTalk - 多智能体协作编排器
""""协调 friend agent 和 persona agent 完成复杂任务"""
from __future__ import annotations

import json
import logging
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from app.models import ProviderConfig
from app.services.provider import create_llm

logger = logging.getLogger(__name__)

ORCHESTRATOR_PROMPT = """"你是多智能体协作编排器。用户提出了一个需要多个视角才能回答的问题。

用户输入: {user_input}

可用 Agent:
- friend_agent: 以好友的口吻和视角回答问题
- persona_agent: 以用户替身的口吻和视角回答问题

请将任务分解，决定调用哪些 Agent，并给出每个 Agent 的输入。

输出 JSON（只输出 JSON）:
{{
    "reasoning": "分解理由",
    "tasks": [
        {{"agent": "friend_agent|persona_agent", "query": "子任务输入"}}
    ]
}}
"""

MERGE_PROMPT = """"你是多智能体协作合并器。以下是不同 Agent 对用户问题的回答，请合并为一个整合回复。

用户原始问题: {user_input}

各 Agent 回复:
{agent_replies}

合并规则:
- 保持各 Agent 的视角和语气
- 如果视角有冲突，指出差异
- 最终回复自然流畅

输出整合回复（直接输出回复文本，不要 JSON）:"""


class OrchestratorState(TypedDict):
    messages: Annotated[list, add_messages]
    persona: dict
    friend_persona: dict
    provider_config: dict
    final_reply: str | None


async def decompose_node(state: OrchestratorState) -> dict:
    """"分析用户意图，将任务分解给各 Agent"""
    user_input = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_input = msg.content
            break

    if not user_input:
        return {"messages": []}

    llm = create_llm(ProviderConfig(**state["provider_config"]))
    resp = await llm.ainvoke([
        SystemMessage(content=ORCHESTRATOR_PROMPT.format(user_input=user_input[:500])),
    ])

    try:
        content = resp.content.strip()
        if "`" in content:
            content = content.split("`")[1]
            if content.startswith("json"):
                content = content[4:]
        plan = json.loads(content)
        tasks = plan.get("tasks", [])
        reasoning = plan.get("reasoning", "")

        logger.info("编排器分解: %s → %d 子任务", reasoning, len(tasks))
        return {
            "messages": [
                AIMessage(content=f"[编排计划] {reasoning}"),
                HumanMessage(content=f"[子任务分配]\n{json.dumps(tasks, ensure_ascii=False)}"),
            ],
        }
    except Exception as e:
        logger.info("编排器分解失败: %s", e)
        return {"messages": [HumanMessage(content=user_input)]}


async def exec_friend_node(state: OrchestratorState) -> dict:
    """"执行 friend agent 视角的回复"""
    from app.agents.friend_graph import friend_graph, build_system_prompt as friend_prompt

    user_input = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_input = msg.content
            break

    persona = state.get("friend_persona", state.get("persona", {}))
    prompt = friend_prompt(persona)
    llm = create_llm(ProviderConfig(**state["provider_config"]))

    resp = await llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"[以好友视角回答]\n{user_input}"),
    ])

    return {"messages": [AIMessage(content=f"[好友视角]\n{resp.content}")]}


async def exec_persona_node(state: OrchestratorState) -> dict:
    """"执行 persona agent 视角的回复"""
    from app.agents.persona_graph import build_persona_system_prompt

    user_input = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_input = msg.content
            break

    persona = state.get("persona", {})
    aggregated = person.get("aggregated", {})
    prompt = build_persona_system_prompt(persona, aggregated)
    llm = create_llm(ProviderConfig(**state["provider_config"]))

    resp = await llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"[以替身视角回答]\n{user_input}"),
    ])

    return {"messages": [AIMessage(content=f"[替身视角]\n{resp.content}")]}


async def merge_node(state: OrchestratorState) -> dict:
    """"合并双 Agent 的输出"""
    user_input = ""
    agent_replies = []

    for msg in state["messages"]:
        if isinstance(msg, HumanMessage) and not msg.content.startswith("["):
            user_input = msg.content
        elif isinstance(msg, AIMessage):
            agent_replies.append(msg.content)

    reply_text = "\n\n---\n\n".join(agent_replies[-2:])  # 最近两条

    # 可选: LLM 合并
    try:
        llm = create_llm(ProviderConfig(**state["provider_config"]))
        resp = await llm.ainvoke([
            SystemMessage(content=MERGE_PROMPT.format(
                user_input=user_input or "帮我分析",
                agent_replies=reply_text[:3000],
            )),
        ])
        merged = resp.content.strip()
    except Exception:
        merged = reply_text

    return {"final_reply": merged}


def build_orchestrator_graph() -> StateGraph:
    graph = StateGraph(OrchestratorState)

    graph.add_node("decompose", decompose_node)
    graph.add_node("friend_agent", exec_friend_node)
    graph.add_node("persona_agent", exec_persona_node)
    graph.add_node("merge", merge_node)

    graph.set_entry_point("decompose")

    # 分解后并行调用双 Agent
    graph.add_edge("decompose", "friend_agent")
    graph.add_edge("decompose", "persona_agent")

    # 双 Agent 汇合到 merge
    graph.add_edge("friend_agent", "merge")
    graph.add_edge("persona_agent", "merge")

    graph.add_edge("merge", END)

    return graph.compile()


orchestrator_graph = build_orchestrator_graph()
