import sys
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
# The exact broken pattern
bad = "datetime('\"'\"'now'\"'\"')"
good = "datetime('now')"
count = content.count(bad)
print(f"Found {count} occurrences")
content = content.replace(bad, good)
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Replacement done")
