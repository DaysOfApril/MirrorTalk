import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\pipelines\profile_builder.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add traceback logging to the LLM call
old_attempt = '''        for attempt in range(3):
            try:
                resp = await llm.ainvoke([
                    SystemMessage(content=FACT_EXTRACTION_PROMPT.format(chat_text=chat_text)),
                ])
                break
            except Exception as e:
                if attempt == 2:
                    raise
                logger.warning("LLM call failed (attempt %d/3): %s", attempt + 1, e)
                await asyncio.sleep(2 ** attempt)'''

new_attempt = '''        for attempt in range(3):
            try:
                resp = await llm.ainvoke([
                    SystemMessage(content=FACT_EXTRACTION_PROMPT.format(chat_text=chat_text)),
                ])
                break
            except Exception as e:
                import traceback as _tb
                logger.warning("LLM call failed (attempt %d/3): %s\\n%s", attempt + 1, e, _tb.format_exc())
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)'''

content = content.replace(old_attempt, new_attempt)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Added traceback logging to LLM calls")
