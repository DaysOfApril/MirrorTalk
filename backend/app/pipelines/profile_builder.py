# MirrorTalk - 离线画像生成 Pipeline
from __future__ import annotations

import json
import re as _re
import asyncio
import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.models import OceanScores, PersonaProfile, ProviderConfig, StyleTags
from app.services.database import get_db
from app.services.memory import insert_memory
from app.services.provider import create_llm
from app.models import MemorySource, MemorySourceType

logger = logging.getLogger(__name__)

# ========== 消息预过滤器 ==========

NOISE_PATTERNS = [
    _re.compile(r'^[\u554a\u561e\u54e6\u597d\u5bf9\u884c\u53ef\u54c8\u563f\u563b\u55e8\u5475\u5582\u54ce\u5503\u5566\u54e9]+[~\u00a1!\u3002\uff0c\uff0c\u2026]?$'),
    _re.compile(r'^[\U0001F44D\U0001F44E\u2764\ufe0f\U0001F60A\U0001F602\U0001F923\U0001F62D\U0001F495\u2728\U0001F525\U0001F389\U0001F64F\U0001F605\U0001F970\U0001F618\U0001F914\U0001FAE1]+$'),
    _re.compile(r'^[\U0001F300-\U0001F9FF\u2600-\u27BF\uFE00-\uFEFF]+$'),
]

MIN_CONTENT_LENGTH = 8


def should_extract(msg: dict) -> bool:
    content = msg.get("content", "").strip()
    if not content or len(content) < MIN_CONTENT_LENGTH:
        return False
    for pattern in NOISE_PATTERNS:
        if pattern.fullmatch(content):
            return False
    return True


# ========== 提取 Prompt ==========

FACT_EXTRACTION_PROMPT = """从以下聊天记录中提取值得长期记住的原子事实。

规则:
- 每条事实一句话，独立完整
- 只提取稳定的、长期有效的信息（偏好、身份、关系、重要事件）
- 不要提取一次性的、琐碎的信息
- 标明每条事实的类型: profile(用户画像) / fact(事实) / relationship(关系)
- 如果聊天记录中没有值得提取的事实，输出空数组 []

示例:
聊天记录:
[小明]: 我刚搬到上海工作了，在张江那边
[小红]: 恭喜啊！做什么的？
[小明]: 后端开发，主要写Go

输出:
[{{"type": "profile", "content": "小明在上海张江工作"}}, {{"type": "profile", "content": "小明是后端开发工程师，主要使用Go语言"}}]

聊天记录:
{chat_text}

输出 JSON 数组:
[{{"type": "profile|fact|relationship", "content": "..."}}]
"""

STYLE_EXTRACTION_PROMPT = """你是一位专业的心理语言学分析师。根据以下聊天记录，分析发言人 {speaker} 的性格特质和说话风格。

【规则】
- 聊天记录中每条消息都是 {speaker} 的真实发言
- 必须基于消息内容做分析，禁止说"无文字消息""无法判断"
- personality 至少给出3个有区分度的特征词
- catchphrases 直接从原文中摘录真实出现的短语
- 如果消息确实少（<5条），就基于仅有的内容做合理推断

分析维度：
- personality: 3-5个特征词，如: 习惯性讨好、喜欢掌控话题、思维跳跃、缺乏安全感、强势直接
- catchphrases: 口头禅列表，从聊天中提取
- sentence_style: 深度分析句式习惯
- emoji_style: 表情包使用习惯
- tone: 语气风格

聊天记录：
{chat_text}

只输出 JSON，不要任何其他文字：
{{
  "personality": ["...", "...", "..."],
  "catchphrases": ["...", "..."],
  "sentence_style": "...",
  "emoji_style": "...",
  "tone": "..."
}}
"""
  "emoji_style": "...",
  "tone": "..."
}}
"""


# ========== 分层成本配置 ==========

DEFAULT_EXTRACTION_PROVIDER = "qwen"
DEFAULT_EXTRACTION_MODEL = "qwen-turbo"
DEFAULT_STYLE_PROVIDER = "qwen"
DEFAULT_STYLE_MODEL = "qwen-plus"

FALLBACK_PROVIDER = "ollama"
FALLBACK_MODEL = "qwen2.5:7b"
ULTIMATE_FALLBACK_PROVIDER = "qwen"
ULTIMATE_FALLBACK_MODEL = "qwen-turbo"

UPGRADE_PROVIDER = "deepseek"
UPGRADE_MODEL = "deepseek-chat"


# ========== 模型降级回退 ==========

async def _create_llm_with_fallback(
    primary_provider: str,
    primary_model: str,
    fallback_provider: str = FALLBACK_PROVIDER,
    fallback_model: str = FALLBACK_MODEL,
    ultimate_provider: str = ULTIMATE_FALLBACK_PROVIDER,
    ultimate_model: str = ULTIMATE_FALLBACK_MODEL,
):
    """Try primary -> fallback -> ultimate (qwen). Qwen always serves as safety net."""
    candidates = [
        (primary_provider, primary_model, "Primary"),
        (fallback_provider, fallback_model, "Fallback"),
        (ultimate_provider, ultimate_model, "Ultimate fallback"),
    ]

    last_error = None
    for provider, model, label in candidates:
        try:
            llm = create_llm(ProviderConfig(provider=provider, model=model))
            await llm.ainvoke([SystemMessage(content="ping")])
            logger.info("%s %s/%s OK", label, provider, model)
            return llm, provider, model
        except Exception as e:
            logger.warning(
                "%s %s/%s unavailable: %s",
                label, provider, model, e,
            )
            last_error = e

    raise RuntimeError(
        f"All providers unavailable. Last error: {last_error}. "
        f"Please configure a Qwen API key in the Settings page."
    ) from last_error


# ========== Step 1: 批量提取原子事实 ==========

async def extract_atomic_facts(
    messages: list[dict],
    batch_size: int = 30,
    max_chars_per_batch: int = 4000,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Step 1: extract atomic facts from chat records (batched + pre-filtered)"""
    provider = provider or DEFAULT_EXTRACTION_PROVIDER
    model = model or DEFAULT_EXTRACTION_MODEL
    llm, used_provider, used_model = await _create_llm_with_fallback(provider, model)

    filtered = [m for m in messages if should_extract(m)]
    logger.info(
        "Fact extraction pre-filter: %d/%d messages passed (%.0f%%)",
        len(filtered), len(messages),
        len(filtered) / max(len(messages), 1) * 100
    )

    all_facts: list[dict] = []

    for i in range(0, len(filtered), batch_size):
        batch = filtered[i:i + batch_size]
        chat_text = "\n".join(
            "[" + m.get("sender", "?") + "]: " + m.get("content", "")
            for m in batch
        )
        if len(chat_text) > max_chars_per_batch:
            chat_text = chat_text[:max_chars_per_batch]

        for attempt in range(3):
            try:
                resp = await llm.ainvoke([
                    SystemMessage(content=FACT_EXTRACTION_PROMPT.format(chat_text=chat_text)),
                ])
                break
            except Exception as e:
                import traceback as _tb
                logger.warning("LLM call failed (attempt %s/3): %s\n%s", attempt + 1, e, _tb.format_exc())
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)

        try:
            content = resp.content.strip()
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            facts = json.loads(content)
            if isinstance(facts, list):
                all_facts.extend(facts)
            else:
                logger.warning("Fact extraction returned non-array: %s", content[:200])
        except Exception as e:
            logger.warning("Failed to parse fact extraction response: %s\nContent: %s", e, resp.content[:300])

    return all_facts


