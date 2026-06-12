import json, sys, io

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\services\stream_parser.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old_func = '''async def _parse_wrapper_or_jsonl(file_path: Path) -> tuple[int, AsyncGenerator, dict]:
    """Detect wrapper-object vs JSONL by scanning first 64KB for 'messages' key."""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        head = f.read(65536)

    # Check if this looks like a wrapper object: top-level JSON with "messages" array
    if '"messages"' in head or '"message"' in head:
        return await _parse_wrapper_object(file_path)

    # Also check for nested message containers (e.g. CipherTalk: chatlab > messages)
    if '"chatlab"' in head:
        return await _parse_wrapper_object(file_path)

    return await _parse_jsonl(file_path)'''

new_func = '''async def _parse_wrapper_or_jsonl(file_path: Path) -> tuple[int, AsyncGenerator, dict]:
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
    return await _parse_jsonl(file_path)'''

content = content.replace(old_func, new_func)

# Add _empty_gen helper
if 'def _empty_gen' not in content:
    insert_pos = content.find('async def _parse_json_array')
    helper = '''
async def _empty_gen():
    """Empty async generator."""
    return
    yield  # pragma: no cover

'''
    content = content[:insert_pos] + helper + content[insert_pos:]

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# Verify
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i in range(82, 120):
    print(f'{i+1}: {lines[i].rstrip()}')
