# MirrorTalk - 深度画像分析 Pipeline（双模型协同 + 语义分段 + 静默期追踪）
#
# 架构:
#   _pre_segment():  时间间隔 + 语义相似度 → 动态分段 + 静默期检测
#   stage1a: 对每个分段提取话题摘要与情绪弧线 (Qwen2.5-7B)
#   stage1b: 对每个分段提取结构化字段 (Qwen2.5-7B)
#   stage2:   深度心理建模 (DeepSeek)
#
# 关键原则: 本地模型只做"客观事实的结构化搬运",远端模型只做"主观意义的深度阐释"

from __future__ import annotations

import json
import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import hashlib
import numpy as np
from langchain_core.messages import HumanMessage, SystemMessage

from app.models import ProviderConfig
from app.services.provider import create_llm
from app.services.database import get_deep_profile_cache, set_deep_profile_cache
from app.services.embedding import embed_texts

logger = logging.getLogger(__name__)

# ========== 模型配置 ==========

STAGE1_PROVIDER = "qwen"
STAGE1_MODEL = "qwen-turbo"
STAGE2_PROVIDER = "deepseek"
STAGE2_MODEL = "deepseek-chat"

# ========== 分段参数 ==========

SESSION_GAP_MINUTES = 30       # 超过30分钟无消息视为候选断点
MAX_SEGMENT_TURNS = 20         # 每段最多20轮
SEMANTIC_SIM_THRESHOLD = 0.55  # 余弦相似度低于此值视为话题转换
SILENCE_HOURS = 2              # 超过2小时记为异常静默


# ========== 消息预分段（时间 + 语义） ==========
# ========== ???? ==========

def _hash_messages(messages: list[dict]) -> str:
    """??????????????????"""
    # ?????? sender + content ?100?????
    hasher = hashlib.sha256()
    for m in messages[:200]:  # ???200??????
        text = f"{m.get('sender','')}:{m.get('content','')[:100]}"
        hasher.update(text.encode("utf-8"))
    hasher.update(str(len(messages)).encode())
    return hasher.hexdigest()[:16]




# ========== ??????? ==========

async def _stream_timeline(
    file_path: str,
    target_speaker: str | None = None,
    window_size: int = 200,
) -> list[list[dict]]:
    """?????????????????????????
    ??: O(window_size) ???????????
    """
    import json as _json

    target_indices: list[int] = []
    all_msgs: list[dict] = []

    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                msg = _json.loads(line)
                all_msgs.append(msg)
                if target_speaker is None or msg.get("sender") == target_speaker:
                    target_indices.append(i)
            except _json.JSONDecodeError:
                pass

    if not target_indices:
        return []

    half = window_size // 2
    seen_ranges: set[tuple[int, int]] = set()

    for ti in target_indices:
        start = max(0, ti - half)
        end = min(len(all_msgs), ti + half)
        for es, ee in list(seen_ranges):
            if start <= ee and end >= es:
                seen_ranges.discard((es, ee))
                start = min(start, es)
                end = max(end, ee)
        seen_ranges.add((start, end))

    windows = [all_msgs[s:e] for s, e in sorted(seen_ranges)]
    logger.info(
        "Timeline stream: %d msgs, %d target -> %d windows",
        len(all_msgs), len(target_indices), len(windows),
    )
    return windows



# ========== Layer 0: ?????????? token? ==========

