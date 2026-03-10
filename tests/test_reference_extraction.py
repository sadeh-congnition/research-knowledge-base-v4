import pytest
from ninja.testing import TestClient
from kb.api import api
from kb.models import Resource, Reference
from events.models import Event, EntityTypes, EventDescriptions
from events.consumers import consume_extract_references
from kb.schemas import ResourceOut

client = TestClient(api)

@pytest.mark.django_db
class TestReferenceExtraction:
    def test_consume_extract_references(self, resource, llm_config):
        # Create an event for the resource
        event = Event.objects.create(
            entity=EntityTypes.RESOURCE,
            entity_id=str(resource.id),
            description=EventDescriptions.CLEAN_UP_FINISHED
        )
        
        # Run the consumer
        count = consume_extract_references()
        
        # Check that one event was processed
        assert count == 1
        
        # Check that a Reference object was created
        assert Reference.objects.filter(resource=resource).exists()
        ref = Reference.objects.get(resource=resource)
        # The mock response in consumers.py is f"MOCKED REFERENCE: {resource.extracted_text[:20]}"
        assert ref.description == f"MOCKED REFERENCE: {resource.extracted_text[:20]}"

    def test_api_returns_references(self, resource, llm_config):
        # Create a reference manually
        Reference.objects.create(resource=resource, description="Test Reference Description")
        
        response = client.get(f"/resources/{resource.id}/")
        assert response.status_code == 200
        data = response.json()
        
        # Verify references are in the response
        assert "references" in data
        assert len(data["references"]) == 1
        assert data["references"][0]["description"] == "Test Reference Description"
        
        # Parse with schema to ensure it's valid
        parsed = ResourceOut(**data)
        assert len(parsed.references) == 1
        assert parsed.references[0].description == "Test Reference Description"
