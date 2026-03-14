import pytest
import os
from unittest.mock import patch, MagicMock
from kb.api import test_llm_connection as call_test_connection
from kb.services.llm import LLMProvider


class TestLLMConnection:
    @patch("kb.api.requests.post")
    @patch("kb.api.llm_service.setup_llm_config")
    def test_lmstudio_connection_success(self, mock_setup, mock_post):
        """Test successful LM Studio connection with direct requests."""
        # Setup mocks
        mock_setup.return_value = "test-model"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": [{"type": "message", "content": "Test joke response"}],
            "response_id": "test-res-id",
        }
        mock_post.return_value = mock_response

        # Test the function with mock bypass
        with patch.dict(os.environ, {"BYPASS_PYTEST_MOCK": "1"}):
            result = call_test_connection(
                "test-model", LLMProvider.LMSTUDIO, "test-key"
            )

        # Verify requests.post was called
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["model"] == "test-model"
        assert kwargs["json"]["stream"] is False

        assert result == "Test joke response"

    @patch("kb.api.requests.post")
    @patch("kb.api.llm_service.setup_llm_config")
    def test_lmstudio_connection_failure(self, mock_setup, mock_post):
        """Test LM Studio connection failure handling with direct requests."""
        # Setup mocks
        mock_setup.return_value = "test-model"

        mock_post.side_effect = Exception("Connection failed")

        # Test the function with mock bypass
        with patch.dict(os.environ, {"BYPASS_PYTEST_MOCK": "1"}):
            result = call_test_connection(
                "test-model", LLMProvider.LMSTUDIO, "test-key"
            )

        assert "Connection test failed: Connection failed" == result

    def test_lmstudio_connection_mocked_in_test(self):
        """Test that mocked response is returned during pytest."""
        # Set the pytest environment variable to trigger mock response
        original_env = os.environ.get("PYTEST_CURRENT_TEST", "")
        try:
            os.environ["PYTEST_CURRENT_TEST"] = "test_some.py::test_function"
            result = call_test_connection(
                "test-model", LLMProvider.LMSTUDIO, "test-key"
            )
            assert result == "Mocked test response"
        finally:
            if original_env:
                os.environ["PYTEST_CURRENT_TEST"] = original_env
            else:
                os.environ.pop("PYTEST_CURRENT_TEST", None)
