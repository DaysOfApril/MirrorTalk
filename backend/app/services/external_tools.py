# MirrorTalk - 外部 API 工具集（真实世界工具）
""""Agent 可调用的外部工具：搜索、天气、计算、URL、时间"""
from __future__ import annotations

import ast
import logging
import operator
from datetime import datetime, timedelta
from typing import Annotated

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 安全的数学运算符白名单
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval(expr: str) -> float:
    """"安全的数学表达式求值，仅允许数字和四则运算 + 幂"""
    expr = expr.strip()
    # 去除所有非安全字符
    allowed = set("0123456789.+-*/()eE ")
    cleaned = "".join(c for c in expr if c in allowed)
    if not cleaned:
        raise ValueError("无效的数学表达式")

    tree = ast.parse(cleaned, mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        elif isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            op_type = type(node.op)
            if op_type in _SAFE_OPS:
                return _SAFE_OPS[op_type](left, right)
            raise ValueError(f"不支持的运算符: {op_type}")
        elif isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            raise ValueError("不支持的运算符")
        elif isinstance(node, ast.Constant):
            return node.value
        else:
            raise ValueError(f"不支持的表达式类型: {type(node)}")

    return float(_eval(tree))


# ========== 工具定义 ==========


@tool
async def web_search(
    query: Annotated[str, "搜索关键词"],
    max_results: Annotated[int, "最大结果数"] = 5,
) -> str:
    """"DuckDuckGo 网页搜索。用于查找实时信息、事实核查。"""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"- {r['title']}: {r['body'][:200]}\n  {r['href']}")
        if not results:
            return f"未找到关于 '{query}' 的搜索结果"
        return f"搜索 '{query}' ({len(results)} 条结果):\n" + "\n".join(results)
    except ImportError:
        return "搜索工具不可用 (duckduckgo_search 未安装)。建议: pip install duckduckgo-search"
    except Exception as e:
        return f"搜索失败: {str(e)[:100]}"


@tool
async def get_weather(
    city: Annotated[str, "城市名称，如 Beijing, Shanghai"],
) -> str:
    """"查询城市天气（wttr.in 免费 API，无需 API key）"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://wttr.in/{city}",
                params={"format": "j1"},
            )
            if resp.status_code != 200:
                return f"天气查询失败: HTTP {resp.status_code}"

            data = resp.json()
            current = data.get("current_condition", [{}])[0]
            weather_desc = current.get("weatherDesc", [{}])[0].get("value", "未知")
            temp_c = current.get("temp_C", "?")
            humidity = current.get("humidity", "?")
            wind = current.get("winddir16Point", "?") + " " + current.get("windspeedKmph", "?") + "km/h"

            # 近 3 天预报
            forecast_lines = []
            for day in data.get("weather", [])[:3]:
                date = day.get("date", "")
                max_t = day.get("maxtempC", "?")
                min_t = day.get("mintempC", "?")
                desc = day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "?")
                forecast_lines.append(f"  {date}: {desc}, {min_t}°C ~ {max_t}°C")

            return (
                f"**{city}** 当前天气: {weather_desc}, {temp_c}°C, "
                f"湿度 {humidity}%, 风 {wind}\n"
                f"近 3 天预报:\n" + "\n".join(forecast_lines)
            )
    except httpx.TimeoutException:
        return "天气查询超时，请稍后重试"
    except Exception as e:
        return f"天气查询失败: {str(e)[:100]}"


@tool
async def calculate(
    expression: Annotated[str, "数学表达式，如 (3.5 + 2) * 4 / 2"],
) -> str:
    """"安全计算数学表达式。支持 + - * / () 和幂运算。"""
    try:
        result = _safe_eval(expression)
        return f"计算结果: {expression} = {result}"
    except Exception as e:
        return f"计算失败: {str(e)[:100]}"


@tool
async def fetch_webpage(
    url: Annotated[str, "网页URL"],
    max_chars: Annotated[int, "最大返回字符数"] = 3000,
) -> str:
    """"抓取网页文本内容。用于阅读文章、获取详情。"""
    if not url.startswith(("http://", "https://")):
        return "URL 必须以 http:// 或 https:// 开头"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "MirrorTalk/1.0"},
            )
            if resp.status_code != 200:
                return f"无法访问该网页: HTTP {resp.status_code}"

            html = resp.text

            # 用 BeautifulSoup 提取纯文本
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                # 移除 script/style
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
            except ImportError:
                # 降级：简单去标签
                import re
                text = re.sub(r"<[^>]+>", " ", html)
                text = re.sub(r"\s+", " ", text).strip()

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n... (已截断，原文共 {len(text)} 字符)"

            title = url.split("/")[-1] or url
            return f"**{title}**\n{text[:max_chars]}"

    except httpx.TimeoutException:
        return "网页抓取超时"
    except Exception as e:
        return f"网页抓取失败: {str(e)[:100]}"


@tool
async def get_datetime(
    query: Annotated[str, "时间查询，如 now / tomorrow / +3d"],
) -> str:
    """"获取当前日期时间或进行日期计算。now=现在, tomorrow=明天, +Nd= N天后。"""
    now = datetime.now()
    q = query.strip().lower()

    if q in ("now", "现在", "当前时间"):
        return f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')})"

    if q in ("tomorrow", "明天"):
        t = now + timedelta(days=1)
        return f"明天: {t.strftime('%Y-%m-%d')} ({t.strftime('%A')})"

    if q in ("yesterday", "昨天"):
        t = now - timedelta(days=1)
        return f"昨天: {t.strftime('%Y-%m-%d')} ({t.strftime('%A')})"

    # 相对天数: +3d / -2d
    import re
    m = re.match(r"^([+-]\d+)d$", q)
    if m:
        days = int(m.group(1))
        t = now + timedelta(days=days)
        return f"{'+' if days >= 0 else ''}{days}天后: {t.strftime('%Y-%m-%d')} ({t.strftime('%A')})"

    return f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')})"
