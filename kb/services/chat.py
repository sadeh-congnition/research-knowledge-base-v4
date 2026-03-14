from typing import Iterable
from django.contrib.auth import get_user_model

from django_llm_chat.chat import Chat
from django_llm_chat.models import Message, Chat as ChatModel

from kb.models import LLMConfig, Resource, ResourceChat
from kb.services import llm as llm_service

User = get_user_model()


def _get_or_create_chat_user() -> "User":
    """Get or create the default chat user for the app."""
    user, _ = User.objects.get_or_create(
        username="rkb-user",
        defaults={"password": "unused"},
    )
    return user


def get_default_llm_config() -> LLMConfig | None:
    """Get the default LLM config, or None if not configured."""
    return LLMConfig.objects.filter(is_default=True).first()


def chat_with_resource(
    resource: Resource,
    user_message: str,
    llm_config: LLMConfig,
    chat_instance: Chat | None = None,
) -> tuple[str, Chat]:
    """Send a message to chat with a resource's content.

    Args:
        resource: The resource to chat about.
        user_message: The user's message.
        llm_config: LLM configuration to use.
        chat_instance: Existing chat instance, or None to create new one.

    Returns:
        Tuple of (AI response text, Chat instance).
    """
    user = _get_or_create_chat_user()

    if chat_instance is None:
        chat_instance = Chat.create()
        # Set system message with resource context
        system_prompt = (
            f"You are a research assistant. The user is discussing a "
            f"{resource.get_resource_type_display()} from: {resource.url}\n\n"
            f"Here is the extracted content of the resource:\n\n"
            f"{resource.extracted_text}\n\n"
            f"Answer the user's questions based on this content. "
            f"Be precise and cite relevant parts of the text when applicable."
        )
        chat_instance.create_system_message(system_prompt, user)

        # Link Chat with Resource
        ResourceChat.objects.create(
            resource=resource,
            chat_id=chat_instance.chat_db_model.id,
        )

    # Determine the model name
    model_name = llm_config.model_name

    # Set up LLM config and get (potentially) updated model name
    api_key = llm_config.secret.value if llm_config.secret else None
    model_name = llm_service.setup_llm_config(
        model_name=llm_config.model_name,
        provider=llm_config.provider,
        api_key=api_key,
    )

    backend = (
        "lmstudio"
        if llm_config.provider == llm_service.LLMProvider.LMSTUDIO
        else "litellm"
    )
    ai_msg, _, _ = chat_instance.send_user_msg_to_llm(
        model_name=model_name,
        text=user_message,
        user=user,
        include_chat_history=True,
        backend=backend,
    )

    return ai_msg.text, chat_instance


def stream_chat_with_resource(
    resource: Resource,
    user_message: str,
    llm_config: LLMConfig,
    chat_instance: Chat | None = None,
) -> Iterable[str]:
    """Send a message to chat with a resource's content and stream the response."""
    user = _get_or_create_chat_user()

    if chat_instance is None:
        chat_instance = Chat.create()
        # Set system message with resource context
        system_prompt = (
            f"You are a research assistant. The user is discussing a "
            f"{resource.get_resource_type_display()} from: {resource.url}\n\n"
            f"Here is the extracted content of the resource:\n\n"
            f"{resource.extracted_text}\n\n"
            f"Answer the user's questions based on this content. "
            f"Be precise and cite relevant parts of the text when applicable."
        )
        chat_instance.create_system_message(system_prompt, user)

        # Link Chat with Resource
        ResourceChat.objects.create(
            resource=resource,
            chat_id=chat_instance.chat_db_model.id,
        )

    # Determine the model name
    model_name = llm_config.model_name

    # Set up LLM config and get (potentially) updated model name
    api_key = llm_config.secret.value if llm_config.secret else None
    model_name = llm_service.setup_llm_config(
        model_name=llm_config.model_name,
        provider=llm_config.provider,
        api_key=api_key,
    )

    # Yield the chat_id first so the TUI knows which chat this belongs to
    yield f"__CHAT_ID__:{chat_instance.chat_db_model.id}"

    backend = (
        "lmstudio"
        if llm_config.provider == llm_service.LLMProvider.LMSTUDIO
        else "litellm"
    )
    yield from chat_instance.stream_user_msg_to_llm(
        model_name=model_name,
        text=user_message,
        user=user,
        include_chat_history=True,
        backend=backend,
    )


def get_chat_messages(chat_id: int) -> list[dict]:
    """Get all messages for a chat.

    Args:
        chat_id: The chat database model ID.

    Returns:
        List of message dicts.
    """
    messages = Message.objects.filter(chat_id=chat_id).order_by("date_created")
    return [
        {
            "id": msg.id,
            "type": msg.type,
            "text": msg.text,
            "date_created": str(msg.date_created),
        }
        for msg in messages
    ]


