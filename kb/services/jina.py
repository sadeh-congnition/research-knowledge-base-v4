import httpx


def extract_text(url: str, api_key: str) -> str:
    """Extract text from a URL using Jina AI Reader API.

    Args:
        url: The URL to extract text from.
        api_key: Jina AI API key for authentication.

    Returns:
        Extracted text content as markdown string.
    """
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/plain",
    }

    response = httpx.get(jina_url, headers=headers, timeout=60.0)
    response.raise_for_status()
    return response.text
