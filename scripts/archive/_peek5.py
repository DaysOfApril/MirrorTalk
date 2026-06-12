import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open(r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\data\uploads\2cc22968a1ba4acf_微信不是法外之地.json', 'r', encoding='utf-8-sig') as f:
    content = f.read()

print(f'File size: {len(content)} chars')
print(f'First non-blank char: {content.strip()[0]}')
print(f'"chatlab" in first 64KB: {"chatlab" in content[:65536]}')
print(f'"messages" in first 64KB: {"messages" in content[:65536]}')
print(f'"_type" anywhere: {"_type" in content}')

# Show area around the error string
idx = content.find('52961657225@chatroom')
if idx > 0:
    # Find the closest bracket context
    before = content[max(0,idx-200):idx]
    after = content[idx:idx+200]
    print('---Before---')
    print(before[-150:])
    print('---After---')
    print(after[:150])