def _compute_behavior_stats(messages: list[dict], silences: list[dict]) -> dict:
    """???????????????? Python ?????? LLM?"""
    from collections import Counter, defaultdict
    from datetime import datetime

    if not messages:
        return {}

    total = len(messages)

    # ??????
    lengths = [len(m.get("content", "")) for m in messages]
    avg_length = sum(lengths) / total if total else 0

    # ??????
    hour_dist = Counter()
    day_dist = Counter()
    ts_count = 0
    for m in messages:
        ts = m.get("timestamp", "")
        dt = _parse_timestamp(ts)
        if dt:
            hour_dist[dt.hour] += 1
            day_dist[dt.strftime("%A")] += 1
            ts_count += 1

    # ???? (23:00-05:00)
    night_msgs = sum(hour_dist[h] for h in range(23, 24)) + sum(hour_dist[h] for h in range(0, 6))
    night_ratio = night_msgs / ts_count if ts_count > 0 else 0

    # ????
    peak_hour = hour_dist.most_common(1)[0] if hour_dist else (0, 0)

    # ??????????
    active_dates = set()
    for m in messages:
        ts = m.get("timestamp", "")
        dt = _parse_timestamp(ts)
        if dt:
            active_dates.add(dt.strftime("%Y-%m-%d"))
    active_days = len(active_dates)
    daily_avg = round(total / active_days, 1) if active_days > 0 else 0

    # ??????
    emoji_pattern = re.compile(
        r"[\U0001F300-\U0001F9FF\u2600-\u27BF\uFE00-\uFEFF"
        r"\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF]"
        r"|\[[^\]]+\]"  # [??] [??] type
    )
    emoji_count = sum(1 for m in messages if emoji_pattern.search(m.get("content", "")))
    emoji_ratio = round(emoji_count / total * 100, 1) if total > 0 else 0

    # @ ??
    at_count = sum(1 for m in messages if "@" in m.get("content", ""))
    at_ratio = round(at_count / total * 100, 1) if total > 0 else 0

    # ?????
    total_silence_hours = sum(s.get("duration_hours", 0) for s in silences)
    night_silence_count = sum(
        1 for s in silences if s.get("time_of_day") == "??"
    )

    return {
        "total_messages": total,
        "avg_message_length": round(avg_length, 1),
        "active_days": active_days,
        "daily_avg_messages": daily_avg,
        "peak_active_hour": f"{peak_hour[0]}:00 ({peak_hour[1]}?)",
        "night_owl_ratio": f"{round(night_ratio * 100, 1)}%",
        "hourly_distribution": dict(hour_dist.most_common(6)),
        "day_distribution": dict(day_dist),
        "emoji_usage_rate": f"{emoji_ratio}%",
        "at_mention_rate": f"{at_ratio}%",
        "total_silence_hours": round(total_silence_hours, 1),
        "night_silence_periods": night_silence_count,
        "message_length_range": f"{min(lengths)}-{max(lengths)}?",
    }



async def _smart_segment(
    messages: list[dict] | None = None,
    timeline_path: str | None = None,
    target_speaker: str | None = None,
    sim_threshold: float = SEMANTIC_SIM_THRESHOLD,
) -> list[list[dict]]:
    """动态分段: 时间间隔候选断点 + embedding 语义相似度确认"""
    if not messages:
        return []

    # Step 1: 找出时间断点候选位置
    candidates: list[int] = []  # 消息索引，在此之后切分
    last_ts: datetime | None = None

    for i, msg in enumerate(messages):
        ts = _parse_timestamp(msg.get("timestamp", ""))

        # 时间间隔候选
        if last_ts and ts:
            gap_min = (ts - last_ts).total_seconds() / 60
            if gap_min > SESSION_GAP_MINUTES:
                candidates.append(i)

        # 轮数硬上限
        if len(candidates) == 0:
            if i > 0 and i % (MAX_SEGMENT_TURNS * 2) == 0:
                candidates.append(i)
        else:
            since_last = i - candidates[-1]
            if since_last >= MAX_SEGMENT_TURNS * 2:
                candidates.append(i)

        if ts:
            last_ts = ts
        elif last_ts is None:
            last_ts = datetime.now()

    if not candidates:
        return [messages]

    # Step 2: 在候选断点处用 embedding 验证语义是否真的变了
    # 取断点前后各1条消息的文本做相似度对比
    confirmed_breaks: set[int] = set()

    # 批量获取所有候选点前后的文本
    texts_to_embed: list[str] = []
    text_map: list[tuple[int, bool]] = []  # (候选索引, is_before)
    for bp in candidates:
        if bp > 0 and bp < len(messages):
            texts_to_embed.append(messages[bp - 1].get("content", "")[:200])
            text_map.append((bp, True))
            texts_to_embed.append(messages[bp].get("content", "")[:200])
            text_map.append((bp, False))

    if texts_to_embed:
        try:
            embeddings = await embed_texts(texts_to_embed)
            for idx in range(0, len(embeddings), 2):
                if idx + 1 < len(embeddings):
                    before_emb = np.array(embeddings[idx])
                    after_emb = np.array(embeddings[idx + 1])
                    sim = float(np.dot(before_emb, after_emb))
                    bp_candidate = text_map[idx][0]
                    if sim < sim_threshold:
                        confirmed_breaks.add(bp_candidate)
                        logger.debug(
                            f"Semantic break at msg {bp_candidate}: sim={sim:.3f} < {sim_threshold}"
                        )
        except Exception as e:
            logger.warning(f"Embedding-based segmentation failed: {e}, falling back to time-only")
            confirmed_breaks = set(candidates)

    # Step 3: 按确认的断点切分
    if not confirmed_breaks:
        return [messages]

    segments: list[list[dict]] = []
    start = 0
    for bp in sorted(confirmed_breaks):
        if bp > start:
            segments.append(messages[start:bp])
        start = bp
    if start < len(messages):
        segments.append(messages[start:])

    return segments


