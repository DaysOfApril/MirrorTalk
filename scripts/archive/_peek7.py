import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open(r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\data\uploads\f78d112c0d5a47d1_如果群里有帅逼，那一定是我.jsonl', 'r', encoding='utf-8-sig') as f:
    for i, line in enumerate(f):
        stripped = line.strip()
        if stripped and '"_type":"message"' in stripped:
            print(f'Line {i+1}: {stripped[:300]}')
            break
