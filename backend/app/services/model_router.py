# MirrorTalk - Model Router（按复杂度分级路由）
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# ---- 模型分级 ----

MODEL_TIERS = {
    "fast":   "deepseek-v4-flash",   # 简单问候、缓存命中
    "normal": "deepseek-v4-flash",   # 常规对话
    "reason": "deepseek-v4-pro",     # 复杂分析、多跳推理
}

# 启发式关键词：触发 pro 模型
REASON_KEYWORDS = [
    "分析", "总结", "对比", "为什么", "原因",
    "趋势", "关系", "变化", "解释", "归纳",
    "预测", "建议", "方案", "步骤", "规划",
    "优缺点", "利弊", "区别", "类似", "不同",
    "你觉得", "你怎么看", "帮我分析",
]

# 简单模式：直接走 flash
SIMPLE_PATTERNS = [
    r"^(你好|在吗|hi|hello|早|晚安|拜拜|嗯|好|谢谢|ok|哈哈)+[\s!！。.]*$",
    r"^.{1,4}$",  # 4 字以内
]


def classify_query_complexity(query: str) -> str:
    """"启发式快判 query 复杂度 → 模型分级"""
    if not query or not query.strip():
        return "fast"

    q = query.strip()

    # 简单模式
    for pattern in SIMPLE_PATTERNS:
        if re.match(pattern, q):
            return "fast"

    # 推理关键词
    if any(kw in q for kw in REASON_KEYWORDS):
        return "reason"

    # 长度启发：长 query 可能需要更多推理
    if len(q) > 80:
        return "reason"

    return "normal"


def get_model_for_query(query: str, default_tier: str = "normal") -> str:
    """"根据 query 返回推荐模型名"""
    tier = classify_query_complexity(query)
    model = MODEL_TIERS.get(tier, MODEL_TIERS[default_tier])
    logger.debug("Model Router: query=%s → tier=%s → model=%s", query[:30], tier, model)
    return model
