from django.shortcuts import get_object_or_404
from ninja import NinjaAPI, Router

from kb.models import Chunk, ChunkConfig, LLMConfig, Resource, Secret
from kb.schemas import (
    ChatHistoryOut,
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
    DefaultLLMConfigIn,
)
from kb.services import chat as chat_service
from kb.services import chromadb_service
from kb.services import chunking as chunking_service
from kb.services import jina as jina_service

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
    # Get Jina API key from secrets
    jina_secret = Secret.objects.filter(title="JINA_API_KEY").first()
    api_key = jina_secret.value if jina_secret else ""

    # Extract text using Jina Reader API
    extracted_text = jina_service.extract_text(payload.url, api_key)

    # Create the resource
    resource = Resource.objects.create(
        url=payload.url,
        resource_type=payload.resource_type,
        extracted_text=extracted_text,
    )

    # Get default chunk config
    chunk_config = ChunkConfig.objects.first()
    if chunk_config:
        # Chunk the extracted text
        chunk_texts = chunking_service.chunk_text(
            extracted_text, chunk_config.details
        )

        # Save chunks to DB
        chunks_to_create = [
            Chunk(
                text=text,
                order=i,
                resource=resource,
                chunk_config=chunk_config,
            )
            for i, text in enumerate(chunk_texts)
        ]
        Chunk.objects.bulk_create(chunks_to_create)

        # Embed and persist to ChromaDB
        chromadb_service.add_chunks(resource.id, chunk_texts)

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

# ---- LLMConfig Endpoints ----

llm_config_router = Router(tags=["llm-configs"])


@llm_config_router.post("/default/", response=LLMConfigOut)
def setup_default_llm_config(request, payload: DefaultLLMConfigIn) -> LLMConfig:
    secret = None
    if payload.api_key:
        secret, _ = Secret.objects.update_or_create(
            title="DEFAULT_LLM_API_KEY", defaults={"value": payload.api_key}
        )

    # Clear other defaults
    LLMConfig.objects.filter(is_default=True).update(is_default=False)

    config, _ = LLMConfig.objects.update_or_create(
        name="Default Chat LLM",
        defaults={
            "model_name": payload.model_name,
            "secret": secret,
            "is_default": True,
        },
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
        is_default=payload.is_default,
        secret=secret,
    )
    return config


api.add_router("/llm-configs", llm_config_router)

# ---- Chat Endpoints ----

chat_router = Router(tags=["chat"])

# In-memory chat instance cache (keyed by chat DB id)
_chat_instances: dict[int, object] = {}


@chat_router.post("/", response=ChatMessageOut)
def send_chat_message(request, payload: ChatMessageIn) -> dict:
    """Send a message to chat with a resource."""
    resource = get_object_or_404(Resource, id=payload.resource_id)

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

    # Get or create chat instance
    chat_instance = _chat_instances.get(payload.resource_id)

    ai_response, chat_inst = chat_service.chat_with_resource(
        resource=resource,
        user_message=payload.message,
        llm_config=llm_config,
        chat_instance=chat_instance,
    )

    # Cache the chat instance
    _chat_instances[payload.resource_id] = chat_inst

    return {
        "chat_id": chat_inst.chat_db_model.id,
        "user_message": payload.message,
        "ai_message": ai_response,
    }


@chat_router.get("/{chat_id}/messages/", response=list[ChatHistoryOut])
def get_chat_history(request, chat_id: int) -> list[dict]:
    """Get all messages for a chat."""
    return chat_service.get_chat_messages(chat_id)


api.add_router("/chat", chat_router)
