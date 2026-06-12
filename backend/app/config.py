# MirrorTalk Backend - 配置与设置
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MIRRORTALK_",
    )

    # ---- 路径 ----
    data_dir: Path = Path("data")
    chroma_dir: Path = Path("data/chroma")
    sqlite_path: Path = Path("data/mirrortalk.db")

    # ---- LLM 默认 Provider ----
    llm_provider: Literal["openai", "deepseek", "qwen", "custom"] = "qwen"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "qwen-plus"
    # ? provider ?? API key????????DB?env??fallback?
    qwen_api_key: str = ""
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    ollama_api_key: str = ""  # ollama ???? key

    # ---- Embedding ----
    embed_mode: Literal["local", "remote"] = "local"
    embed_local_model: str = "BAAI/bge-m3"
    embed_remote_provider: str = "openai"
    embed_remote_api_key: str = ""
    embed_remote_base_url: str = ""
    embed_remote_model: str = "text-embedding-3-small"

    # ---- Rerank ----
    rerank_mode: Literal["local", "remote"] = "local"
    rerank_local_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_remote_provider: str = "custom"
    rerank_remote_api_key: str = ""
    rerank_remote_base_url: str = ""
    rerank_remote_model: str = ""

    # ---- RRF 融合 ----
    rrf_k: int = 60
    rrf_weight_fts: float = 1.0
    rrf_weight_vector: float = 1.0

    # ---- 检索指标 ----
    retrieval_metrics_enabled: bool = False
    retrieval_metrics_log_interval: int = 100

    # ---- 服务 ----
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
