import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\frontend\src\pages\SettingsPage.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix handleTest to skip masked API keys
old_test = """        api_key: form(pid).api_key || "",

      body: JSON.stringify({"""

new_test = """        // If the form shows a masked key (loaded from DB), pass empty so backend uses saved key
        api_key: (form(pid).api_key && !form(pid).api_key.includes('****')) ? form(pid).api_key : "",

      body: JSON.stringify({"""

content = content.replace(old_test, new_test)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed test connection masked key handling")