# ========== Step 2: 提取说话风格 ==========

def _clean_content(content: str) -> str:
    """剔除动画表情 URL 等噪音，让 LLM 只看文本内容"""
    import re
    cleaned = re.sub(r'\[动画表情\]\s*https?://\S+', '', content)
    return cleaned.strip()

async def extract_style(
    messages: list[dict],
    speaker: str,
    provider: str | None = None,
    model: str | None = None,
) -> StyleTags:
    """Step 2: extract speaking style (sample longest messages)"""
    provider = provider or DEFAULT_STYLE_PROVIDER
    model = model or DEFAULT_STYLE_MODEL
    llm, used_provider, used_model = await _create_llm_with_fallback(provider, model)

    speaker_msgs = [m for m in messages if m.get("sender") == speaker]
    sorted_msgs = sorted(speaker_msgs, key=lambda m: len(m.get("content", "")), reverse=True)
    sample_msgs = sorted_msgs[:150]

    chat_text = "\n".join(_clean_content(m.get("content", "")) for m in sample_msgs)

    resp = await llm.ainvoke([
        SystemMessage(content=STYLE_EXTRACTION_PROMPT.format(
            speaker=speaker, chat_text=chat_text[:6000]
        )),
    ])
    try:
        content = resp.content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content)
        return StyleTags(**data)
    except Exception as e:
        logger.warning("Style extraction failed: %s", e)
        return StyleTags()


# ========== 增量提取支持 ==========

def get_last_import_timestamp(persona_id: str) -> str | None:
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT created_at FROM personas WHERE id = ?",
            (persona_id,),
        ).fetchone()
        conn.close()
        return row["created_at"] if row else None
    except Exception:
        return None


# ========== 完整画像构建 Pipeline ==========

async def build_persona_pipeline(
    persona_id: str,
    name: str,
    messages: list[dict],
    speaker: str | None = None,
    message_count: int | None = None,
    extraction_provider: str | None = None,
    extraction_model: str | None = None,
    style_provider: str | None = None,
    style_model: str | None = None,
) -> PersonaProfile:
    """Run full persona building pipeline on a set of messages."""
    extracted_messages = [m for m in messages if should_extract(m)]
    logger.info(
        "Building persona '%s' (%d msgs, %d after filter)",
        persona_id, len(messages), len(extracted_messages),
    )

    try:
        facts = await extract_atomic_facts(
            extracted_messages,
            provider=extraction_provider,
            model=extraction_model,
        )
        logger.info("Extracted %d atomic facts", len(facts))

        for f in facts:
            insert_memory(
                source_type=MemorySourceType(f.get("type", "fact")),
                source=MemorySource.FRIEND_SPEECH if speaker != "\u7528\u6237" else MemorySource.USER_SPEECH,
                content=f["content"],
                confidence=0.7,
                importance=0.5,
            )
    except Exception as e:
        logger.warning("Fact extraction skipped: %s", e)
        facts = []

    style = await extract_style(
        messages, speaker,
        provider=style_provider,
        model=style_model,
    )

    profile = PersonaProfile(
        id=persona_id,
        name=name,
        message_count=message_count or len(messages),
        is_aggregated=False,
        style=StyleTags(**(style.model_dump() if style else {})),
        ocean=OceanScores(),
    )

    conn = get_db()
    conn.execute(
        """INSERT INTO personas (id, name, style_json, ocean_json, is_aggregated, source_count, created_at)
        VALUES (?, ?, ?, ?, 0, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            style_json = excluded.style_json,
            ocean_json = excluded.ocean_json,
            source_count = excluded.source_count,
            source_count = excluded.source_count,
        (
            profile.id, profile.name,
            json.dumps(profile.style.model_dump(), ensure_ascii=False),
            json.dumps(profile.ocean.model_dump(), ensure_ascii=False),
            profile.message_count,
        ),
    )
    conn.commit()
    conn.close()
    logger.info("Persona built: %s", persona_id)
    return profile

