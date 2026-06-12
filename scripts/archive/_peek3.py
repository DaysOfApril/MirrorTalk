import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open(r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\data\uploads\2cc22968a1ba4acf_微信不是法外之地.json', 'r', encoding='utf-8-sig') as f:
    content = f.read(3000)
    # Show last 1000 chars of the 3000-char sample
    print(content[2000:3000])