# ========== 静默期分析 ==========

def _extract_silence_periods(messages: list[dict]) -> list[dict]:
    """检测异常静默区间"""
    silences: list[dict] = []
    last_ts: datetime | None = None
    last_sender: str = ""

    for msg in messages:
        ts = _parse_timestamp(msg.get("timestamp", ""))
        if last_ts and ts:
            gap_hours = (ts - last_ts).total_seconds() / 3600
            if gap_hours > SILENCE_HOURS:
                hour_of_day = ts.hour
                silences.append({
                    "from": last_ts.isoformat(),
                    "to": ts.isoformat(),
                    "duration_hours": round(gap_hours, 1),
                    "time_of_day": "深夜" if hour_of_day < 6 else ("凌晨" if hour_of_day < 8 else "白天"),
                    "last_sender": last_sender,
                })
        if ts:
            last_ts = ts
        last_sender = msg.get("sender", "")

    return silences


# ========== Stage 1a: 分段 + 话题摘要 ==========

STAGE1A_PROMPT = """# Role
你是对话分段标注员。只做两件事：给每段对话写话题摘要，标情绪弧线。

# Rules
1. 话题摘要：15字以内
2. 情绪弧线：描述该段对话中主要发言人的情绪变化轨迹（如：平静→防御→自嘲）
3. 不需脱敏、不需提取原话、不需语用标记

聊天记录（格式：[发言人] (时间): 内容）:
{chat_text}

输出 JSON:
{{
  "topic_summary": "...",
  "emotional_arc": "..."
}}"""


async def _stage1a_summarize(
    messages: list[dict],
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Stage 1a: 对单段对话做话题摘要 + 情绪弧线"""
    provider = provider or STAGE1_PROVIDER
    model = model or STAGE1_MODEL
    llm = create_llm(ProviderConfig(provider=provider, model=model))

    chat_text = "\n".join(
        f"[{m.get('sender', '?')}] ({m.get('timestamp', '?')}): {m.get('content', '')}"
        for m in messages
    )[:5000]

    for attempt in range(3):
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=STAGE1A_PROMPT.format(chat_text=chat_text)),
            ])
            break
        except Exception as e:
            if attempt == 2:
                return {"topic_summary": "", "emotional_arc": ""}
            await asyncio.sleep(2 ** attempt)

    try:
        content = resp.content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content)
    except json.JSONDecodeError:
        return {"topic_summary": "", "emotional_arc": ""}


# ========== Stage 1b: 结构化特征提取 ==========

STAGE1B_PROMPT = """# Role
你是对话特征提取员。基于已分段的对话，提取以下结构化字段。

# Rules
1. key_utterances: 3-5条最具代表性的原话（保留标点/语气词/表情符号）
2. pragmatic_markers: 语用标记列表（如：反问、省略号、表情包、撤回、长时间未回复、讽刺、自嘲）
3. context_notes: 上下文线索（如：提及某人/某事/时间节点/外部事件）
4. 严格脱敏：人名→[P1]/[P2]，地名→[LOC]，号码/金额→[NUM]
5. 不做性格判断，只记录可观测事实

对话摘要: {summary}
情绪弧线: {arc}

聊天记录:
{chat_text}

输出 JSON:
{{
  "key_utterances": ["...", "..."],
  "pragmatic_markers": ["...", "..."],
  "context_notes": "..."
}}"""


async def _stage1b_extract(
    messages: list[dict],
    summary: str,
    arc: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Stage 1b: 从已分段对话中提取结构化特征"""
    provider = provider or STAGE1_PROVIDER
    model = model or STAGE1_MODEL
    llm = create_llm(ProviderConfig(provider=provider, model=model))

    chat_text = "\n".join(
        f"[{m.get('sender', '?')}]: {m.get('content', '')}"
        for m in messages
    )[:4000]

    for attempt in range(3):
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=STAGE1B_PROMPT.format(
                    summary=summary, arc=arc, chat_text=chat_text
                )),
            ])
            break
        except Exception as e:
            if attempt == 2:
                return {"key_utterances": [], "pragmatic_markers": [], "context_notes": ""}
            await asyncio.sleep(2 ** attempt)

    try:
        content = resp.content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content)
    except json.JSONDecodeError:
        return {"key_utterances": [], "pragmatic_markers": [], "context_notes": ""}


