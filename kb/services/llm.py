import os
from enum import Enum
from django.conf import settings


class LLMProvider(str, Enum):
    OPENROUTER = "openrouter"
    GROQ = "groq"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LMSTUDIO = "lmstudio"


def setup_llm_config(
    model_name: str, provider: LLMProvider | str, api_key: str | None
) -> str:
    """
    Sets up the environment variables for the given LLM provider and API key.
    Returns the potentially modified model name.
    """
    if isinstance(provider, str):
        provider_str = provider.lower()
    else:
        provider_str = provider.value.lower()

    if provider_str == LLMProvider.LMSTUDIO.value:
        os.environ["LM_STUDIO_API_BASE"] = settings.LMSTUDIO_BASE_URL
        if api_key:
            os.environ["LM_STUDIO_API_KEY"] = api_key
        return model_name

    # Prefix model name with provider for LiteLLM if not already present
    if not model_name.startswith(f"{provider_str}/"):
        model_name = f"{provider_str}/{model_name}"

    if api_key:
        if provider_str == LLMProvider.OPENROUTER.value:
            os.environ["OPENROUTER_API_KEY"] = api_key
        elif provider_str == LLMProvider.OPENAI.value:
            os.environ["OPENAI_API_KEY"] = api_key
        elif provider_str == LLMProvider.ANTHROPIC.value:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        elif provider_str == LLMProvider.GROQ.value:
            os.environ["GROQ_API_KEY"] = api_key
        else:
            # Default to OpenAI if it matches the string or is unknown
            os.environ["OPENAI_API_KEY"] = api_key
    return model_name
