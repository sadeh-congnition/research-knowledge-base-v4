import chromadb
import httpx
from django.conf import settings


def get_client() -> chromadb.ClientAPI:
    """Get a persistent ChromaDB client."""
    return chromadb.PersistentClient(path=str(settings.CHROMADB_DIR))


def get_collection(client: chromadb.ClientAPI | None = None) -> chromadb.Collection:
    """Get the resource chunks collection."""
    if client is None:
        client = get_client()
    return client.get_or_create_collection(
        name=settings.CHROMADB_COLLECTION_NAME,
    )


def _get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embeddings from LMStudio server.

    Args:
        texts: List of texts to embed.

    Returns:
        List of embedding vectors.
    """
    response = httpx.post(
        f"{settings.LMSTUDIO_BASE_URL}/v1/embeddings",
        json={
            "model": settings.LMSTUDIO_EMBEDDING_MODEL,
            "input": texts,
        },
        timeout=120.0,
    )
    response.raise_for_status()
    data = response.json()
    return [item["embedding"] for item in data["data"]]


def add_chunks(resource_id: int, chunks: list[str]) -> None:
    """Embed and store chunks in ChromaDB.

    Args:
        resource_id: ID of the resource the chunks belong to.
        chunks: List of chunk text strings.
    """
    if not chunks:
        return

    collection = get_collection()
    embeddings = _get_embeddings(chunks)

    ids = [f"resource_{resource_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {"resource_id": resource_id, "chunk_order": i} for i in range(len(chunks))
    ]

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )


def remove_chunks(resource_id: int) -> None:
    """Remove all chunks for a resource from ChromaDB.

    Args:
        resource_id: ID of the resource to remove chunks for.
    """
    collection = get_collection()
    # Get all doc IDs for this resource
    results = collection.get(
        where={"resource_id": resource_id},
    )
    if results["ids"]:
        collection.delete(ids=results["ids"])


def search(query: str, n_results: int = 5) -> list[dict]:
    """Search for similar chunks in ChromaDB.

    Args:
        query: Query text to search for.
        n_results: Number of results to return.

    Returns:
        List of dicts with 'document', 'metadata', 'distance' keys.
    """
    collection = get_collection()
    embeddings = _get_embeddings([query])

    results = collection.query(
        query_embeddings=embeddings,
        n_results=n_results,
    )

    search_results: list[dict] = []
    if results["documents"] and results["metadatas"] and results["distances"]:
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            search_results.append(
                {
                    "document": doc,
                    "metadata": meta,
                    "distance": dist,
                }
            )

    return search_results
