# MirrorTalk - SQL 门控策略
from __future__ import annotations

import logging
import re
from typing import Optional

from app.services.database import get_db

logger = logging.getLogger(__name__)

# 只读 SQL 白名单前缀
ALLOWED_PREFIXES = ("SELECT", "PRAGMA", "EXPLAIN")

# 禁止访问的表（安全敏感）
BLOCKED_TABLES = ("config",)


def is_sql_allowed(has_used_structured_tools: bool) -> tuple[bool, str]:
    """检查 SQL 查询权限是否已解锁"""
    if not has_used_structured_tools:
        return False, "SQL 查询工具尚未解锁。请先使用 recall 或 remember 等结构化工具，然后才能使用 SQL 查询。"
    return True, ""


def validate_sql_query(sql: str) -> tuple[bool, str]:
    """
    校验 SQL 查询是否安全（只读、不访问敏感表）。
    返回 (is_valid, error_message)
    """
    sql_stripped = sql.strip().upper()

    # 只允许 SELECT/PRAGMA/EXPLAIN
    if not any(sql_stripped.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return False, "只允许执行 SELECT、PRAGMA、EXPLAIN 查询"

    # 检查是否包含敏感表
    sql_lower = sql.lower()
    for table in BLOCKED_TABLES:
        if table in sql_lower:
            return False, f"无权访问表: {table}"

    return True, ""


async def execute_readonly_query(sql: str, limit: int = 20) -> str:
    """执行只读 SQL 查询，返回格式化结果"""
    valid, error = validate_sql_query(sql)
    if not valid:
        return f"查询被拒绝: {error}"

    # 自动加 LIMIT 防止查询过大
    sql_upper = sql.strip().upper()
    if sql_upper.startswith("SELECT") and "LIMIT" not in sql_upper:
        # 在最后一个分号前插入 LIMIT
        sql = sql.rstrip().rstrip(";") + f" LIMIT {limit}"

    try:
        conn = get_db()
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "查询结果为空"

        # 格式化输出
        columns = [desc[0] for desc in cursor.description]
        header = " | ".join(columns)
        separator = "-" * len(header)
        lines = [f"查询结果 ({len(rows)} 行):", header, separator]

        for row in rows[:limit]:
            values = [str(v) if v is not None else "NULL" for v in row]
            lines.append(" | ".join(values))

        if len(rows) > limit:
            lines.append(f"... 还有 {len(rows) - limit} 行未显示")

        return "\n".join(lines)
    except Exception as e:
        return f"查询执行失败: {str(e)}"
