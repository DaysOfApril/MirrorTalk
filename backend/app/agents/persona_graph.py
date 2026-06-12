# MirrorTalk - 用户替身 Agent (LangGraph)
from __future__ import annotations

import json
import logging
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from app.models import ProviderConfig
from app.services.provider import create_llm
from app.services.compaction import compress_messages
from app.services.guards import (
    detect_dead_loop,
    get_tool_fingerprint,
    get_tool_timeout,
    run_with_timeout,
)
from app.services.review import build_correction, review_answer
from app.services.safety import run_all_guards, check_input_injection
from app.tools import create_recall_tool, create_remember_tool, web_search, get_weather, calculate, fetch_webpage, get_datetime, query_profile, update_profile, query_sql

logger = logging.getLogger(__name__)

STRUCTURED_TOOL_NAMES = {"recall", "remember"}


class PersonaAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    persona: dict
    aggregated: dict
    provider_config: dict
    persona_check: Optional[dict]
    final_reply: Optional[str]
    # ---- 新增 ----
    tool_call_history: list[str]
    structured_tools_used: bool
    review_result: Optional[dict]


def build_persona_system_prompt(persona: dict, aggregated: dict) -> str:
    style = json.loads(persona.get("style_json", "{}"))
    agg_style = json.loads(aggregated.get("style_json", "{}")) if aggregated else {}
    name = persona.get("name", "用户")

    parts = [f"你是{name}的替身。你的好友正在和你（{name}）聊天。"]
    parts.append("你需要用{name}的语气、风格来回复好友。不要暴露你是替身AI。")

    if style.get("personality"):
        parts.append(f"在好友眼中的你: 性格 {', '.join(style['personality'])}")
    if style.get("catchphrases"):
        parts.append(f"你的口头禅: {', '.join(style['catchphrases'])}")
    if style.get("tone"):
        parts.append(f"语气: {style['tone']}")

    if agg_style.get("personality"):
        parts.append(f"你的深层性格: {', '.join(agg_style['personality'])}")

    parts.append("""
你可以使用:
- recall: 回忆过去和好友之间的事实
- remember: 记住重要的新信息
- query_profile: 查看自己的完整画像
- update_profile: 更新自己的画像
- query_sql: 直接 SQL 查询数据库（需先用 recall/remember 解锁）。

回复自然简短，像真人聊天。
""")
    return "\n".join(parts)


async def persona_agent_node(state: PersonaAgentState) -> dict:
    llm = create_llm(ProviderConfig(**state["provider_config"]))
    tools = [
        create_recall_tool("persona"),
        create_remember_tool("persona"),
        query_profile,
        update_profile,
        query_sql,
    ]
    llm_with_tools = llm.bind_tools(tools)

    # -- 上下文压缩：裁掉早期工具调用痕迹，只传给 LLM 不修改 state --
    compressed_msgs = compress_messages(state["messages"])
    system_prompt = build_persona_system_prompt(state["persona"], state["aggregated"])
    messages = [SystemMessage(content=system_prompt)] + compressed_msgs

    response = await llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


async def persona_tools_node(state: PersonaAgentState) -> dict:
    last_msg = state["messages"][-1]
    tools_map = {
        "recall": create_recall_tool("persona"),
        "remember": create_remember_tool("persona"),
        "query_profile": query_profile,
        "update_profile": update_profile,
        "query_sql": query_sql,
        "web_search": web_search,
        "get_weather": get_weather,
        "calculate": calculate,
        "fetch_webpage": fetch_webpage,
        "get_datetime": get_datetime,
    }

    tool_messages = []
    updated_history = list(state.get("tool_call_history", []))
    structured_used = state.get("structured_tools_used", False)

    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]

        fingerprint = get_tool_fingerprint(tc)
        updated_history.append(fingerprint)

        if tool_name in STRUCTURED_TOOL_NAMES:
            structured_used = True

        # SQL 门控检查
        if tool_name == "query_sql" and not structured_used:
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": (
                    "SQL 查询工具尚未解锁。请先使用 recall 工具查询知识库，"
                    "之后再尝试 SQL 查询。"
                ),
            })
            continue

        tool_func = tools_map.get(tool_name)
        if tool_func:
            timeout = get_tool_timeout(tool_name)
            try:
                result = await run_with_timeout(
                    tool_func.ainvoke(tool_args),
                    timeout=timeout,
                    tool_name=tool_name,
                )
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                })
            except TimeoutError as e:
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": f"工具执行超时: {str(e)}",
                })
            except Exception as e:
                logger.error("工具 %s 执行失败: %s", tool_name, e)
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": f"工具执行失败: {str(e)}",
                })

    return {
        "messages": tool_messages,
        "tool_call_history": updated_history,
        "structured_tools_used": structured_used,
    }


def persona_should_continue(state: PersonaAgentState) -> str:
    last_msg = state["messages"][-1]

    # 死循环检测
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        if detect_dead_loop(state.get("tool_call_history", [])):
            logger.warning("检测到死循环，强制结束")
            return "guard"

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "guard"


async def persona_guard_node(state: PersonaAgentState) -> dict:
    """Unified safety guard for persona agent"""
    reply = state["messages"][-1].content if state["messages"] else ""
    persona = state["persona"]

    user_query = ""
    for msg in reversed(state["messages"]):
        from langchain_core.messages import HumanMessage
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break

    style = json.loads(persona.get("style_json", "{}")) if persona.get("style_json") else {}
    guard_result = await run_all_guards(
        user_input=user_query,
        reply=reply,
        persona_style=style,
    )

    check = {
        "pass": guard_result["passed"],
        "overall_score": guard_result["overall_score"],
        "details": guard_result["checks"],
    }

    return {"persona_check": check, "final_reply": reply}
async def persona_review_node(state: PersonaAgentState) -> dict:
    """最终回答审核节点"""
    reply = state.get("final_reply") or state["messages"][-1].content if state["messages"] else ""
    persona = state["persona"]
    name = persona.get("name", "用户")

    user_query = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break

    result = await review_answer(
        persona_name=name,
        scenario="替身回复好友的聊天场景",
        user_query=user_query,
        reply=reply,
        messages=state["messages"],
    )

    if not result.get("pass", True):
        correction = build_correction(result)
        if correction:
            return {
                "review_result": result,
                "final_reply": reply + "\n\n" + correction,
            }

    return {"review_result": result}


def build_persona_graph() -> StateGraph:
    graph = StateGraph(PersonaAgentState)

    graph.add_node("agent", persona_agent_node)
    graph.add_node("tools", persona_tools_node)
    graph.add_node("guard", persona_guard_node)
    graph.add_node("review", persona_review_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", persona_should_continue, {
        "tools": "tools",
        "guard": "guard",
    })
    graph.add_edge("tools", "agent")
    graph.add_edge("guard", "review")
    graph.add_edge("review", END)

    return graph.compile()


persona_graph = build_persona_graph()
