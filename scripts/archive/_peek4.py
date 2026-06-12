import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open(r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\data\uploads\2cc22968a1ba4acf_微信不是法外之地.json', 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Find the section between members array end and messages array start
members_end = content.find('"platformId": "52961657225@chatroom"')
if members_end > 0:
    # Show 500 chars after this
    chunk = content[members_end:members_end+800]
    print(chunk)
    print('---')
    # Also find the _type keyword
    type_idx = content.find('"_type"')
    if type_idx > 0:
        print(f'Found "_type" at position {type_idx}')
        print(content[type_idx:type_idx+200])
