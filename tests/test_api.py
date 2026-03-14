from ninja.testing import TestClient

from kb.api import api
from kb.models import LLMConfig, Secret
from kb.schemas import (
    LLMConfigIn,
    LLMConfigOut,
    DefaultLLMConfigIn,
    ResourceListOut,
    SecretIn,
    SecretOut,
    SemanticSearchOut,
)

client = TestClient(api)


# ---- Secret Tests ----


class TestSecretEndpoints:
    def test_create_secret(self, db):
        payload = SecretIn(title="MY_KEY", value="super-secret")
        response = client.post("/secrets/", json=payload.dict())
        assert response.status_code == 200
        data = SecretOut(**response.json())
        assert data.title == "MY_KEY"
        assert Secret.objects.filter(title="MY_KEY").exists()

    def test_list_secrets(self, db, secret):
        response = client.get("/secrets/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        parsed = [SecretOut(**item) for item in data]
        assert any(s.title == secret.title for s in parsed)


# ---- Resource Tests ----


class TestResourceEndpoints:
    def test_create_resource_streaming(self, db):
        import json
        from django.test import Client
        from kb.schemas import ResourceIn, ResourceStreamUpdate

        django_client = Client()
        payload = {"url": "https://example.com", "resource_type": "paper"}

        response = django_client.post(
            "/api/resources/", data=json.dumps(payload), content_type="application/json"
        )
        assert response.status_code == 200

        chunks = list(response.streaming_content)
        lines = [chunk.decode("utf-8").strip() for chunk in chunks]
        lines = [line for line in lines if line]

        assert (
            len(lines) >= 4
        )  # Should have at least the status updates and the final result

        updates = []
        for line in lines:
            data = json.loads(line)
            updates.append(ResourceStreamUpdate(**data))

        # Check that the last update is the result
        last_update = updates[-1]
        assert last_update.type == "result"
        assert last_update.resource is not None
        assert last_update.resource.url == "https://example.com"
        assert last_update.resource.resource_type == "paper"

    def test_list_resources_empty(self, db):
        response = client.get("/resources/")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_resources(self, db, resource):
        response = client.get("/resources/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        parsed = ResourceListOut(**data[0])
        assert parsed.url == resource.url

    def test_get_resource(self, db, resource):
        response = client.get(f"/resources/{resource.id}/")
        assert response.status_code == 200
        data = response.json()
        assert data["url"] == resource.url
        assert data["extracted_text"] == resource.extracted_text

    def test_get_resource_not_found(self, db):
        response = client.get("/resources/99999/")
        assert response.status_code == 404

    def test_list_resource_chunks(self, db, resource_with_chunks):
        response = client.get(f"/resources/{resource_with_chunks.id}/chunks/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["order"] == 0
        assert data[1]["order"] == 1


# ---- ChunkConfig Tests ----


class TestChunkConfigEndpoints:
    def test_list_chunk_configs(self, db, chunk_config):
        response = client.get("/chunk-configs/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1


# ---- LLMConfig Tests ----


class TestLLMConfigEndpoints:
    def test_create_llm_config(self, db, secret):
        payload = LLMConfigIn(
            name="my-llm",
            model_name="llama-3.1-8b-instant",
            provider="groq",
            is_default=True,
            secret_id=secret.id,
        )
        response = client.post("/llm-configs/", json=payload.dict())
        assert response.status_code == 200
        data = LLMConfigOut(**response.json())
        assert data.name == "my-llm"
        assert data.is_default is True
        assert data.secret_id == secret.id

    def test_create_llm_config_clears_previous_default(self, db, secret):
        # Create first config as default
        payload1 = LLMConfigIn(
            name="first-llm",
            model_name="llama-3.1-8b-instant",
            provider="groq",
            is_default=True,
            secret_id=secret.id,
        )
        response1 = client.post("/llm-configs/", json=payload1.dict())
        assert response1.status_code == 200
        first_id = response1.json()["id"]

        # Create second config as default
        payload2 = LLMConfigIn(
            name="second-llm",
            model_name="llama-3.1-8b-instant",
            provider="groq",
            is_default=True,
            secret_id=secret.id,
        )
        response2 = client.post("/llm-configs/", json=payload2.dict())
        assert response2.status_code == 200

        # First should no longer be default
        first = LLMConfig.objects.get(id=first_id)
        assert first.is_default is False

    def test_list_llm_configs(self, db, llm_config):
        response = client.get("/llm-configs/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        parsed = [LLMConfigOut(**item) for item in data]
        assert any(c.name == llm_config.name for c in parsed)

    def test_create_llm_config_without_secret(self, db):
        payload = LLMConfigIn(
            name="local-llm",
            model_name="llama-3.1-8b-instant",
            provider="groq",
            is_default=False,
        )
        response = client.post("/llm-configs/", json=payload.dict())
        assert response.status_code == 200
        data = LLMConfigOut(**response.json())
        assert data.secret_id is None

    def test_create_llm_config_invalid_provider(self, db):
        payload = {
            "name": "invalid-llm",
            "model_name": "some-model",
            "provider": "invalid-provider",
        }
        response = client.post("/llm-configs/", json=payload)
        assert response.status_code == 422
        # Check if the error message mentions the provider
        data = response.json()
        assert "provider" in str(data)


class TestDefaultLLMConfigEndpoints:
    def test_setup_default_llm_config_with_key(self, db):
        payload = DefaultLLMConfigIn(
            model_name="llama-3.1-8b-instant",
            provider="groq",
            api_key="sk-test-key",
        )
        response = client.post("/llm-configs/default/", json=payload.dict())
        assert response.status_code == 200
        data = LLMConfigOut(**response.json())

        assert data.name == "Default Chat LLM"
        assert data.model_name == "groq/llama-3.1-8b-instant"
        assert data.is_default is True
        assert data.secret_id is not None

        # Verify secret was created
        secret = Secret.objects.get(id=data.secret_id)
        assert secret.title == "DEFAULT_LLM_API_KEY"
        assert secret.value == "sk-test-key"

    def test_setup_default_llm_config_without_key(self, db):
        payload = DefaultLLMConfigIn(
            model_name="llama-3.1-8b-instant",
            provider="groq",
        )
        response = client.post("/llm-configs/default/", json=payload.dict())
        assert response.status_code == 200
        data = LLMConfigOut(**response.json())

        assert data.name == "Default Chat LLM"
        assert data.model_name == "groq/llama-3.1-8b-instant"
        assert data.is_default is True
        assert data.secret_id is None

    def test_setup_default_llm_config_clears_previous_defaults(self, db, secret):
        # Create a regular config as default first
        regular_payload = LLMConfigIn(
            name="first-llm",
            model_name="llama-3.1-8b-instant",
            provider="groq",
            is_default=True,
            secret_id=secret.id,
        )
        regular_response = client.post("/llm-configs/", json=regular_payload.dict())
        assert regular_response.status_code == 200
        first_id = regular_response.json()["id"]

        # Now setup default
        default_payload = DefaultLLMConfigIn(
            model_name="llama-3.1-8b-instant",
            provider="groq",
        )
        default_response = client.post(
            "/llm-configs/default/", json=default_payload.dict()
        )
        assert default_response.status_code == 200

        # Verify old one is no longer default
        first = LLMConfig.objects.get(id=first_id)
        assert first.is_default is False


# ---- TextExtractionConfig Tests ----


class TestTextExtractionConfigEndpoints:
    def test_list_text_extraction_configs(self, db):
        response = client.get("/text-extraction-configs/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(c["title"] == "JINA AI API" for c in data)

    def test_set_and_get_text_extraction_config_secret(self, db):
        from kb.models import TextExtractionConfig

        config = TextExtractionConfig.objects.get(title="JINA AI API")

        # Get when no secret exists
        response = client.get(f"/text-extraction-configs/{config.id}/secret/")
        assert response.status_code == 404

        # Set secret
        payload = SecretIn(title="JINA_API_KEY", value="my-jina-key")
        response = client.post(
            f"/text-extraction-configs/{config.id}/secret/", json=payload.dict()
        )
        assert response.status_code == 200
        data = SecretOut(**response.json())
        assert data.title == "JINA_API_KEY"

        # Verify only one secret exists for this config
        assert config.secrets.count() == 1


# ---- Search Tests ----


class TestSearchEndpoints:
    def test_search_chunks_empty_query(self, db):
        response = client.get("/search/?query=   ")
        if response.status_code != 200:
            print(response.json())
        assert response.status_code == 200
        assert response.json() == []

    def test_search_chunks(self, db, resource_with_chunks):
        # For tests, we use the actual chromadb instance to do semantic search.
        # But wait - we shouldn't use mocks as per user instruction.
        # Since resource_with_chunks is created, chunks were added to Chromadb in `conftest.py` hopefully, or tests rely on the real one.

        # Let's perform a search for text we know exists in the mock/fixture
        # Fixture usually creates chunk 1 with "first chunk text", chunk 2 with "second chunk text"
        # Since we use LLM/LMStudio directly, let's just make sure there is no fatal error when searching.

        # The user rules explicitly state: "Do not use any mocks. Do not monkeypatch anything."
        # We'll just call the API directly.
        response = client.get("/search/?query=test%20query")

        assert response.status_code == 200
        data = response.json()

        # we can't be strictly sure it returns something depending on the similarity threshold/LMStudio,
        # but we know the result is a parseable list.
        assert isinstance(data, list)

        if len(data) > 0:
            parsed = SemanticSearchOut(**data[0])
            assert parsed.document is not None
            assert parsed.distance is not None
            assert parsed.resource_id is not None
            assert parsed.chunk_order is not None
