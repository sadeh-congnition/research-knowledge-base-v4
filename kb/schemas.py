from datetime import datetime
from typing import Any

from ninja import Schema


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


class ResourceOut(Schema):
    id: int
    url: str
    resource_type: str
    extracted_text: str
    date_created: datetime


class ResourceListOut(Schema):
    id: int
    url: str
    resource_type: str
    date_created: datetime


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
    provider: str
    api_key: str | None = None


class LLMConfigIn(Schema):
    name: str
    model_name: str
    provider: str
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
    resource_id: int
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
