from unittest.mock import patch

from model_bakery import baker
from ninja.testing import TestClient

from kb.api import api
from kb.models import LLMConfig, SearchConfig, Secret
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
    def test_list_search_configs_includes_seeded_semantic_search(self, db):
        response = client.get("/search-configs/")

        assert response.status_code == 200
        data = response.json()
        assert any(
            config["name"] == "semantic search"
            and config["package_path"]
            == "kb.services.search_engines.semantic_search.search"
            for config in data
        )

    def test_create_search_config_valid_package_path(self, db):
        response = client.post(
            "/search-configs/",
            json={
                "name": "valid engine",
                "package_path": "tests.search_engines.valid_engine",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "valid engine"
        assert data["package_path"] == "tests.search_engines.valid_engine"

    def test_create_search_config_invalid_package_path_returns_400(self, db):
        response = client.post(
            "/search-configs/",
            json={
                "name": "invalid engine",
                "package_path": "tests.search_engines.invalid_engine",
            },
        )

        assert response.status_code == 400
        assert "Invalid package_path" in response.json()["error"]

    def test_search_chunks_empty_query(self, db):
        response = client.get("/search/?query=   ")
        if response.status_code != 200:
            print(response.json())
        assert response.status_code == 200
        assert response.json() == []

    def test_search_without_search_config_id_uses_semantic_search(self, db):
        with patch("kb.api.load_search_engine") as mock_load_search_engine:
            mock_load_search_engine.return_value = lambda query, n_results: [
                {
                    "document": f"default:{query}:{n_results}",
                    "distance": 0.123,
                    "resource_id": 1,
                    "chunk_order": 2,
                }
            ]
            response = client.get("/search/?query=test%20query&n_results=7")

        assert response.status_code == 200
        assert response.json() == [
            {
                "document": "default:test query:7",
                "distance": 0.123,
                "resource_id": 1,
                "chunk_order": 2,
            }
        ]
        mock_load_search_engine.assert_called_once_with(
            "kb.services.search_engines.semantic_search.search"
        )

    def test_search_with_explicit_search_config_routes_through_selected_engine(
        self, db
    ):
        config = baker.make(
            SearchConfig,
            name="explicit engine",
            package_path="tests.search_engines.explicit_engine",
        )

        response = client.get(
            f"/search/?query=routed&n_results=3&search_config_id={config.id}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data == [
            {
                "document": "explicit:routed:3",
                "distance": 0.456,
                "resource_id": 22,
                "chunk_order": 3,
            }
        ]
        parsed = SemanticSearchOut(**data[0])
        assert parsed.document == "explicit:routed:3"