def get_chat_list() -> list[dict]:
    """Get all chats with their resource info and last message.

    Returns:
        List of chat data dicts.
    """
    resource_chats = ResourceChat.objects.select_related("resource").all()
    chat_ids = [rc.chat_id for rc in resource_chats]

    # Get Chat objects to get dates and token counts
    chats = {c.id: c for c in ChatModel.objects.filter(id__in=chat_ids)}

    # Get last message for each chat
    # This could be optimized but since it's a TUI for personal use it's fine for now
    results = []
    for rc in resource_chats:
        chat_model = chats.get(rc.chat_id)
        if not chat_model:
            continue

        last_msg = (
            Message.objects.filter(chat_id=rc.chat_id).order_by("-date_created").first()
        )
        results.append(
            {
                "id": rc.chat_id,
                "resource_id": rc.resource.id,
                "resource_url": rc.resource.url,
                "resource_title": rc.resource.title,
                "resource_summary": rc.resource.summary,
                "last_message": last_msg.text if last_msg else "",
                "date_updated": chat_model.date_updated,
            }
        )

    # Sort by date_updated descending
    results.sort(key=lambda x: x["date_updated"], reverse=True)
    return results


def continue_chat(
    chat_id: int,
    user_message: str,
    llm_config: LLMConfig,
) -> tuple[str, Chat]:
    """Continue an existing chat.

    Args:
        chat_id: The chat database model ID.
        user_message: The user's message.
        llm_config: LLM configuration to use.

    Returns:
        Tuple of (AI response text, Chat instance).
    """
    user = _get_or_create_chat_user()
    chat_db_model = ChatModel.objects.get(id=chat_id)

    # Reconstruct Chat instance from DB model
    # Chat.create() creates a new model, we want to wrap existing one.
    # Looking at Chat dataclass in django_llm_chat/chat.py:
    # @dataclass
    # class Chat:
    #     chat_db_model: ChatDBModel
    #     llm_user: object
    #     default_user: object

    # We need to get llm_user and default_user.
    # django_llm_chat/chat.py handles this in Chat.create().
    # We can probably use a similar logic or see if there's a better way.

    llm_user, _ = User.objects.get_or_create(
        username="litellm", defaults={"password": "litellm"}
    )

    default_user, _ = User.objects.get_or_create(
        username="djllmchat", defaults={"password": "djllmchat"}
    )

    chat_instance = Chat(
        chat_db_model=chat_db_model,
        llm_user=llm_user,
        default_user=default_user,
    )

    # Determine the model name
    model_name = llm_config.model_name
    api_key = llm_config.secret.value if llm_config.secret else None
    model_name = llm_service.setup_llm_config(
        model_name=llm_config.model_name,
        provider=llm_config.provider,
        api_key=api_key,
    )

    backend = (
        "lmstudio"
        if llm_config.provider == llm_service.LLMProvider.LMSTUDIO
        else "litellm"
    )
    ai_msg, _, _ = chat_instance.send_user_msg_to_llm(
        model_name=model_name,
        text=user_message,
        user=user,
        include_chat_history=True,
        backend=backend,
    )

    return ai_msg.text, chat_instance


def stream_continue_chat(
    chat_id: int,
    user_message: str,
    llm_config: LLMConfig,
) -> Iterable[str]:
    """Continue an existing chat and stream the response."""
    user = _get_or_create_chat_user()
    chat_db_model = ChatModel.objects.get(id=chat_id)

    llm_user, _ = User.objects.get_or_create(
        username="litellm", defaults={"password": "litellm"}
    )

    default_user, _ = User.objects.get_or_create(
        username="djllmchat", defaults={"password": "djllmchat"}
    )

    chat_instance = Chat(
        chat_db_model=chat_db_model,
        llm_user=llm_user,
        default_user=default_user,
    )

    # Determine the model name
    model_name = llm_config.model_name
    api_key = llm_config.secret.value if llm_config.secret else None
    model_name = llm_service.setup_llm_config(
        model_name=llm_config.model_name,
        provider=llm_config.provider,
        api_key=api_key,
    )

    backend = (
        "lmstudio"
        if llm_config.provider == llm_service.LLMProvider.LMSTUDIO
        else "litellm"
    )
    yield from chat_instance.stream_user_msg_to_llm(
        model_name=model_name,
        text=user_message,
        user=user,
        include_chat_history=True,
        backend=backend,
    )
