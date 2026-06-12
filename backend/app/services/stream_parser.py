# MirrorTalk - 流式消息解析器（支持 JSON 数组 / Wrapper 对象 / JSONL）
import json
import logging
from pathlib import Path
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


async def count_and_parse_messages(
    file_path: str | Path,
) -> tuple[int, AsyncGenerator, dict]:
    """Count total messages & return async generator that yields normalized messages.

    Supports 3 formats:
      - JSON array: [{sender, content}, ...]           → ijson 流式（无 ijson 则全量加载）
      - Wrapper object: {members: [...], messages: [...]} → ijson 流式
      - JSONL: one JSON object per line                → 逐行读取
    """
    file_path = Path(file_path)

    # Detect format by first non-blank character
    first_char = ""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                first_char = stripped[0]
                break

    if first_char == "[":
        return await _parse_json_array(file_path)
    elif first_char == "{":
        return await _parse_wrapper_or_jsonl(file_path)
    else:
        return await _parse_jsonl(file_path)


# ========== JSON Array: [{...}, {...}] ==========


async def _empty_gen():
    """Empty async generator."""
    return
    yield  # pragma: no cover

async def _parse_json_array(file_path: Path) -> tuple[int, AsyncGenerator, dict]:
    """Streaming parse of top-level JSON array using ijson."""
    import asyncio

    # Quick approximate count
    total = 0
    with open(file_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            stripped = line.strip()
            if stripped in ("[", "]", ""):
                continue
            if stripped.startswith("{"):
                total += 1

    async def generator():
        try:
            import ijson
            loop = asyncio.get_event_loop()

            def sync_items():
                items = []
                with open(file_path, "r", encoding="utf-8-sig") as f:
                    for item in ijson.items(f, "item"):
                        items.append(item)
                return items

            all_items = await loop.run_in_executor(None, sync_items)
            for item in all_items:
                if isinstance(item, dict):
                    yield item
        except ImportError:
            logger.warning("ijson not installed, falling back to full-file json.load (may OOM on large files)")
            with open(file_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            for item in data:
                if isinstance(item, dict):
                    yield item

    return total, generator(), {}


# ========== Wrapper Object: {members: [...], messages: [...]} ==========

async def _parse_wrapper_or_jsonl(file_path: Path) -> tuple[int, AsyncGenerator, dict]:
    """Detect wrapper-object vs JSONL by trying to parse the first non-blank line."""
    first_line = ""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                first_line = stripped
                break

    if not first_line:
        return 0, _empty_gen(), {}

    # Try parsing first line as a full JSON object (JSONL detection)
    try:
        obj = json.loads(first_line)
        if isinstance(obj, dict):
            # JSONL: single-line JSON objects (e.g. CipherTalk JSONL with _type field)
            logger.info("DEBUG: Routing to _parse_jsonl (first line parsed as JSON)")
            return await _parse_jsonl(file_path)
    except json.JSONDecodeError:
        pass

    # If first line is just '{' or '[', it's a multi-line JSON (wrapper or array)
    if first_line == "{" or first_line == "[":
        with open(file_path, "r", encoding="utf-8-sig") as f:
            head = f.read(65536)
        # Check for wrapper-object markers
        if '"messages"' in head or '"message"' in head or '"chatlab"' in head:
            return await _parse_wrapper_object(file_path)
        if first_line == "[":
            return await _parse_json_array(file_path)
        # Fallback: try as wrapper
        return await _parse_wrapper_object(file_path)

    # Unknown format, try JSONL as last resort
    return await _parse_jsonl(file_path)


async def _parse_wrapper_object(file_path: Path) -> tuple[int, AsyncGenerator, dict]:
    """Parse {members: [...], messages: [...]} wrapper format with ijson streaming."""
    import asyncio

    member_map = {}
    messages_raw = []

    try:
        import ijson
        loop = asyncio.get_event_loop()

        def sync_parse():
            members = []
            msgs = []
            with open(file_path, "r", encoding="utf-8-sig") as f:
                parser = ijson.parse(f)
                current_key = None
                in_messages = False
                obj_depth = 0
                obj_started = False
                obj_buf = ""

                for prefix, event, value in parser:
                    # Track members
                    if prefix == "members.item" and event == "start_map":
                        obj_started = True
                        obj_buf = ""
                    elif prefix.startswith("members.item.") and obj_started:
                        if event == "string":
                            obj_buf += value
                    elif prefix == "members.item" and event == "end_map":
                        obj_started = False

                    # Track messages (store as raw dicts)
                    if prefix == "messages.item" and event == "start_map":
                        obj_started = True
                        current_obj = {}
                        current_key = None
                    elif prefix.startswith("messages.item.") and obj_started:
                        key = prefix.split(".")[-1]
                        if event == "map_key":
                            current_key = value
                        elif event in ("string", "number", "boolean", "null") and current_key:
                            current_obj[current_key] = value
                            current_key = None
                    elif prefix == "messages.item" and event == "end_map":
                        obj_started = False
                        if current_obj:
                            msgs.append(current_obj)
                            current_obj = {}

            # Extract member map
            # Since ijson member extraction is complex, do a second simpler pass
            with open(file_path, "r", encoding="utf-8-sig") as f:
                # Read just the members section
                content = f.read(65536)  # First 64KB should cover members
                try:
                    # Try to extract members with a quick partial parse
                    import re
                    members_section = re.search(r'"members"\s*:\s*\[(.*?)\]', content, re.DOTALL)
                    if members_section:
                        members_text = "[" + members_section.group(1) + "]"
                        members = json.loads(members_text)
                except Exception:
                    members = []

            for m in members:
                pid = m.get("platformId", "")
                aname = m.get("accountName", "")
                if pid and aname:
                    member_map[pid] = aname

            return member_map, msgs

        member_map, messages_raw = await loop.run_in_executor(None, sync_parse)

    except ImportError:
        logger.warning("ijson not installed, falling back to full-file json.load")
        with open(file_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)

        for m in data.get("members", []):
            pid = m.get("platformId", "")
            aname = m.get("accountName", "")
            if pid and aname:
                member_map[pid] = aname

        messages = data.get("messages", data.get("message", []))
        if isinstance(messages, dict):
            messages = messages.get("messages", messages.get("message", []))
        messages_raw = messages

    total = len(messages_raw)

    async def gen():
        for item in messages_raw:
            if isinstance(item, dict):
                yield item

    return total, gen(), member_map


# ========== JSONL: one JSON per line ==========

async def _parse_jsonl(file_path: Path) -> tuple[int, AsyncGenerator, dict]:
    """Parse JSONL: one JSON object per line. Truly streaming."""
    total = 0
    with open(file_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                total += 1

    async def generator():
        with open(file_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    item = json.loads(stripped)
                    if isinstance(item, dict):
                        yield item
                except json.JSONDecodeError:
                    logger.debug(f"Skipping non-JSON line: {stripped[:80]}")

    return total, generator(), {}


# ========== Message Normalization ==========

def normalize_message(msg: dict, member_map: dict | None = None) -> dict | None:
    """Normalize a raw message dict into {sender, content, timestamp} format."""
    if not isinstance(msg, dict):
        return None

    raw_sender = (
        msg.get("accountName", "") or
        msg.get("sender", "") or
        msg.get("Sender", "") or
        msg.get("speaker", "") or
        msg.get("Speaker", "")
    )
    content = (
        msg.get("content") or
        msg.get("Content") or
        msg.get("text") or
        msg.get("Text") or
        msg.get("message") or
        msg.get("Message") or
        ""
    )
    timestamp = (
        msg.get("timestamp") or
        msg.get("Timestamp") or
        msg.get("time") or
        msg.get("Time") or
        msg.get("created_at") or
        ""
    )

    if member_map:
        raw_sender = member_map.get(raw_sender, raw_sender)

    if not content or not isinstance(content, str) or not content.strip():
        return None

    # Skip system messages like [image], [audio]
    if content.startswith("[") and content.endswith("]") and len(content) < 20:
        return None

    result = {"sender": raw_sender, "content": content.strip()}
    if timestamp:
        result["timestamp"] = str(timestamp)
    return result
