import pytest
from tests.test_api import client
from kb.models import EmbeddingModelConfig
from unittest.mock import patch, MagicMock
import httpx

@pytest.mark.django_db
class TestEmbeddingStatus:
    def test_status_no_config(self):
        EmbeddingModelConfig.objects.all().delete()
        response = client.get("/embedding-configs/status/")
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert "No active embedding model configuration found" in data.get("message", "")

    @patch("httpx.get")
    def test_status_lmstudio_success(self, mock_get):
        EmbeddingModelConfig.objects.all().delete()
        EmbeddingModelConfig.objects.create(
            model_name="test-model",
            model_provider="LMStudio",
            is_active=True
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "test-model"}, {"id": "other-model"}]
        }
        mock_get.return_value = mock_response
        
        response = client.get("/embedding-configs/status/")
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True, f"Status check failed: {data.get('message')}"
        assert "loaded" in data["message"]
        assert data["provider"] == "LMStudio"
        assert data["model_name"] == "test-model"

    @patch("httpx.get")
    def test_status_lmstudio_not_loaded(self, mock_get):
        EmbeddingModelConfig.objects.all().delete()
        EmbeddingModelConfig.objects.create(
            model_name="test-model",
            model_provider="LMStudio",
            is_active=True
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "other-model"}]
        }
        mock_get.return_value = mock_response
        
        response = client.get("/embedding-configs/status/")
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert "not loaded" in data["message"]

    @patch("httpx.get")
    def test_status_lmstudio_server_down(self, mock_get):
        EmbeddingModelConfig.objects.all().delete()
        EmbeddingModelConfig.objects.create(
            model_name="test-model",
            model_provider="LMStudio",
            is_active=True
        )
        
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        
        response = client.get("/embedding-configs/status/")
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert "server not running" in data["message"]
