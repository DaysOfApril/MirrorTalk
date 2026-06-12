# MirrorTalk - Provider 模式：统一 LLM 工厂
from __future__ import annotations

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import settings
from app.models import ProviderConfig, ProviderInfo, ProviderProtocol
from app.services.database import get_config

# ========== 内置 Provider 注册表 ==========

BUILTIN_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        id="openai", name="openai", display_name="OpenAI",
        protocol=ProviderProtocol.OPENAI_RESPONSES,
        base_url="https://api.openai.com/v1",
        models=["gpt-4o", "gpt-4o-mini", "gpt-4.1"],
    ),
    ProviderInfo(
        id="deepseek", name="deepseek", display_name="DeepSeek",
        protocol=ProviderProtocol.OPENAI_COMPATIBLE,
        base_url="https://api.deepseek.com/v1",
        models=["deepseek-chat", "deepseek-reasoner"],
    ),
    ProviderInfo(
        id="qwen", name="qwen", display_name="通义千问 (Qwen)",
        protocol=ProviderProtocol.OPENAI_COMPATIBLE,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=["qwen-plus", "qwen-max", "qwen-turbo"],
    ),
    ProviderInfo(
        id="ollama", name="ollama", display_name="Ollama (本地)",
        protocol=ProviderProtocol.OPENAI_COMPATIBLE,
        base_url="http://localhost:11434/v1",
        models=["llama3.2", "qwen2.5:7b", "deepseek-r1:8b", "mistral"],
        optional_api_key=True,
    ),
    ProviderInfo(
        id="custom", name="custom", display_name="自定义",
        protocol=ProviderProtocol.OPENAI_COMPATIBLE,
        base_url="",
        models=[],
        allow_custom_base_url=True,
    ),
]


def _resolve_config(key: str, fallback: str = "") -> str:
    """优先读数据库配置，否则回退到 .env"""
    db_val = get_config(key)
    return db_val if db_val else fallback


def get_provider_info(provider_id: str) -> Optional[ProviderInfo]:
    for p in BUILTIN_PROVIDERS:
        if p.id == provider_id:
            return p
    return None


def list_providers() -> list[ProviderInfo]:
    return BUILTIN_PROVIDERS


def create_llm(config: ProviderConfig) -> BaseChatModel:
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
        streaming=False,
    )

