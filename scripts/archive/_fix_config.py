import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\api\routes.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add per-provider fields to _build_config_response
old_response = '''    response = {
        "llm_provider": db_cfg.get("llm_provider") or settings.llm_provider,
        "llm_model": db_cfg.get("llm_model") or settings.llm_model,
        "llm_api_key": _mask_key(db_cfg["llm_api_key"]) if db_cfg.get("llm_api_key") else "",
        "llm_api_key_set": bool(db_cfg.get("llm_api_key")),
        "llm_base_url": db_cfg.get("llm_base_url") or settings.llm_base_url,
        "qwen_api_key": _mask_key(db_cfg["qwen_api_key"]) if db_cfg.get("qwen_api_key") else "",
        "qwen_api_key_set": bool(db_cfg.get("qwen_api_key")),
        "deepseek_api_key": _mask_key(db_cfg["deepseek_api_key"]) if db_cfg.get("deepseek_api_key") else "",
        "deepseek_api_key_set": bool(db_cfg.get("deepseek_api_key")),'''

new_response = '''    response = {
        "llm_provider": db_cfg.get("llm_provider") or settings.llm_provider,
        "llm_model": db_cfg.get("llm_model") or settings.llm_model,
        "llm_api_key": _mask_key(db_cfg["llm_api_key"]) if db_cfg.get("llm_api_key") else "",
        "llm_api_key_set": bool(db_cfg.get("llm_api_key")),
        "llm_base_url": db_cfg.get("llm_base_url") or settings.llm_base_url,
        # Per-provider configs
        "qwen_api_key": _mask_key(db_cfg["qwen_api_key"]) if db_cfg.get("qwen_api_key") else "",
        "qwen_api_key_set": bool(db_cfg.get("qwen_api_key")),
        "qwen_base_url": db_cfg.get("qwen_base_url") or "",
        "qwen_model": db_cfg.get("qwen_model") or "",
        "deepseek_api_key": _mask_key(db_cfg["deepseek_api_key"]) if db_cfg.get("deepseek_api_key") else "",
        "deepseek_api_key_set": bool(db_cfg.get("deepseek_api_key")),
        "deepseek_base_url": db_cfg.get("deepseek_base_url") or "",
        "deepseek_model": db_cfg.get("deepseek_model") or "",
        "ollama_api_key": _mask_key(db_cfg["ollama_api_key"]) if db_cfg.get("ollama_api_key") else "",
        "ollama_api_key_set": bool(db_cfg.get("ollama_api_key")),
        "ollama_base_url": db_cfg.get("ollama_base_url") or "",
        "ollama_model": db_cfg.get("ollama_model") or "",'''

content = content.replace(old_response, new_response)

# 2. Add per-provider fields to allowed_keys in update_config
old_allowed = '''    allowed_keys = {
        "llm_provider", "llm_model", "llm_base_url",
        "llm_api_key", "qwen_api_key", "deepseek_api_key", "openai_api_key", "ollama_api_key",
        "embed_mode", "embed_remote_provider", "embed_remote_model", "embed_remote_base_url",
        "embed_remote_api_key",
        "rerank_mode", "rerank_remote_provider", "rerank_remote_model", "rerank_remote_base_url",
        "rerank_remote_api_key",
    }'''

new_allowed = '''    allowed_keys = {
        "llm_provider", "llm_model", "llm_base_url",
        "llm_api_key", "qwen_api_key", "deepseek_api_key", "openai_api_key", "ollama_api_key",
        "qwen_base_url", "qwen_model",
        "deepseek_base_url", "deepseek_model",
        "ollama_base_url", "ollama_model",
        "embed_mode", "embed_remote_provider", "embed_remote_model", "embed_remote_base_url",
        "embed_remote_api_key",
        "rerank_mode", "rerank_remote_provider", "rerank_remote_model", "rerank_remote_base_url",
        "rerank_remote_api_key",
    }'''

content = content.replace(old_allowed, new_allowed)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Config endpoints updated with per-provider base_url/model")
