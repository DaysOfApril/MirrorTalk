import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\services\provider.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old_create = '''def create_llm(config: ProviderConfig) -> BaseChatModel:
    """根据 ProviderConfig 创建 LangChain ChatModel"""
    api_key = config.api_key or _resolve_config("llm_api_key", settings.llm_api_key)
    base_url = config.base_url or _resolve_config("llm_base_url", settings.llm_base_url)
    model = config.model or _resolve_config("llm_model", settings.llm_model)

    info = get_provider_info(config.provider)
    if info and not base_url:
        base_url = info.base_url

    # Providers that don't require an API key (e.g. local Ollama)
    if info and info.optional_api_key and not api_key:
        api_key = "not-needed"

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.7,
        streaming=True,
    )'''

new_create = '''def create_llm(config: ProviderConfig) -> BaseChatModel:
    """根据 ProviderConfig 创建 LangChain ChatModel
    解析优先级: 调用参数 > DB配置 > .env > 内置默认值
    """
    provider = config.provider
    info = get_provider_info(provider)

    # --- API Key: per-provider > global > env ---
    api_key = config.api_key or ""
    if not api_key and provider:
        # Try per-provider key from DB or .env (e.g. qwen_api_key, deepseek_api_key)
        provider_key = getattr(settings, f"{provider}_api_key", "")
        api_key = _resolve_config(f"{provider}_api_key", provider_key)
    if not api_key:
        api_key = _resolve_config("llm_api_key", settings.llm_api_key)

    # --- Base URL: per-provider > global > builtin default ---
    base_url = config.base_url or ""
    if not base_url and provider:
        base_url = _resolve_config(f"{provider}_base_url", "")
    if not base_url:
        base_url = _resolve_config("llm_base_url", settings.llm_base_url)
    if info and not base_url:
        base_url = info.base_url

    # --- Model: per-provider > global > builtin default ---
    model = config.model or ""
    if not model and provider:
        model = _resolve_config(f"{provider}_model", "")
    if not model:
        model = _resolve_config("llm_model", settings.llm_model)
    if info and not model and info.models:
        model = info.models[0]

    # Providers that don't require an API key (e.g. local Ollama)
    if info and info.optional_api_key and not api_key:
        api_key = "not-needed"

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.7,
        streaming=True,
    )'''

content = content.replace(old_create, new_create)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("create_llm updated with per-provider resolution")
