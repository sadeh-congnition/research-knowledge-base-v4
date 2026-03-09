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

    ai_msg: Message
    ai_msg, _, _ = chat_instance.send_user_msg_to_llm(
        model_name=model_name,
        text=user_message,
        user=user,
        include_chat_history=True,
    )

    return ai_msg.text, chat_instance


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

        last_msg = Message.objects.filter(chat_id=rc.chat_id).order_by("-date_created").first()
        results.append({
            "id": rc.chat_id,
            "resource_id": rc.resource.id,
            "resource_url": rc.resource.url,
            "last_message": last_msg.text if last_msg else "",
            "date_updated": chat_model.date_updated,
        })

    # Sort by date_updated descending
    results.sort(key=lambda x: x["date_updated"], reverse=True)
    return results
