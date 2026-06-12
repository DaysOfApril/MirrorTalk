import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open(r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\data\uploads\f78d112c0d5a47d1_如果群里有帅逼，那一定是我.jsonl', 'r', encoding='utf-8-sig') as f:
    lines = []
    for i, line in enumerate(f):
        if i < 8:
            lines.append(line.rstrip()[:200])
        else:
            break
for i, line in enumerate(lines):
    print(f'Line {i+1}: {line}')
    print('---')
