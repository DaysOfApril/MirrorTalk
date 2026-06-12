import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Directly test normalize_message from the module
import importlib.util
spec = importlib.util.spec_from_file_location("sp", r"D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\services\stream_parser.py")
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)

with open(r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\data\uploads\f78d112c0d5a47d1_如果群里有帅逼，那一定是我.jsonl', 'r', encoding='utf-8-sig') as f:
    total = 0
    valid = 0
    senders = {}
    for i, line in enumerate(f):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            msg = json.loads(stripped)
        except:
            continue
        if msg.get('_type') != 'message':
            continue
        total += 1
        norm = sp.normalize_message(msg, {})
        if norm:
            valid += 1
            s = norm['sender']
            senders[s] = senders.get(s, 0) + 1
        else:
            if valid < 5:
                print(f'  FILTERED: sender={msg.get("accountName","?")} content_repr={repr(msg.get("content",""))[:80]}')

print(f'\nTotal messages: {total}')
print(f'Valid (passed normalize): {valid}')
print(f'Unique senders: {len(senders)}')
print(f'Top 10: {sorted(senders.items(), key=lambda x: -x[1])[:10]}')
print(f'Senders with >=5 msgs: {sum(1 for v in senders.values() if v >= 5)}')
print(f'Senders with <5 msgs: {sum(1 for v in senders.values() if v < 5)}')
