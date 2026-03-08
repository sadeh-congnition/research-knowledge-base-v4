from django.contrib.auth import get_user_model

from django_llm_chat.chat import Chat
from django_llm_chat.models import Message

from kb.models import LLMConfig, Resource

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

    # Determine the model name
    model_name = llm_config.model_name

    # Set API key as environment variable if the config has a secret
    if llm_config.secret:
        import os

        os.environ["OPENAI_API_KEY"] = llm_config.secret.value

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
