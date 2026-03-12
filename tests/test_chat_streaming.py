import pytest
from django.test import Client
from model_bakery import baker
from kb.models import Resource, LLMConfig
import json


@pytest.mark.django_db
def test_stream_chat_message():
    client = Client()

    # Create resource and LLM config
    resource = baker.make(
        Resource, url="http://example.com", extracted_text="test content"
    )
    llm_config = baker.make(
        LLMConfig, model_name="llama-3.1-8b-instant", provider="groq", is_default=True
    )

    payload = {"resource_id": resource.id, "message": "hello"}

    # Send streaming request
    # Note: django.test.Client.post with StreamingHttpResponse returns a response where you can iterate over content
    response = client.post(
        "/api/chat/stream/", data=json.dumps(payload), content_type="application/json"
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"

    # Collect chunks
    chunks = list(response.streaming_content)
    assert len(chunks) > 0

    # First chunk should be chat_id
    first_chunk = chunks[0].decode()
    assert first_chunk.startswith("__CHAT_ID__:")

    # Other chunks should be text (depending on mock)
    # Since we are not mocking in tests according to rules, it will try to call LiteLLM.
    # But wait, RULE[endpoint-tests.md] says: Do not use any mocks.
    # However, TEST-TOOLS.md says they use groq llama-3.1-8b-instant for testing if LLM is involved.
    # But for a basic functional test, if I can't mock, I might hit real API.
    # Let's see if there's any existing tests for chat to see how they handle it.
