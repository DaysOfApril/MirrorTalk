import sys, io, asyncio, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import importlib.util
spec = importlib.util.spec_from_file_location("sp", r"D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\services\stream_parser.py")
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)

async def test_full_pipeline():
    path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\data\uploads\f78d112c0d5a47d1_如果群里有帅逼，那一定是我.jsonl'
    
    total, gen, member_map = await sp.count_and_parse_messages(path)
    print(f'total={total}, member_map keys={len(member_map)}')
    if member_map:
        items = list(member_map.items())[:5]
        print(f'  sample: {items}')
    
    parsed = 0
    valid = 0
    senders = {}
    async for msg in gen:
        parsed += 1
        norm = sp.normalize_message(msg, member_map)
        if norm:
            valid += 1
            s = norm['sender']
            senders[s] = senders.get(s, 0) + 1
        if parsed <= 5:
            print(f'  [{parsed}] _type={msg.get("_type","?")} norm={bool(norm)} sender={norm["sender"] if norm else "N/A"}')
    
    print(f'\nParsed: {parsed}')
    print(f'Valid: {valid}')
    print(f'Senders: {len(senders)}')
    print(f'>=5: {sum(1 for v in senders.values() if v >= 5)}')
    print(f'<5: {sum(1 for v in senders.values() if v < 5)}')
    print(f'Top 5: {sorted(senders.items(), key=lambda x: -x[1])[:5]}')

asyncio.run(test_full_pipeline())
