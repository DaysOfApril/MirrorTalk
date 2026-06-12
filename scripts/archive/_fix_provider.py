import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\services\provider.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    api_key = config.api_key or _resolve_config("llm_api_key", settings.llm_api_key)
    base_url = config.base_url or _resolve_config("llm_base_url", settings.llm_base_url)
    model = config.model or _resolve_config("llm_model", settings.llm_model)

    info = get_provider_info(config.provider)
    if info and not base_url:
        base_url = info.base_url

    return ChatOpenAI('''

new = '''    api_key = config.api_key or _resolve_config("llm_api_key", settings.llm_api_key)
    base_url = config.base_url or _resolve_config("llm_base_url", settings.llm_base_url)
    model = config.model or _resolve_config("llm_model", settings.llm_model)

    info = get_provider_info(config.provider)
    if info and not base_url:
        base_url = info.base_url

    # Providers that don't require an API key (e.g. local Ollama)
    if info and info.optional_api_key and not api_key:
        api_key = "not-needed"

    return ChatOpenAI('''

content = content.replace(old, new)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed create_llm for optional_api_key providers")
