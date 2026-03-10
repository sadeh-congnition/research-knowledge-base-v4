import pytest
from django.test import Client
from model_bakery import baker
from kb.models import Resource, Chunk, ChunkConfig

@pytest.mark.django_db
def test_get_search_context():
    client = Client()
    
    # Setup
    resource = baker.make(Resource)
    chunk_config = baker.make(ChunkConfig)
    
    # Create 10 chunks
    chunks = []
    for i in range(10):
        chunks.append(
            baker.make(Chunk, resource=resource, order=i, text=f"Chunk {i}", chunk_config=chunk_config)
        )
    
    # Test middle chunk context
    target_order = 5
    response = client.get(f"/api/search/{resource.id}/context/{target_order}/")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should have 7 chunks (5-3, 5-2, 5-1, 5, 5+1, 5+2, 5+3)
    assert len(data["chunks"]) == 7
    orders = [c["order"] for c in data["chunks"]]
    assert orders == [2, 3, 4, 5, 6, 7, 8]
    
    # Check target highlight
    target_chunk = next(c for c in data["chunks"] if c["order"] == target_order)
    assert target_chunk["is_target"] is True
    
    # Test boundary condition: start
    target_order = 1
    response = client.get(f"/api/search/{resource.id}/context/{target_order}/")
    assert response.status_code == 200
    data = response.json()
    # Should have chunks 0, 1, 2, 3, 4
    orders = [c["order"] for c in data["chunks"]]
    assert 0 in orders
    assert 4 in orders
    assert -1 not in orders
    
    # Test boundary condition: end
    target_order = 8
    response = client.get(f"/api/search/{resource.id}/context/{target_order}/")
    assert response.status_code == 200
    data = response.json()
    # Should have chunks 5, 6, 7, 8, 9
    orders = [c["order"] for c in data["chunks"]]
    assert 5 in orders
    assert 9 in orders
    assert 10 not in orders
