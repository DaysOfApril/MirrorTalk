# MirrorTalk - 核心数据模型
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ========== Provider ==========

class ProviderProtocol(str, Enum):
    OPENAI_RESPONSES = "openai-responses"
    OPENAI_COMPATIBLE = "openai-compatible"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


class ProviderInfo(BaseModel):
    id: str
    name: str
    display_name: str
    protocol: ProviderProtocol
    base_url: str = ""
    models: list[str] = []
    allow_custom_base_url: bool = False
    optional_api_key: bool = False


class ProviderConfig(BaseModel):
    """运行时 Provider 配置"""
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    protocol: ProviderProtocol = ProviderProtocol.OPENAI_COMPATIBLE


# ========== 记忆/知识库 ==========

class MemorySourceType(str, Enum):
    PROFILE = "profile"          # 用户画像
    FACT = "fact"                # 原子事实
    RELATIONSHIP = "relationship"  # 人际关系
    EXTERNAL = "external"       # 外部文件导入


class MemorySource(str, Enum):
    USER_SPEECH = "user_speech"       # 用户发言
    FRIEND_SPEECH = "friend_speech"   # 好友发言
    SHARED = "shared"                 # 双方共享
    EXTERNAL_FILE = "external_file"   # 外部文件


class ChunkInfo(BaseModel):
    """分块元信息"""
    parent_id: Optional[int] = None  # 所属父块ID，None表示自身即父
    chunk_index: int = 0              # 在同级兄弟中的序号
    chunk_count: int = 1              # 同级兄弟总数


class MemoryItem(BaseModel):
    id: int
    source_type: MemorySourceType
    source: MemorySource
    content: str
    title: str = ""
    session_id: Optional[str] = None
    confidence: float = 0.5
    importance: float = 0.5
    tags: list[str] = []
    parent_id: Optional[int] = None
    chunk_index: int = 0
    chunk_count: int = 1
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class RecallResult(BaseModel):
    items: list[MemoryItem]
    mode: str  # "hybrid" | "keyword"
    retrieval_info: dict = {}
    trace_id: str = ""  # ?????? ID?????????


# ========== 人格 (Persona) ==========

class StyleTags(BaseModel):
    """风格标签"""
    personality: list[str] = []      # 性格: ["内向", "细心"]
    catchphrases: list[str] = []     # 口头禅: ["笑死", "好家伙"]
    sentence_style: str = ""         # 句式: "短句为主"
    emoji_style: str = ""            # 表情包: "重度用户"
    tone: str = ""                   # 语气: "温柔"


class OceanScores(BaseModel):
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5


class PersonaProfile(BaseModel):
    """用户/好友 画像"""
    id: str  # friend_id
    name: str
    style: StyleTags = Field(default_factory=StyleTags)
    ocean: OceanScores = Field(default_factory=OceanScores)
    # 聚合来源信息
    source_count: int = 1
    is_aggregated: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


# ========== 对话 ==========

class ConversationInfo(BaseModel):
    id: str
    persona_id: str
    agent_type: str  # "friend" | "persona"
    title: str = "新对话"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ChatMessage(BaseModel):
    id: Optional[int] = None
    conversation_id: str
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime = Field(default_factory=datetime.now)


class ChatRequest(BaseModel):
    """前端发送的聊天请求"""
    conversation_id: Optional[str] = None  # None = 新对话
    persona_id: str                        # 好友ID
    agent_type: str = "friend"             # "friend" | "persona"
    message: str


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    persona_check: Optional[dict] = None



# ========== ??????? ==========

class RetrievalFeedback(BaseModel):
    """??????????/????"""
    trace_id: str                                # ????? trace_id
    query_text: str = ""                         # ???????
    thumbs: Optional[bool] = None                # True=?, False=?, None=???
    rating: Optional[int] = None                 # 1-5 ??
    clicked_ids: list[int] = []                  # ????/??? memory_ids
    session_id: Optional[str] = None             # ????? session
    created_at: datetime = Field(default_factory=datetime.now)


class RetrievalEvalResult(BaseModel):
    """??????"""
    mrr: float = 0.0
    recall_at_1: float = 0.0
    recall_at_3: float = 0.0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    ndcg_at_5: float = 0.0
    ndcg_at_10: float = 0.0
    query_count: int = 0


class EvalQuery(BaseModel):
    """??????????? query"""
    id: str
    query: str
    relevant_ids: list[int]
    relevance_scores: list[int] = []  # ????? NDCG ??