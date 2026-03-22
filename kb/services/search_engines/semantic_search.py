from kb.services import chromadb_service


def search(query: str, n_results: int) -> list[dict]:
    results = chromadb_service.search(query, n_results=n_results)
    return [
        {
            "document": result["document"],
            "distance": result["distance"],
            "resource_id": result["metadata"].get("resource_id", 0),
            "chunk_order": result["metadata"].get("chunk_order", 0),
        }
        for result in results
    ]
