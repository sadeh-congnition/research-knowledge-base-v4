from typing import Any

from chonkie import SemanticChunker
from kb.models import EmbeddingModelConfig


def chunk_text(text: str, config_details: dict[str, Any]) -> list[str]:
    """Chunk text using Chonkie SemanticChunker.

    Args:
        text: The text to chunk.
        config_details: Configuration dict from ChunkConfig.details.

    Returns:
        List of chunk text strings in order.
    """
    embedding_config = EmbeddingModelConfig.objects.filter(is_active=True).first()
    if embedding_config:
        model_name = embedding_config.model_name
    else:
        model_name = config_details.get("embedding_model", "minishlab/potion-base-32M")

    chunker = SemanticChunker(
        embedding_model=model_name,
        threshold=config_details.get("threshold", 0.7),
        chunk_size=config_details.get("chunk_size", 512),
        similarity_window=config_details.get("similarity_window", 3),
        skip_window=config_details.get("skip_window", 0),
    )

    chunks = chunker.chunk(text)
    return [chunk.text for chunk in chunks]
