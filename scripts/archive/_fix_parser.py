import json, sys, io

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\services\stream_parser.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find _parse_wrapper_or_jsonl function and fix it
old_func = '''async def _parse_wrapper_or_jsonl(file_path: Path) -> tuple[int, AsyncGenerator, dict]:
    """Detect wrapper-object vs JSONL by checking first line for 'messages' key."""
    first_line = ""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                first_line = stripped
                break

    if '"messages"' in first_line or '"message"' in first_line:
        return await _parse_wrapper_object(file_path)
    else:
        return await _parse_jsonl(file_path)'''

new_func = '''async def _parse_wrapper_or_jsonl(file_path: Path) -> tuple[int, AsyncGenerator, dict]:
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

content = content.replace(old_func, new_func)
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# Verify
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i in range(85, 105):
    print(f'{i+1}: {lines[i].rstrip()}')
print('--- Done ---')
