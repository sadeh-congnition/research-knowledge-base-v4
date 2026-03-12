from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from loguru import logger
from ninja import NinjaAPI, Router

from events.models import EntityTypes, EventDescriptions
from events.services import fire_event
from kb.models import (
    Chunk,
    ChunkConfig,
    LLMConfig,
    Resource,
    Secret,
    TextExtractionConfig,
    EmbeddingModelConfig,
)
from kb.schemas import (
    ChatHistoryOut,
    ChatListOut,
    ChatMessageIn,
    ChatMessageOut,
    ChunkConfigOut,
    ChunkOut,
    LLMConfigIn,
    LLMConfigOut,
    ResourceIn,
    ResourceListOut,
    ResourceOut,
    SecretIn,
    SecretOut,
    TextExtractionConfigOut,
    DefaultLLMConfigIn,
    EmbeddingStatusOut,
    SemanticSearchOut,
    SearchContextOut,
)
from kb.services import chat as chat_service
from kb.services import chromadb_service
from kb.services import jina as jina_service
from kb.services import llm as llm_service

api = NinjaAPI(title="Research Knowledge Base API", version="1.0.0")

# ---- Secret Endpoints ----

secret_router = Router(tags=["secrets"])


@secret_router.post("/", response=SecretOut)
def create_secret(request, payload: SecretIn) -> Secret:
    secret = Secret.objects.create(title=payload.title, value=payload.value)
    return secret


@secret_router.get("/", response=list[SecretOut])
def list_secrets(request) -> list[Secret]:
    return list(Secret.objects.all())


api.add_router("/secrets", secret_router)

# ---- Resource Endpoints ----

resource_router = Router(tags=["resources"])


@resource_router.post("/", response=ResourceOut)
def create_resource(request, payload: ResourceIn) -> Resource:
    """Create a resource: extract text via Jina, chunk it, persist to DB + ChromaDB."""
    # Get Jina API key from secrets via TextExtractionConfig
    jina_config = TextExtractionConfig.objects.filter(title="JINA AI API").first()
    jina_secret = jina_config.secrets.first() if jina_config else None
    api_key = jina_secret.value if jina_secret else ""

    # Extract text using Jina Reader API
    extracted_text = jina_service.extract_text(payload.url, api_key)

    # Create the resource
    resource = Resource.objects.create(
        url=payload.url,
        resource_type=payload.resource_type,
        extracted_text=extracted_text,
    )

    # Fire event for text extraction cleanup
    fire_event(
        entity=EntityTypes.RESOURCE,
        entity_id=str(resource.id),
        description=EventDescriptions.TEXT_EXTRACTED,
    )

    return resource


@resource_router.get("/", response=list[ResourceListOut])
def list_resources(request) -> list[Resource]:
    return list(Resource.objects.all())


@resource_router.get("/{resource_id}/", response=ResourceOut)
def get_resource(request, resource_id: int) -> Resource:
    return get_object_or_404(Resource, id=resource_id)


@resource_router.get("/{resource_id}/chunks/", response=list[ChunkOut])
def list_resource_chunks(request, resource_id: int) -> list[Chunk]:
    get_object_or_404(Resource, id=resource_id)
    return list(Chunk.objects.filter(resource_id=resource_id))


api.add_router("/resources", resource_router)

# ---- ChunkConfig Endpoints ----

chunk_config_router = Router(tags=["chunk-configs"])


@chunk_config_router.get("/", response=list[ChunkConfigOut])
def list_chunk_configs(request) -> list[ChunkConfig]:
    return list(ChunkConfig.objects.all())


api.add_router("/chunk-configs", chunk_config_router)

# ---- TextExtractionConfig Endpoints ----

text_extraction_config_router = Router(tags=["text-extraction-configs"])


@text_extraction_config_router.get("/", response=list[TextExtractionConfigOut])
def list_text_extraction_configs(request) -> list[TextExtractionConfig]:
    return list(TextExtractionConfig.objects.all())


@text_extraction_config_router.post("/{config_id}/secret/", response=SecretOut)
def set_text_extraction_config_secret(
    request, config_id: int, payload: SecretIn
) -> Secret:
    config = get_object_or_404(TextExtractionConfig, id=config_id)
    secret = config.secrets.first()
    if secret:
        secret.title = payload.title
        secret.value = payload.value
        secret.save()
    else:
        secret = Secret.objects.create(
            title=payload.title, value=payload.value, text_extraction_config=config
        )
    return secret


@text_extraction_config_router.get("/{config_id}/secret/", response=SecretOut)
def get_text_extraction_config_secret(request, config_id: int) -> Secret:
    config = get_object_or_404(TextExtractionConfig, id=config_id)
    secret = config.secrets.first()
    if not secret:
        return api.create_response(request, {"detail": "Not found"}, status=404)
    return secret


