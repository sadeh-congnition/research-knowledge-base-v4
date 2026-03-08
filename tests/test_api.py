import pytest
from ninja.testing import TestClient

from kb.api import api
from kb.models import ChunkConfig, LLMConfig, Resource, Secret
from kb.schemas import (
    LLMConfigIn,
    LLMConfigOut,
    DefaultLLMConfigIn,
    ResourceListOut,
    SecretIn,
    SecretOut,
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
            model_name="ollama_chat/qwen3:4b",
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
            model_name="model-a",
            is_default=True,
            secret_id=secret.id,
        )
        response1 = client.post("/llm-configs/", json=payload1.dict())
        assert response1.status_code == 200
        first_id = response1.json()["id"]

        # Create second config as default
        payload2 = LLMConfigIn(
            name="second-llm",
            model_name="model-b",
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
            model_name="ollama_chat/qwen3:4b",
            is_default=False,
        )
        response = client.post("/llm-configs/", json=payload.dict())
        assert response.status_code == 200
        data = LLMConfigOut(**response.json())
        assert data.secret_id is None


class TestDefaultLLMConfigEndpoints:
    def test_setup_default_llm_config_with_key(self, db):
        payload = DefaultLLMConfigIn(
            model_name="openai/gpt-4o",
            api_key="sk-test-key",
        )
        response = client.post("/llm-configs/default/", json=payload.dict())
        assert response.status_code == 200
        data = LLMConfigOut(**response.json())
        
        assert data.name == "Default Chat LLM"
        assert data.model_name == "openai/gpt-4o"
        assert data.is_default is True
        assert data.secret_id is not None
        
        # Verify secret was created
        secret = Secret.objects.get(id=data.secret_id)
        assert secret.title == "DEFAULT_LLM_API_KEY"
        assert secret.value == "sk-test-key"

    def test_setup_default_llm_config_without_key(self, db):
        payload = DefaultLLMConfigIn(
            model_name="ollama_chat/qwen3:4b",
        )
        response = client.post("/llm-configs/default/", json=payload.dict())
        assert response.status_code == 200
        data = LLMConfigOut(**response.json())
        
        assert data.name == "Default Chat LLM"
        assert data.model_name == "ollama_chat/qwen3:4b"
        assert data.is_default is True
        assert data.secret_id is None

    def test_setup_default_llm_config_clears_previous_defaults(self, db, secret):
        # Create a regular config as default first
        regular_payload = LLMConfigIn(
            name="first-llm",
            model_name="model-a",
            is_default=True,
            secret_id=secret.id,
        )
        regular_response = client.post("/llm-configs/", json=regular_payload.dict())
        assert regular_response.status_code == 200
        first_id = regular_response.json()["id"]

        # Now setup default
        default_payload = DefaultLLMConfigIn(
            model_name="new-model",
        )
        default_response = client.post("/llm-configs/default/", json=default_payload.dict())
        assert default_response.status_code == 200

        # Verify old one is no longer default
        first = LLMConfig.objects.get(id=first_id)
        assert first.is_default is False
