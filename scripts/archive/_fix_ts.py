import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\frontend\src\pages\SettingsPage.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix template literals to string concatenation
content = content.replace("config[${pid}_api_key_set as keyof AppConfig]", "config[(pid + '_api_key_set') as keyof AppConfig]")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed template literals")
