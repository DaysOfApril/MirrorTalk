# MirrorTalk - Agent 工具集
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool

from app.models import MemorySource, MemorySourceType
from app.services.external_tools import web_search, get_weather, calculate, fetch_webpage, get_datetime
from app.services.memory import insert_memory, recall as do_recall

logger = logging.getLogger(__name__)


# ========== recall: 检索知识库 ==========

def create_recall_tool(agent_type: str = "friend"):
    @tool
    async def recall(
        query: Annotated[str, "检索意图或关键词"],
        limit: Annotated[int, "返回条数上限，默认10"] = 10,
    ) -> str:
        """检索知识库中的记忆。涉及用户偏好、长期事实、关系等信息时先查一下。"""
        result = await do_recall(query=query, agent_type=agent_type, limit=limit)
        if not result.items:
            return "没有找到相关记忆。"
        lines = [f"找到 {len(result.items)} 条相关记忆（{result.mode} 模式）："]
        for item in result.items:
            source_tag = f"[{item.source.value}|置信度 {item.confidence:.0%}]"
            lines.append(f"- {source_tag} {item.content}")
        return "\n".join(lines)

    return recall


# ========== remember: 写入记忆 ==========

def create_remember_tool(agent_type: str = "friend"):
    @tool
    async def remember(
        content: Annotated[str, "要记住的事实，一句话写清楚"],
        kind: Annotated[str, "类型: profile=用户画像, fact=事实, relationship=关系"] = "fact",
        importance: Annotated[float, "重要性 0~1"] = 0.5,
    ) -> str:
        """记住一条长期记忆。只在用户透露稳定偏好/身份/重要事实时使用。"""
        source_type = MemorySourceType(kind) if kind in [t.value for t in MemorySourceType] else MemorySourceType.FACT
        mem_id = insert_memory(
            source_type=source_type,
            source=MemorySource.FRIEND_SPEECH if agent_type == "friend" else MemorySource.USER_SPEECH,
            content=content,
            title=content[:40],
            importance=importance,
        )
        logger.info(f"记忆已写入: id={mem_id}, content={content[:50]}")
        return f"已记住 (id={mem_id}): {content[:60]}"

    return remember


# ========== query_profile: 查询画像 ==========

@tool
async def query_profile(persona_id: str) -> str:
    """查询用户替身画像。返回该替身的性格标签、偏好等信息。"""
    from app.services.database import get_db
    conn = get_db()
    row = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    conn.close()
    if not row:
        return f"未找到画像: {persona_id}"
    import json
    style = json.loads(row["style_json"])
    ocean = json.loads(row["ocean_json"])
    parts = [f"**{row['name']}** 的画像:"]
    if style.get("personality"):
        parts.append(f"性格: {', '.join(style['personality'])}")
    if style.get("catchphrases"):
        parts.append(f"口头禅: {', '.join(style['catchphrases'])}")
    if style.get("tone"):
        parts.append(f"语气: {style['tone']}")
    if style.get("sentence_style"):
        parts.append(f"句式: {style['sentence_style']}")
    return "\n".join(parts)


# ========== update_profile: 更新画像 ==========

@tool
async def update_profile(persona_id: str, field: str, value: str) -> str:
    """更新用户替身画像的某个字段。仅用户替身 Agent 可用。"""
    import json
    from app.services.database import get_db
    conn = get_db()
    row = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    if not row:
        conn.close()
        return f"未找到画像: {persona_id}"

    style = json.loads(row["style_json"])
    valid_fields = ["personality", "catchphrases", "sentence_style", "emoji_style", "tone"]
    if field not in valid_fields:
        conn.close()
        return f"不支持更新字段: {field}，可用字段: {valid_fields}"

    if field in ("sentence_style", "emoji_style", "tone"):
        style[field] = value
    else:
        current = style.get(field, [])
        if value not in current:
            current.append(value)
            style[field] = current

    conn.execute(
        "UPDATE personas SET style_json = ? WHERE id = ?",
        (json.dumps(style, ensure_ascii=False), persona_id),
    )
    conn.commit()
    conn.close()
    return f"画像已更新: {persona_id}.{field} -> {value}"


# ========== query_sql: SQL 查询（需门控解锁）==========

@tool
async def query_sql(
    sql: Annotated[str, "只读 SQL 查询语句，仅支持 SELECT/PRAGMA/EXPLAIN"],
    limit: Annotated[int, "返回行数上限"] = 20,
) -> str:
    """执行 SQL 查询。可查询记忆库、画像等数据库表。注意：此工具需要先使用 recall 或 remember 等结构化工具后才能解锁。"""
    from app.services.tool_policy import execute_readonly_query
    return await execute_readonly_query(sql, limit=limit)

