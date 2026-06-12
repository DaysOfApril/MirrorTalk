import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open(r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\data\uploads\f78d112c0d5a47d1_如果群里有帅逼，那一定是我.jsonl', 'r', encoding='utf-8-sig') as f:
    lines = [json.loads(line.strip()) for line in f if line.strip()]

# Count by _type
from collections import Counter
types = Counter(l['_type'] for l in lines)
print('Type counts:', dict(types))

# Show sample messages of each type
for t in types:
    samples = [l for l in lines if l.get('_type') == t][:3]
    print(f'\n=== _type={t} ({len([l for l in lines if l.get("_type")==t])} total) ===')
    for s in samples:
        print(json.dumps(s, ensure_ascii=False)[:300])
        print('---')

# Check message content types
msgs = [l for l in lines if l.get('_type') == 'message']
content_types = Counter(type(m.get('content')).__name__ for m in msgs)
print('\nContent field types in messages:', dict(content_types))

# Check type field values
type_vals = Counter(m.get('type') for m in msgs)
print('Type field values:', dict(type_vals))

# Sample message with type != 0
for m in msgs:
    if m.get('type') != 0:
        print('\nNon-type-0 message:', json.dumps(m, ensure_ascii=False)[:300])
        break
