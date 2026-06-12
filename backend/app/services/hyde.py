# MirrorTalk - HyDE (Hypothetical Document Embeddings) 查询改写
""""检索前用 LLM 生成假设文档，用假设文档 embedding 替代原始 query 检索"""
from __future__ import annotations

import logging

from langchain_core.messages import SystemMessage

from app.models import ProviderConfig
from app.services.provider import create_llm

logger = logging.getLogger(__name__)

HYDE_PROMPT = """"你是一个知识助手。请根据用户的问题，写一段假想的回答文档。
这个文档应该包含可能出现在知识库中的事实信息，用于帮助检索。

规则：
- 写一段 100-200 字的段落
- 使用陈述句，不要用问答格式
- 如果问题很简单（问候、闲聊），直接返回原始问题

用户问题: {query}

假想文档:"""


async def generate_hypothetical_doc(query: str) -> str:
    """"生成假设文档，HyDE 检索用"""
    if not query or len(query.strip()) < 3:
        return query

    # 短问候跳过
    skip_patterns = {"你好", "在吗", "hi", "hello", "早", "晚安", "拜拜", "嗯", "好", "谢谢", "ok"}
    if query.strip() in skip_patterns:
        return query

    try:
        llm = create_llm(ProviderConfig())
        resp = await llm.ainvoke([
            SystemMessage(content=HYDE_PROMPT.format(query=query)),
        ])
        hypo = resp.content.strip()
        if hypo:
            logger.debug("HyDE 生成: %s → %s", query[:30], hypo[:60])
            return hypo
    except Exception as e:
        logger.info("HyDE 生成失败，降级为原始 query: %s", e)

    return query
