import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\services\provider.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Turn off streaming to debug the '"type"' KeyError
old = '''    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.7,
        streaming=True,
    )'''

new = '''    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.7,
        streaming=False,
    )'''

content = content.replace(old, new)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Streaming disabled for debugging")
