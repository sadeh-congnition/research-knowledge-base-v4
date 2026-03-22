import pytest
from django.db import IntegrityError
from model_bakery import baker

from kb.models import SearchConfig


def test_seeded_default_search_config_exists(db):
    config = SearchConfig.objects.get(name="semantic search")

    assert config.package_path == "kb.services.search_engines.semantic_search.search"


def test_search_config_name_uniqueness_is_enforced(db):
    baker.make(
        SearchConfig,
        name="duplicate",
        package_path="tests.search_engines.valid_engine",
    )

    with pytest.raises(IntegrityError):
        baker.make(
            SearchConfig,
            name="duplicate",
            package_path="tests.search_engines.explicit_engine",
        )