# ========== Stage 1 完整流程 ==========

async def stage1_segment_and_extract(
    messages: list[dict],
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Stage 1: 语义分段 → 1a摘要 → 1b特征提取 → 结构化输出"""
    provider = provider or STAGE1_PROVIDER
    model = model or STAGE1_MODEL

    # 智能分段
    segments_raw = await _smart_segment(messages)
    logger.info(f"Stage1: {len(messages)} msgs → {len(segments_raw)} semantic segments")

    # 静默期检测（基于全量消息，不受分段影响）
    silences = _extract_silence_periods(messages)

    # 逐个分段处理: 1a → 1b
    all_segments: list[dict] = []
    sem = asyncio.Semaphore(4)  # 并发4个分段

    async def process_one(seg_idx: int, seg_msgs: list[dict]):
        async with sem:
            # 1a: 话题摘要 + 情绪弧线
            summary_data = await _stage1a_summarize(seg_msgs, provider, model)
            # 1b: 结构化提取
            features = await _stage1b_extract(
                seg_msgs,
                summary_data.get("topic_summary", ""),
                summary_data.get("emotional_arc", ""),
                provider, model,
            )

            ts_start = seg_msgs[0].get("timestamp", "") if seg_msgs else ""
            ts_end = seg_msgs[-1].get("timestamp", "") if seg_msgs else ""
            participants = list(set(m.get("sender", "?") for m in seg_msgs))

            return {
                "segment_id": seg_idx + 1,
                "timestamp_range": f"{ts_start} ~ {ts_end}" if ts_start else "",
                "message_count": len(seg_msgs),
                "participants": participants,
                "topic_summary": summary_data.get("topic_summary", ""),
                "emotional_arc": summary_data.get("emotional_arc", ""),
                "key_utterances": features.get("key_utterances", []),
                "pragmatic_markers": features.get("pragmatic_markers", []),
                "context_notes": features.get("context_notes", ""),
            }

    tasks = [process_one(i, seg) for i, seg in enumerate(segments_raw)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning(f"Stage1 segment {i} failed: {r}")
        elif r:
            all_segments.append(r)

    # 按 segment_id 排序
    all_segments.sort(key=lambda s: s["segment_id"])

    logger.info(
        f"Stage1 complete: {len(all_segments)} segments, "
        f"{len(silences)} silence periods detected"
    )

    return all_segments, silences


# ========== Stage 2: 深度心理建模 ==========

STAGE2_SYSTEM_PROMPT = """# Role
你是一位整合了临床心理学、话语分析与社会学理论的资深人格研究员。请基于提供的结构化聊天数据，进行深度人格建模。

# Theoretical Framework (必须显式调用)
分析时需交替使用以下透镜，并在输出中标注所用理论：
- 【心理动力学】防御机制、客体关系、自体凝聚力
- 【依附理论】安全基地探索、焦虑/回避策略、内部工作模型
- 【拟剧论】前台表演、后台真实、印象管理、面子工作
- 【叙事心理学】情节编排、评价立场、身份宣称、沉默/空白意义

# Analysis Protocol

## Step 1: 核心冲突识别
从数据中提炼2-3个贯穿始终的认知-情感冲突（非表面特征）。每个冲突需包含：
- 冲突命名（如："渴望融合 vs 恐惧吞噬"）
- 语言证据（引用segment_id + 原话）
- 心理功能（该冲突如何服务于自我保护？）
- 理论锚点（对应上述哪个理论的具体概念？）
- confidence: 0-1 置信度

## Step 2: 关系脚本图谱
分析其对不同对象（朋友/异性/长辈/权威）的互动模式差异：
- 角色定位（拯救者/受害者/小丑/导师？）
- 权力动态（谁主导话题？谁承担情绪劳动？）
- 脚本切换触发条件

## Step 3: 发展性假设与验证
- 提出1-2个关于早期经历/创伤的合理推测（标注"推测"）
- 为每个推测设计可验证的行为指标
- 指出当前数据中的反证或模糊地带

## Step 4: 元反思
- 本次分析可能存在的盲区
- 哪些结论证据较弱需存疑？
- 建议补充的数据源

# Output Requirements
- 使用 Markdown 格式，层级清晰
- 所有论断必须有 segment_id 支撑
- 区分"观察事实"与"理论推断"
- 每个主要结论附带 confidence (0-1)
- 语言风格：专业但可读

结构化聊天数据:
{segments_json}

静默期数据:
{silences_json}"""


async def stage2_deep_analysis(
    segments: list[dict],
    silences: list[dict],
    persona_name: str,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """Stage 2: 深度心理建模，输出 Markdown 报告"""
    provider = provider or STAGE2_PROVIDER
    model = model or STAGE2_MODEL
    llm = create_llm(ProviderConfig(provider=provider, model=model))

    segments_json = json.dumps(segments, ensure_ascii=False, indent=2)
    silences_json = json.dumps(silences, ensure_ascii=False, indent=2) if silences else "[]"

    # 智能抽样：保留前5段 + 情感高密度段
    if len(segments_json) > 10000:
        sampled = segments[:5]
        # 找 emotional_arc 非空的段（情感信息密度更高）
        emotional_segments = [
            s for s in segments[5:]
            if s.get("emotional_arc") and s["emotional_arc"] not in ("", "无", "—")
        ]
        # 补充情感段 + 均匀采样
        sampled.extend(emotional_segments[:10])
        for i in range(10, len(segments), 8):
            if segments[i] not in sampled:
                sampled.append(segments[i])
        segments_json = json.dumps(sampled, ensure_ascii=False, indent=2)
        logger.info(f"Stage2: sampled {len(sampled)}/{len(segments)} segments (emotion-aware)")

    prompt = STAGE2_SYSTEM_PROMPT.format(
        segments_json=segments_json[:14000],
        silences_json=silences_json[:1000],
        behavior_stats_json=json.dumps(behavior_stats, ensure_ascii=False, indent=2)[:2000],
    )

    resp = await llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"请对 {persona_name} 的聊天数据进行深度人格分析。"),
    ])

    report = resp.content.strip()
    logger.info(f"Stage2: generated {len(report)} char deep profile report for {persona_name}")
    return report


# ========== 完整双模型流水线 ==========

async def build_deep_profile(
    persona_id: str,
    name: str,
    messages: list[dict],
    stage1_provider: str | None = None,
    stage1_model: str | None = None,
    stage2_provider: str | None = None,
    stage2_model: str | None = None,
) -> dict:
    """完整深度画像分析流水线"""
    logger.info(f"Starting deep profile analysis: {persona_id} ({len(messages)} messages)")

    # Stage 1: 语义清洗与特征提取
    segments, silences = await stage1_segment_and_extract(
        messages,
        provider=stage1_provider,
        model=stage1_model,
    )

    if not segments:
        return {
            "persona_id": persona_id,
            "name": name,
            "status": "failed",
            "error": "Stage 1 produced no segments",
        }

    # Stage 2: 深度心理建模
    report = await stage2_deep_analysis(
        segments,
        silences,
        persona_name=name,
        provider=stage2_provider,
        model=stage2_model,
    )

    return {
        "persona_id": persona_id,
        "name": name,
        "status": "completed",
        "segment_count": len(segments),
        "silence_count": len(silences),
        "behavior_stats": behavior_stats,
        "segments": segments,
        "silences": silences,
        "report": report,
    }


# ========== 时间戳解析 ==========

def _parse_timestamp(ts_str: str) -> datetime | None:
    """尝试解析多种时间戳格式"""
    if not ts_str:
        return None
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts_str.strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(ts_str.strip())
    except ValueError:
        return None
