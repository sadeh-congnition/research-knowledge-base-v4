from typing import Any, Union
from django.conf import settings
import httpx
import numpy as np

from chonkie import SemanticChunker
from chonkie.embeddings.base import BaseEmbeddings
from chonkie.tokenizer import CharacterTokenizer
from kb.models import EmbeddingModelConfig


class LMStudioEmbeddings(BaseEmbeddings):
    """Custom embedding handler for Chonkie that uses LMStudio."""

    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name
        self._dimension: Union[int, None] = None
        self._tokenizer = CharacterTokenizer()

    def embed(self, text: str) -> np.ndarray:
        """Embed a single text."""
        res = self.embed_batch([text])[0]
        return res

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Embed a batch of texts."""
        response = httpx.post(
            f"{settings.LMSTUDIO_BASE_URL}/v1/embeddings",
            json={
                "model": self.model_name,
                "input": texts,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        embeddings = [
            np.array(item["embedding"], dtype=np.float32) for item in data["data"]
        ]

        if self._dimension is None and embeddings:
            self._dimension = len(embeddings[0])

        return embeddings

    @property
    def dimension(self) -> int:
        """Return the dimension of the embedding vectors."""
        if self._dimension is None:
            # Trigger a small embedding to get the dimension
            self.embed("test")
        assert self._dimension is not None
        return int(self._dimension)

    def get_tokenizer(self) -> Any:
        """Return a basic tokenizer."""
        return self._tokenizer


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
        model_name = config_details.get(
            "embedding_model", "text-embedding-embeddinggemma-300m"
        )

    # Use our custom LMStudio embedding handler
    embeddings = LMStudioEmbeddings(model_name=model_name)

    chunker = SemanticChunker(
        embedding_model=embeddings,
        threshold=config_details.get("threshold", 0.7),
        chunk_size=config_details.get("chunk_size", 512),
        similarity_window=config_details.get("similarity_window", 3),
        skip_window=config_details.get("skip_window", 0),
    )

    chunks = chunker.chunk(text)
    return [chunk.text for chunk in chunks]
