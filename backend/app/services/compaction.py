# MirrorTalk - 上下文压缩（增量摘要版）
""""Sliding window + LLM 增量摘要：既保最近窗口，又不丢早期关键信息"""
from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.models import ProviderConfig
from app.services.provider import create_llm

logger = logging.getLogger(__name__)

MAX_ROUNDS = 4
SUMMARY_EVERY_N_ROUNDS = 6  # 每 N 轮触发一次摘要


def compress_messages(messages: list, max_rounds: int = MAX_ROUNDS) -> list:
    """"Sliding window：保留最近 max_rounds 轮 + SystemMessage"""
    if not messages:
        return messages

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    other_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

    if not other_msgs:
        return messages

    human_indices = [i for i, m in enumerate(other_msgs) if isinstance(m, HumanMessage)]

    if len(human_indices) <= max_rounds:
        return messages

    cut_index = human_indices[-max_rounds]
    trimmed = other_msgs[cut_index:]
    result = system_msgs + trimmed
    logger.debug("消息压缩: %d → %d 条", len(messages), len(result))
    return result


async def summarize_messages(
    messages: list,
    existing_summary: str = "",
) -> str:
    """"LLM 增量摘要：将对话压缩为结构化摘要"""
    if not messages:
        return existing_summary

    # 提取人类可读对话
    chat_lines = []
    for msg in messages:
        role = "用户" if isinstance(msg, HumanMessage) else "AI" if isinstance(msg, AIMessage) else "系统"
        content = msg.content if hasattr(msg, "content") else str(msg)
        if content and len(str(content)) > 2:
            chat_lines.append(f"[{role}]: {str(content)[:300]}")

    if not chat_lines:
        return existing_summary

    chat_text = "\n".join(chat_lines)

    prompt = """你是对话摘要助手。请把以下对话的关键信息整合进已有摘要。
只记录值得长期记住的事实：用户偏好、身份信息、重要关系、关键事件。
不要记录寒暄、问候、日常闲聊。

已有摘要: {existing}

新对话:
{chat_text}

输出更新后的摘要（只输出摘要文本，JSON 格式）：
{{"summary": "..."}}
"""

    try:
        llm = create_llm(ProviderConfig())
        resp = await llm.ainvoke([
            SystemMessage(content=prompt.format(
                existing=existing_summary or "（无）",
                chat_text=chat_text[:4000],
            )),
        ])
        import json
        content = resp.content.strip()
        if "`" in content:
            content = content.split("`")[1]
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content)
        summary = data.get("summary", "")
        logger.info("对话摘要更新: +%d 条消息 → %d 字摘要", len(chat_lines), len(summary))
        return summary
    except Exception as e:
        logger.info("摘要生成失败: %s", e)
        return existing_summary


def should_summarize(
    total_rounds: int,
    last_summary_round: int = 0,
    interval: int = SUMMARY_EVERY_N_ROUNDS,
) -> bool:
    """"判断是否需要触发摘要：对话轮数 > 阈值 且 距上次 > interval/2"""
    if total_rounds < interval:
        return False
    return (total_rounds - last_summary_round) >= (interval // 2)


def build_summary_context(existing_summary: str) -> Optional[str]:
    """"构建注入给 Agent 的摘要上下文"""
    if not existing_summary:
        return None
    return f"[长期记忆摘要]\n{existing_summary}\n[/长期记忆摘要]"