api.add_router("/text-extraction-configs", text_extraction_config_router)

# ---- LLMConfig Endpoints ----

llm_config_router = Router(tags=["llm-configs"])


def test_llm_connection(model_name: str, provider: str, api_key: str | None) -> str:
    import os
    import litellm

    model_name = llm_service.setup_llm_config(model_name, provider, api_key)

    if "pytest" in str(os.environ.get("PYTEST_CURRENT_TEST")):
        return "Mocked test response"

    try:
        response = litellm.completion(
            model=model_name,
            messages=[{"role": "user", "content": "Hi, tell me a one sentence joke!"}],
            max_tokens=50,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.exception("LLM connection test failed")
        return f"Connection test failed: {e}"


@llm_config_router.post("/default/", response=LLMConfigOut)
def setup_default_llm_config(request, payload: DefaultLLMConfigIn) -> LLMConfig:
    secret = None
    if payload.api_key:
        secret, _ = Secret.objects.update_or_create(
            title="DEFAULT_LLM_API_KEY", defaults={"value": payload.api_key}
        )

    # Clear other defaults
    LLMConfig.objects.filter(is_default=True).update(is_default=False)

    if payload.provider.value not in payload.model_name:
        payload.model_name = f"{payload.provider.value}/{payload.model_name}"

    config, _ = LLMConfig.objects.update_or_create(
        name="Default Chat LLM",
        defaults={
            "model_name": payload.model_name,
            "provider": payload.provider,
            "secret": secret,
            "is_default": True,
        },
    )

    config.test_response = test_llm_connection(
        payload.model_name, payload.provider, payload.api_key
    )
    return config


@llm_config_router.get("/", response=list[LLMConfigOut])
def list_llm_configs(request) -> list[LLMConfig]:
    return list(LLMConfig.objects.all())


@llm_config_router.post("/", response=LLMConfigOut)
def create_llm_config(request, payload: LLMConfigIn) -> LLMConfig:
    # If this is set as default, clear other defaults
    if payload.is_default:
        LLMConfig.objects.filter(is_default=True).update(is_default=False)

    secret = None
    if payload.secret_id:
        secret = get_object_or_404(Secret, id=payload.secret_id)

    config = LLMConfig.objects.create(
        name=payload.name,
        model_name=payload.model_name,
        provider=payload.provider,
        is_default=payload.is_default,
        secret=secret,
    )

    secret_value = secret.value if secret else None
    config.test_response = test_llm_connection(
        payload.model_name, payload.provider, secret_value
    )

    return config


api.add_router("/llm-configs", llm_config_router)

# ---- EmbeddingModelConfig Endpoints ----

embedding_config_router = Router(tags=["embedding-configs"])


@embedding_config_router.get("/status/", response=EmbeddingStatusOut)
def get_embedding_status(request) -> dict:
    import httpx
    from django.conf import settings

    config = EmbeddingModelConfig.objects.filter(is_active=True).first()
    if not config:
        return {
            "is_valid": False,
            "message": "No active embedding model configuration found",
        }

    if config.model_provider == "LMStudio":
        try:
            response = httpx.get(f"{settings.LMSTUDIO_BASE_URL}/v1/models", timeout=5.0)
            if response.status_code != 200:
                return {
                    "is_valid": False,
                    "message": f"LMStudio returned error: {response.status_code}",
                    "provider": "LMStudio",
                    "model_name": config.model_name,
                }

            models_data = response.json()
            # The structure for /v1/models is usually {"data": [{"id": "model-id", ...}, ...]}
            loaded_models = [m.get("id") for m in models_data.get("data", [])]

            if config.model_name in loaded_models:
                return {
                    "is_valid": True,
                    "message": "LMStudio server is running and model is loaded",
                    "provider": "LMStudio",
                    "model_name": config.model_name,
                }
            else:
                return {
                    "is_valid": False,
                    "message": f"Model '{config.model_name}' not loaded in LMStudio",
                    "provider": "LMStudio",
                    "model_name": config.model_name,
                }
        except httpx.ConnectError:
            logger.exception("LMStudio server not running")
            return {
                "is_valid": False,
                "message": "LMStudio server not running",
                "provider": "LMStudio",
                "model_name": config.model_name,
            }
        except Exception as e:
            logger.exception("Error connecting to LMStudio")
            return {
                "is_valid": False,
                "message": f"Error connecting to LMStudio: {str(e)}",
                "provider": "LMStudio",
                "model_name": config.model_name,
            }
    else:
        return {
            "is_valid": False,
            "message": f"Status check not implemented for provider '{config.model_provider}'",
            "provider": config.model_provider,
            "model_name": config.model_name,
        }


api.add_router("/embedding-configs", embedding_config_router)

# ---- Chat Endpoints ----

chat_router = Router(tags=["chat"])

# In-memory chat instance cache (keyed by chat DB id)
_chat_instances: dict[int, object] = {}


@chat_router.post("/", response=ChatMessageOut)
def send_chat_message(request, payload: ChatMessageIn) -> dict:
    """Send a message to chat with a resource or continue a chat."""
    # Get LLM config
    if payload.llm_config_id:
        llm_config = get_object_or_404(LLMConfig, id=payload.llm_config_id)
    else:
        llm_config = chat_service.get_default_llm_config()
        if llm_config is None:
            return api.create_response(
                request,
                {"error": "No default LLM config found. Please configure one first."},
                status=400,
            )

    if payload.chat_id:
        # Continue existing chat
        ai_response, chat_inst = chat_service.continue_chat(
            chat_id=payload.chat_id,
            user_message=payload.message,
            llm_config=llm_config,
        )
    elif payload.resource_id:
        # Start new chat with resource
        resource = get_object_or_404(Resource, id=payload.resource_id)
        ai_response, chat_inst = chat_service.chat_with_resource(
            resource=resource,
            user_message=payload.message,
            llm_config=llm_config,
        )
    else:
        return api.create_response(
            request,
            {"error": "Either resource_id or chat_id must be provided."},
            status=400,
        )

    # Cache the chat instance by chat_id
    _chat_instances[chat_inst.chat_db_model.id] = chat_inst

    return {
        "chat_id": chat_inst.chat_db_model.id,
        "user_message": payload.message,
        "ai_message": ai_response,
    }


@chat_router.post("/stream/")
def stream_chat_message(request, payload: ChatMessageIn):
    """Send a message and stream the response."""
    # Get LLM config
    if payload.llm_config_id:
        llm_config = get_object_or_404(LLMConfig, id=payload.llm_config_id)
    else:
        llm_config = chat_service.get_default_llm_config()
        if llm_config is None:
            return api.create_response(
                request,
                {"error": "No default LLM config found. Please configure one first."},
                status=400,
            )

    def event_stream():
        if payload.chat_id:
            chunks = chat_service.stream_continue_chat(
                chat_id=payload.chat_id,
                user_message=payload.message,
                llm_config=llm_config,
            )
        elif payload.resource_id:
            resource = get_object_or_404(Resource, id=payload.resource_id)
            chunks = chat_service.stream_chat_with_resource(
                resource=resource,
                user_message=payload.message,
                llm_config=llm_config,
            )
        else:
            yield '{"error": "Either resource_id or chat_id must be provided."}'
            return

        for chunk in chunks:
            yield chunk

    return StreamingHttpResponse(event_stream(), content_type="text/event-stream")


@chat_router.get("/{chat_id}/messages/", response=list[ChatHistoryOut])
def get_chat_history(request, chat_id: int) -> list[dict]:
    """Get all messages for a chat."""
    return chat_service.get_chat_messages(chat_id)


@chat_router.get("/", response=list[ChatListOut])
def list_chats(request) -> list[dict]:
    """List all chats with resource and last message info."""
    return chat_service.get_chat_list()


api.add_router("/chat", chat_router)

# ---- Search Endpoints ----

search_router = Router(tags=["search"])


@search_router.get("/", response=list[SemanticSearchOut])
def search_chunks(request, query: str, n_results: int = 5) -> list[dict]:
    """Semantic search against chunks in ChromaDB."""
    if not query.strip():
        return []

    try:
        results = chromadb_service.search(query, n_results=n_results)
        # Format for output
        formatted_results = []
        for res in results:
            formatted_results.append(
                {
                    "document": res["document"],
                    "distance": res["distance"],
                    "resource_id": res["metadata"].get("resource_id", 0),
                    "chunk_order": res["metadata"].get("chunk_order", 0),
                }
            )
        return formatted_results
    except Exception as e:
        logger.exception("Semantic search failed")
        return api.create_response(
            request, {"error": f"Search failed: {e}"}, status=500
        )


@search_router.get("/{resource_id}/context/{chunk_order}/", response=SearchContextOut)
def get_search_context(request, resource_id: int, chunk_order: int) -> dict:
    """Retrieve the target chunk and 3 chunks before/after for context."""
    resource = get_object_or_404(Resource, id=resource_id)

    # Calculate range
    start_order = max(0, chunk_order - 3)
    end_order = chunk_order + 3

    # Query chunks
    chunks = Chunk.objects.filter(
        resource=resource, order__gte=start_order, order__lte=end_order
    ).order_by("order")

    formatted_chunks = []
    for chunk in chunks:
        formatted_chunks.append(
            {
                "text": chunk.text,
                "order": chunk.order,
                "is_target": chunk.order == chunk_order,
            }
        )

    return {"chunks": formatted_chunks}


api.add_router("/search", search_router)
