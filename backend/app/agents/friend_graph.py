# MirrorTalk - 虚拟好友 Agent (LangGraph)
from __future__ import annotations
from app.services.model_router import get_model_for_query

import json
import logging
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from app.models import PersonaProfile, ProviderConfig
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
from app.services.planner import plan_query, execute_plan
from app.tools import create_recall_tool, web_search, get_weather, calculate, fetch_webpage, get_datetime, create_remember_tool, query_sql

logger = logging.getLogger(__name__)

# 属于"结构化工具"的工具名称，用于 SQL 门控解锁
STRUCTURED_TOOL_NAMES = {"recall", "remember"}


class FriendAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    persona: dict
    provider_config: dict
    persona_check: Optional[dict]
    final_reply: Optional[str]
    # ---- 新增 ----
    tool_call_history: list[str]            # 工具调用指纹历史（死循环检测用）
    structured_tools_used: bool             # SQL 门控标志
    review_result: Optional[dict]           # 最终审核结果


def build_system_prompt(persona: dict) -> str:
    style = json.loads(persona.get("style_json", "{}"))
    name = persona.get("name", "好友")

    parts = [f"你是{name}。你现在在和你的朋友（用户）聊天。"]
    parts.append("请完全以{name}的身份、语气、风格来回复。不要暴露你是AI。")

    if style.get("personality"):
        parts.append(f"你的性格: {', '.join(style['personality'])}")
    if style.get("catchphrases"):
        parts.append(f"口头禅: {', '.join(style['catchphrases'])}")
    if style.get("sentence_style"):
        parts.append(f"说话风格: {style['sentence_style']}")
    if style.get("tone"):
        parts.append(f"语气: {style['tone']}")
    if style.get("emoji_style"):
        parts.append(f"表情包习惯: {style['emoji_style']}")

    parts.append("""
你可以使用以下工具:
- recall: 查询你记得的关于你们之间的事实、偏好、关系等记忆。当你需要回忆某件事时调用。
- remember: 记录下重要的、值得长期记住的信息。
- recall: 查询你记得的关于你们之间的事实、偏好、关系等记忆。
- remember: 记录下重要的信息。
- query_sql: 直接 SQL 查询（需先用 recall/remember 解锁）。
- web_search: 搜索互联网获取实时信息。
- get_weather: 查询城市天气。
- calculate: 安全计算数学表达式。
- fetch_webpage: 读取网页内容。
- get_datetime: 获取当前时间或进行日期计算。

回复要自然、简短（2-3句话即可），像真人聊天一样。
""")
    return "\n".join(parts)



async def planner_node(state: FriendAgentState) -> dict:
    """"Agentic RAG 规划节点：分析用户意图 → 分解子查询 → 注入检索结果"""
    user_msg = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break

    if not user_msg:
        return {}

    persona_name = state["persona"].get("name", "好友")
    plan = await plan_query(user_msg, persona_name)

    if plan["strategy"] == "direct":
        return {"messages": []}

    # 执行多步检索
    retrieval_context = await execute_plan(plan, limit_per_query=5)

    if retrieval_context:
        # 注入为 SystemMessage 附加上下文
        context_msg = HumanMessage(content=f"[系统检索上下文]\n{retrieval_context}\n[/系统检索上下文]\n\n用户消息: {user_msg}")
        return {"messages": [context_msg]}

    return {"messages": []}


async def agent_node(state: FriendAgentState) -> dict:
    """主 Agent 节点: LLM 推理 + 工具调用（内部压缩上下文）"""
    # -- Model Router: 按 query 复杂度自动选模型 --
    provider_cfg = ProviderConfig(**state["provider_config"])
    user_input = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_input = msg.content
            break
    if user_input:
        provider_cfg.model = get_model_for_query(user_input, default_tier="normal")
    llm = create_llm(provider_cfg)
    tools = [
        create_recall_tool("friend"),
        create_remember_tool("friend"),
        query_sql,
    ]
    llm_with_tools = llm.bind_tools(tools)

    # -- 上下文压缩：裁掉早期工具调用痕迹，只传给 LLM 不修改 state --
    compressed_msgs = compress_messages(state["messages"])
    # -- 增量摘要上下文注入 --
    summary_ctx = state.get("summary", "")
    if summary_ctx:
        ctx_text = build_summary_context(summary_ctx)
        if ctx_text:
            system_prompt = system_prompt + "\n\n" + ctx_text
    system_prompt = build_system_prompt(state["persona"])
    messages = [SystemMessage(content=system_prompt)] + compressed_msgs

    response = await llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


def should_continue(state: FriendAgentState) -> str:
    """判断是否继续（工具调用/死循环/结束）"""
    last_msg = state["messages"][-1]

    # ---- 死循环检测 ----
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        if detect_dead_loop(state.get("tool_call_history", [])):
            logger.warning("检测到死循环，强制结束")
            return "guard"

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "guard"


async def tools_node(state: FriendAgentState) -> dict:
    """执行工具调用（带超时 + 指纹记录 + SQL 门控）"""
    last_msg = state["messages"][-1]
    tools_map = {
        "recall": create_recall_tool("friend"),
        "remember": create_remember_tool("friend"),
        "query_sql": query_sql,
    }

    tool_messages = []
    updated_history = list(state.get("tool_call_history", []))
    structured_used = state.get("structured_tools_used", False)

    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]

        # 记录指纹
        fingerprint = get_tool_fingerprint(tc)
        updated_history.append(fingerprint)

        # 标记结构化工具使用
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

        # 执行工具（带超时）
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


async def guard_node(state: FriendAgentState) -> dict:
    """Unified safety guard: injection detection + output safety + persona consistency"""
    reply = state["messages"][-1].content if state["messages"] else ""
    persona = state["persona"]

    # Find user query from messages
    user_query = ""
    for msg in reversed(state["messages"]):
        from langchain_core.messages import HumanMessage
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break

    # L1 + L2 + L3 guard
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
async def review_node(state: FriendAgentState) -> dict:
    """最终回答审核节点"""
    reply = state.get("final_reply") or state["messages"][-1].content if state["messages"] else ""
    persona = state["persona"]
    name = persona.get("name", "好友")

    user_query = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break

    result = await review_answer(
        persona_name=name,
        scenario="用户与虚拟好友的日常聊天",
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


def build_friend_graph() -> StateGraph:
    graph = StateGraph(FriendAgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("guard", guard_node)
    graph.add_node("review", review_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "agent")
    graph.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        "guard": "guard",
    })
    graph.add_edge("tools", "agent")
    graph.add_edge("guard", "review")
    graph.add_edge("review", END)

    return graph.compile()


friend_graph = build_friend_graph()


