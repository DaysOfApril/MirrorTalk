import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\api\routes.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and patch _run_import_task to add debug logging after parsing
for i, line in enumerate(lines):
    # After "total_normalized = sum(..." line
    if 'total_normalized = sum(cnt for _, _, cnt in sender_info.values())' in line:
        # Add debug log after the existing log
        indent = line[:len(line) - len(line.lstrip())]
        insert_at = i + 2  # after the next logger.info line
        debug_line = f'{indent}logger.info("DEBUG sender_info: %d senders, names=%s", len(sender_info), list(sender_info.keys())[:10])\n'
        lines.insert(insert_at, debug_line)
        # Add another right after _parse_wrapper_or_jsonl return
        break

# Also add debug at the start of parsing
for i, line in enumerate(lines):
    if 'total, gen, member_map = await count_and_parse_messages(file_path)' in line:
        indent = line[:len(line) - len(line.lstrip())]
        insert_at = i + 1
        debug_line = f'{indent}logger.info("DEBUG parsing: total=%s member_map_keys=%s", total, len(member_map))\n'
        lines.insert(insert_at, debug_line)
        break

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Debug logs added to _run_import_task")

# Also add debug to _parse_wrapper_or_jsonl  
path2 = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\services\stream_parser.py'
with open(path2, 'r', encoding='utf-8') as f:
    lines2 = f.readlines()

for i, line in enumerate(lines2):
    if 'json.loads(first_line)' in line and 'try' in lines2[i-2] if i >= 2 else False:
        pass  # too fragile
    if 'return await _parse_jsonl(file_path)' in line and i > 90 and i < 120:
        indent = line[:len(line) - len(line.lstrip())]
        # Add debug before the return
        lines2.insert(i, f'{indent}logger.info("DEBUG: Routing to _parse_jsonl (first line parsed as JSON)")\n')
        break

with open(path2, 'w', encoding='utf-8') as f:
    f.writelines(lines2)

print("Debug logs added to stream_parser.py")
