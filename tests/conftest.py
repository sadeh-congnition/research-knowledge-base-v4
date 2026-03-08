import pytest
from model_bakery import baker

from kb.models import Chunk, ChunkConfig, LLMConfig, Resource, Secret


@pytest.fixture
def secret(db) -> Secret:
    return baker.make(Secret, title="TEST_API_KEY", value="test-secret-value")


@pytest.fixture
def jina_secret(db) -> Secret:
    return baker.make(Secret, title="JINA_API_KEY", value="test-jina-key")


@pytest.fixture
def chunk_config(db) -> ChunkConfig:
    return baker.make(
        ChunkConfig,
        name="test-chunk-config",
        details={
            "embedding_model": "test-model",
            "threshold": 0.7,
            "chunk_size": 512,
            "similarity_window": 3,
            "skip_window": 0,
        },
    )


@pytest.fixture
def resource(db) -> Resource:
    return baker.make(
        Resource,
        url="https://example.com/test-paper",
        resource_type=Resource.ResourceType.PAPER,
        extracted_text="This is test content from a paper.",
    )


@pytest.fixture
def resource_with_chunks(db, resource, chunk_config) -> Resource:
    baker.make(
        Chunk,
        text="First chunk of text.",
        order=0,
        resource=resource,
        chunk_config=chunk_config,
    )
    baker.make(
        Chunk,
        text="Second chunk of text.",
        order=1,
        resource=resource,
        chunk_config=chunk_config,
    )
    return resource


@pytest.fixture
def llm_config(db, secret) -> LLMConfig:
    return baker.make(
        LLMConfig,
        name="test-llm",
        model_name="ollama_chat/qwen3:4b",
        is_default=True,
        secret=secret,
    )
