import pytest
from kb.models import EmbeddingModelConfig
from kb.services.chromadb_service import _get_embeddings

@pytest.mark.django_db
def test_embedding_config_exists():
    """Verify that the default embedding config was seeded."""
    config = EmbeddingModelConfig.objects.filter(is_active=True).first()
    assert config is not None
    assert config.model_name == "text-embedding-embeddinggemma-300m"
    assert config.model_provider == "LMStudio"
    assert config.is_active is True

@pytest.mark.django_db
def test_get_embeddings_no_config():
    """Verify that _get_embeddings raises ValueError if no active config exists."""
    EmbeddingModelConfig.objects.all().delete()
    with pytest.raises(ValueError, match="No active EmbeddingModelConfig found."):
        _get_embeddings(["test"])
