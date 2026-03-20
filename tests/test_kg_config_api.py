import pytest
from tests.test_api import client
from kb.models import KnowledgeGraphConfig


@pytest.mark.django_db
class TestKnowledgeGraphConfigAPI:
    def test_list_empty(self):
        response = client.get("/kg-configs/")
        assert response.status_code == 200
        assert response.json() == []

    def test_create(self):
        payload = {
            "name": "Test KG",
            "package_name": "custom.pkg",
            "update_trigger": "always",
            "is_active": True,
        }
        response = client.post("/kg-configs/", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test KG"
        assert data["package_name"] == "custom.pkg"

        # Verify in DB
        assert KnowledgeGraphConfig.objects.count() == 1
        config = KnowledgeGraphConfig.objects.first()
        assert config.name == "Test KG"

    def test_list_with_data(self):
        KnowledgeGraphConfig.objects.create(name="KG 1")
        KnowledgeGraphConfig.objects.create(name="KG 2")

        response = client.get("/kg-configs/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [d["name"] for d in data]
        assert "KG 1" in names
        assert "KG 2" in names

    def test_update(self):
        config = KnowledgeGraphConfig.objects.create(
            name="Old Name", package_name="old.pkg"
        )

        payload = {
            "name": "New Name",
            "package_name": "new.pkg",
            "update_trigger": "llm_intent",
            "is_active": True,
        }
        response = client.put(f"/kg-configs/{config.id}/", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"

        config.refresh_from_db()
        assert config.name == "New Name"
        assert config.package_name == "new.pkg"

    def test_delete(self):
        config = KnowledgeGraphConfig.objects.create(name="Delete Me")
        assert KnowledgeGraphConfig.objects.count() == 1

        response = client.delete(f"/kg-configs/{config.id}/")
        assert response.status_code == 200
        assert KnowledgeGraphConfig.objects.count() == 0
