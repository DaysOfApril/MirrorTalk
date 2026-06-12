# MirrorTalk - 最终回答审核
from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.messages import SystemMessage

from app.models import ProviderConfig
from app.services.provider import create_llm

logger = logging.getLogger(__name__)

REVIEW_PROMPT = """你是一个回答质量审核员。审查以下 AI 生成的回复，判断是否存在问题。

回复场景：{scenario}
AI 身份：{persona_name}
用户消息：{user_query}
AI 回复：{reply}

附近的原始工具调用结果：
{tool_results}

请逐项检查：
1. **编造（Hallucination）**：回复中声称的事实是否在工具调用结果中有依据？如果有"无中生有"的信息，指出具体是哪句。
2. **身份暴露**：是否暴露了自己是 AI？（例如"作为AI"、"我不知道"、"我没有情感"等）
3. **人格一致性**：回复的语气、风格是否符合 {persona_name} 的设定？
4. **遗漏关键引用**：工具结果中有重要信息但没有在回复中提及？

输出 JSON（只输出 JSON，不要其他内容）：
{{
    "pass": true/false,
    "issues": [
        {{"type": "hallucination|identity_leak|style_mismatch|missing_citation", "detail": "具体问题描述"}}
    ],
    "suggestion": "如果有问题，建议如何修正（一句话）"
}}
"""


async def review_answer(
    persona_name: str,
    scenario: str,
    user_query: str,
    reply: str,
    messages: list,
) -> dict:
    """审查 Agent 回答质量"""
    if not reply or len(reply.strip()) < 3:
        return {
            "pass": False,
            "issues": [{"type": "empty_reply", "detail": "回复为空或过短"}],
            "suggestion": "请生成一个完整的回复",
        }

    # 提取最近的工具结果作为上下文
    tool_results = _extract_tool_results(messages, max_chars=1500)

    llm = create_llm(ProviderConfig())
    resp = await llm.ainvoke([
        SystemMessage(content=REVIEW_PROMPT.format(
            scenario=scenario,
            persona_name=persona_name,
            user_query=user_query[:500],
            reply=reply[:2000],
            tool_results=tool_results,
        )),
    ])

    try:
        content = resp.content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content)
        if not isinstance(result.get("pass"), bool):
            result["pass"] = True
        return result
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("审核 LLM 返回解析失败: %s", e)
        return {"pass": True, "issues": [], "suggestion": ""}


def _extract_tool_results(messages: list, max_chars: int = 1500) -> str:
    """从消息列表中提取最近的工具调用结果"""
    parts = []
    total = 0
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.content:
            role = getattr(msg, "type", "unknown")
            text = str(msg.content)[:300]
            total += len(text)
            parts.append(f"[{role}]: {text}")
            if total > max_chars:
                break
    return "\n".join(reversed(parts))


def build_correction(review_result: dict) -> str:
    """根据审核结果生成修正说明"""
    if review_result.get("pass", True):
        return ""
    issues = review_result.get("issues", [])
    suggestion = review_result.get("suggestion", "")
    if not issues and not suggestion:
        return ""

    parts = ["（补充说明：我检查了一下刚才的回答，发现以下问题：）"]
    for issue in issues:
        parts.append(f"- {issue.get('detail', '')}")
    if suggestion:
        parts.append(f"修正：{suggestion}")
    parts.append("（很抱歉，以上是我的补充说明。）")
    return "\n".join(parts)
