from datetime import datetime
from typing import Any

from ninja import Schema
from kb.services.llm import LLMProvider


# --- Secret Schemas ---


class SecretIn(Schema):
    title: str
    value: str


class SecretOut(Schema):
    id: int
    title: str
    date_created: datetime


# --- Resource Schemas ---


class ResourceIn(Schema):
    url: str
    resource_type: str  # "paper" or "blog_post"


class ReferenceOut(Schema):
    id: int
    description: str
    date_created: datetime


class ResourceOut(Schema):
    id: int
    url: str
    title: str
    resource_type: str
    extracted_text: str
    summary: str
    references: list[ReferenceOut]
    date_created: datetime


class ResourceListOut(Schema):
    id: int
    url: str
    title: str
    resource_type: str
    date_created: datetime


class ResourceStreamUpdate(Schema):
    status: str
    type: str  # "status" or "result"
    resource: ResourceOut | None = None


# --- ChunkConfig Schemas ---


class ChunkConfigOut(Schema):
    id: int
    name: str
    details: dict[str, Any]


# --- TextExtractionConfig Schemas ---


class TextExtractionConfigOut(Schema):
    id: int
    title: str
    details: dict[str, Any]
    date_created: datetime


# --- Chunk Schemas ---


class ChunkOut(Schema):
    id: int
    text: str
    order: int
    resource_id: int
    chunk_config_id: int


# --- LLMConfig Schemas ---


class DefaultLLMConfigIn(Schema):
    model_name: str
    provider: LLMProvider
    api_key: str | None = None


class LLMConfigIn(Schema):
    name: str
    model_name: str
    provider: LLMProvider
    is_default: bool = False
    secret_id: int | None = None


class LLMConfigOut(Schema):
    id: int
    name: str
    model_name: str
    provider: str
    is_default: bool
    secret_id: int | None
    date_created: datetime
    test_response: str | None = None


# --- EmbeddingModelConfig Schemas ---


class EmbeddingStatusOut(Schema):
    is_valid: bool
    message: str
    provider: str | None = None
    model_name: str | None = None


# --- Chat Schemas ---


class ChatMessageIn(Schema):
    resource_id: int | None = None
    chat_id: int | None = None
    message: str
    llm_config_id: int | None = None  # Uses default if not specified


class ChatMessageOut(Schema):
    chat_id: int
    user_message: str
    ai_message: str


class ChatHistoryOut(Schema):
    id: int
    type: str
    text: str
    date_created: datetime


class ChatListOut(Schema):
    id: int
    resource_id: int
    resource_url: str
    resource_title: str
    resource_summary: str
    last_message: str
    date_updated: datetime


# --- Search Schemas ---


class SemanticSearchOut(Schema):
    document: str
    distance: float
    resource_id: int
    chunk_order: int


class ChunkContextOut(Schema):
    text: str
    order: int
    is_target: bool


class SearchContextOut(Schema):
    chunks: list[ChunkContextOut]


# --- KnowledgeGraphConfig Schemas ---


class KnowledgeGraphConfigIn(Schema):
    name: str
    package_name: str = "djangorag.lightrag_app"
    update_trigger: str = "always"
    is_active: bool = False


class KnowledgeGraphConfigOut(Schema):
    id: int
    name: str
    package_name: str
    update_trigger: str
    is_active: bool
    date_created: datetime
    date_updated: datetime
