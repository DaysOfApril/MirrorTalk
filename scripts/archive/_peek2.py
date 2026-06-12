import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open(r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\data\uploads\2cc22968a1ba4acf_微信不是法外之地.json', 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Find key names at root level
import re
# Find all top-level keys
keys = re.findall(r'\n  "(\w+)":', content[:10000])
print("Top-level keys:", keys)

# Find messages-related keys
for key in ['sessions','messages','message','topics','events','talks']:
    idx = content.find(f'\n  "{key}":')
    if idx >= 0:
        print(f'Key "{key}" at pos {idx}, preview: {content[idx:idx+200]}')
