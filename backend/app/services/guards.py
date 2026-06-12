# MirrorTalk - 死循环检测 & 工具超时
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 不同工具的独立超时（秒）
TOOL_TIMEOUTS: dict[str, float] = {
    "recall": 60.0,
    "remember": 30.0,
    "query_profile": 30.0,
    "update_profile": 30.0,
    "query_sql": 120.0,
    "__default__": 60.0,
}

DEAD_LOOP_THRESHOLD = 3  # 连续 N 次相同指纹即判定死循环


def get_tool_fingerprint(tool_call: dict) -> str:
    """生成工具调用的唯一指纹（name + args 签名）"""
    raw = f"{tool_call.get('name', '')}:{json.dumps(tool_call.get('args', {}), sort_keys=True, ensure_ascii=False)}"
    return hashlib.md5(raw.encode()).hexdigest()


def detect_dead_loop(history: list[str]) -> bool:
    """检测死循环：连续 N 次工具调用指纹完全相同"""
    if len(history) < DEAD_LOOP_THRESHOLD:
        return False
    return len(set(history[-DEAD_LOOP_THRESHOLD:])) == 1


def get_tool_timeout(tool_name: str) -> float:
    """获取工具专属超时，未配置的使用默认值"""
    return TOOL_TIMEOUTS.get(tool_name, TOOL_TIMEOUTS["__default__"])


async def run_with_timeout(coro, timeout: float, tool_name: str) -> Any:
    """带超时的工具执行"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("工具 %s 执行超时 (%ss)", tool_name, timeout)
        raise TimeoutError(f"工具 {tool_name} 执行超时 ({timeout}s)")
