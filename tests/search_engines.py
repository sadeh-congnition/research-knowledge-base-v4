def valid_engine(query: str, n_results: int) -> list[dict]:
    return [
        {
            "document": f"{query}:{n_results}",
            "distance": 0.123,
            "resource_id": 11,
            "chunk_order": 7,
        }
    ]


def explicit_engine(query: str, n_results: int) -> list[dict]:
    return [
        {
            "document": f"explicit:{query}:{n_results}",
            "distance": 0.456,
            "resource_id": 22,
            "chunk_order": 3,
        }
    ]


def invalid_engine(query: str) -> list[dict]:
    return []
