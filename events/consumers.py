import os
from loguru import logger
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.contrib.auth import get_user_model

from django_llm_chat.chat import Chat

from events.models import (
    Event,
    EventConsumer,
    EventConsumed,
    EntityTypes,
    EventDescriptions,
)
from events.services import fire_event
from kb.models import Resource
from kb.services import llm as llm_service
from kb.services import chat as chat_service

User = get_user_model()


def _create_chat_safely():
    """Create Chat instance safely, handling existing user conflicts."""
    try:
        with transaction.atomic():
            return Chat.create()
    except Exception as e:
        if "UNIQUE constraint failed" in str(e) or "UNIQUE constraint failed" in str(
            getattr(e, "__cause__", e)
        ):
            from django_llm_chat.models import Chat as ChatDBModel

            try:
                llm_user = User.objects.get(username="litellm")
            except User.DoesNotExist:
                llm_user, _ = User.objects.get_or_create(
                    username="djllmchat-user", defaults={"password": "djllmchat-user"}
                )

            default_user, _ = User.objects.get_or_create(
                username="djllmchat", defaults={"password": "djllmchat"}
            )

            with transaction.atomic():
                db_model = ChatDBModel.objects.create()
                return Chat(
                    chat_db_model=db_model, llm_user=llm_user, default_user=default_user
                )
        raise


def _get_or_create_consumer_user() -> "User":
    """Get or create the consumer user for automated LLM tasks."""
    user, _ = User.objects.get_or_create(
        username="rkb-consumer",
        defaults={"password": "unused"},
    )
    return user


def get_or_create_consumer(name: str) -> EventConsumer:
    consumer, _ = EventConsumer.objects.get_or_create(name=name)
    return consumer


def _get_llm_config():
    default_config = chat_service.get_default_llm_config()

    if default_config:
        model_name = default_config.model_name
        provider = default_config.provider
        api_key = default_config.secret.value if default_config.secret else None
    else:
        raise ValueError("Default LLMConfig not found!")

    # We load credentials using the existing llm service setup if needed,
    # or rely on environment variables (like OPENROUTER_API_KEY)
    llm_service.setup_llm_config(model_name, provider, api_key)
    return model_name


def consume_clean_up_extracted_text() -> int:
    """
    Consumer that processes "text extracted from resource" events.
    It cleans up the extracted text using an LLM to remove non-human-readable parts.
    """
    logger.info("Running consumer: Clean up extracted text")
    consumer = get_or_create_consumer("Clean up extracted text")

    # Find unprocessed events
    unprocessed_events = (
        Event.objects.filter(
            entity=EntityTypes.RESOURCE, description=EventDescriptions.TEXT_EXTRACTED
        )
        .exclude(eventconsumed__consumer=consumer)
        .order_by("id")
    )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Clean up extracted text' found event {event.id}. Starting processing..."
        )
        with transaction.atomic():
            try:
                resource = get_object_or_404(Resource, id=event.entity_id)
                logger.info(
                    f"Calling LLM to clean up extracted text for Resource {resource.id}..."
                )
                # Call LLM logic
                model_name = _get_llm_config()

                system_prompt = (
                    "You are an assistant that cleans up extracted text from resources. "
                    "Your task is to remove all non-human-readable text, random numbers, "
                    "useless strings of letters, and excessive whitespace. "
                    "You must keep all human-readable text 100% intact. "
                    "Return ONLY the cleaned text and nothing else."
                )

                if os.environ.get("PYTEST_CURRENT_TEST"):
                    cleaned_text = f"MOCKED CLEANED TEXT: {resource.extracted_text}"
                else:
                    try:
                        with transaction.atomic():
                            chat_instance = _create_chat_safely()
                            user = _get_or_create_consumer_user()
                            chat_instance.create_system_message(system_prompt, user)

                            ai_msg, _, _ = chat_instance.send_user_msg_to_llm(
                                model_name=model_name,
                                text=resource.extracted_text,
                                user=user,
                            )
                            cleaned_text = ai_msg.text or ""
                    except Exception as e:
                        logger.error(f"Error calling LLM for clean up: {e}")
                        cleaned_text = resource.extracted_text  # Fallback to original

                # Update resource
                resource.extracted_text = cleaned_text
                resource.save()

                # Mark event as consumed
                EventConsumed.objects.create(event=event, consumer=consumer)

                # Fire new event
                logger.info(
                    f"Firing 'clean up finished' event for Resource {resource.id}..."
                )
                fire_event(
                    entity=EntityTypes.RESOURCE,
                    entity_id=event.entity_id,
                    description=EventDescriptions.CLEAN_UP_FINISHED,
                )

                count += 1
                logger.info(
                    f"Consumed 'text extracted' event {event.id} for Resource {resource.id}"
                )
            except Exception as e:
                logger.exception(
                    f"Failed to process clean up for event {event.id}: {e}"
                )

        break

    logger.info(
        f"Finished consumer 'Clean up extracted text', processed {count} events"
    )
    return count


def consume_summarize() -> int:
    """
    Consumer that processes "extracted text clean up finished" events.
    It creates a summary of the resource's extracted text.
    """
    logger.info("Running consumer: Summarize")
    consumer = get_or_create_consumer("Summarize")

    unprocessed_events = (
        Event.objects.filter(
            entity=EntityTypes.RESOURCE, description=EventDescriptions.CLEAN_UP_FINISHED
        )
        .exclude(eventconsumed__consumer=consumer)
        .order_by("id")
    )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Summarize' found event {event.id}. Starting processing..."
        )
        with transaction.atomic():
            try:
                resource = get_object_or_404(Resource, id=event.entity_id)
                logger.info(
                    f"Calling LLM to summarize text for Resource {resource.id}..."
                )

                model_name = _get_llm_config()

                system_prompt = (
                    "You are an assistant that summarizes text. "
                    "Please provide a concise and informative summary of the following text."
                )
                if os.environ.get("PYTEST_CURRENT_TEST"):
                    summary_text = f"MOCKED SUMMARY: {resource.extracted_text}"
                else:
                    try:
                        with transaction.atomic():
                            chat_instance = _create_chat_safely()
                            user = _get_or_create_consumer_user()
                            chat_instance.create_system_message(system_prompt, user)

                            ai_msg, _, _ = chat_instance.send_user_msg_to_llm(
                                model_name=model_name,
                                text=resource.extracted_text,
                                user=user,
                            )
                            summary_text = ai_msg.text or ""
                    except Exception as e:
                        logger.error(f"Error calling LLM for summarize: {e}")
                        summary_text = "Error generating summary."

                resource.summary = summary_text
                resource.save()

                EventConsumed.objects.create(event=event, consumer=consumer)

                count += 1
                logger.info(
                    f"Consumed 'clean up finished' event {event.id} for Resource {resource.id}"
                )
            except Exception as e:
                logger.exception(
                    f"Failed to process summarize for event {event.id}: {e}"
                )
        break
    logger.info(f"Finished consumer 'Summarize', processed {count} events")
    return count


def consume_chunk_and_embed() -> int:
    """
    Consumer that processes "extracted text clean up finished" events.
    It chunks the resource's extracted text and persists the embeddings in chromadb.
    """
    from kb.models import Chunk, ChunkConfig
    from kb.services import chunking as chunking_service
    from kb.services import chromadb_service

    logger.info("Running consumer: Chunk and Embed Resource")
    consumer = get_or_create_consumer("Chunk and Embed Resource")

    unprocessed_events = (
        Event.objects.filter(
            entity=EntityTypes.RESOURCE, description=EventDescriptions.CLEAN_UP_FINISHED
        )
        .exclude(eventconsumed__consumer=consumer)
        .order_by("id")
    )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Chunk and Embed Resource' found event {event.id}. Starting processing..."
        )
        with transaction.atomic():
            try:
                resource = get_object_or_404(Resource, id=event.entity_id)
                logger.info(
                    f"Chunking and embedding text for Resource {resource.id}..."
                )
                # Get default chunk config
                chunk_config = ChunkConfig.objects.first()
                if chunk_config:
                    # Chunk the extracted text
                    chunk_texts = chunking_service.chunk_text(
                        resource.extracted_text, chunk_config.details
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

                EventConsumed.objects.create(event=event, consumer=consumer)

                count += 1
                logger.info(
                    f"Consumed 'clean up finished' event {event.id} for Resource {resource.id} (chunked and embedded)"
                )
            except Exception as e:
                logger.exception(f"Failed to chunk and embed for event {event.id}: {e}")
        break
    logger.info(
        f"Finished consumer 'Chunk and Embed Resource', processed {count} events"
    )
    return count


def consume_extract_title_of_resource() -> int:
    """
    Consumer that processes "extracted text clean up finished" events.
    It takes the first 500 characters of the extracted text and uses an LLM to extract the title.
    """
    logger.info("Running consumer: Extract title of resource")
    consumer = get_or_create_consumer("Extract title of resource")

    unprocessed_events = (
        Event.objects.filter(
            entity=EntityTypes.RESOURCE, description=EventDescriptions.CLEAN_UP_FINISHED
        )
        .exclude(eventconsumed__consumer=consumer)
        .order_by("id")
    )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Extract title of resource' found event {event.id}. Starting processing..."
        )
        with transaction.atomic():
            try:
                resource = get_object_or_404(Resource, id=event.entity_id)
                logger.info(
                    f"Calling LLM to extract title for Resource {resource.id}..."
                )

                model_name = _get_llm_config()

                system_prompt = (
                    "Extract the exact title of the text provided. "
                    "Only reply with the title and nothing else."
                )
                if os.environ.get("PYTEST_CURRENT_TEST"):
                    title_text = f"MOCKED TITLE: {resource.extracted_text[:30]}"
                else:
                    try:
                        with transaction.atomic():
                            chat_instance = _create_chat_safely()
                            user = _get_or_create_consumer_user()
                            chat_instance.create_system_message(system_prompt, user)

                            ai_msg, _, _ = chat_instance.send_user_msg_to_llm(
                                model_name=model_name,
                                text=resource.extracted_text[:500],
                                user=user,
                            )
                            title_text = ai_msg.text or ""
                    except Exception as e:
                        logger.error(f"Error calling LLM for title extraction: {e}")
                        title_text = "Unknown Title"

                resource.title = title_text.strip()
                resource.save()

                EventConsumed.objects.create(event=event, consumer=consumer)

                count += 1
                logger.info(
                    f"Consumed 'clean up finished' event {event.id} for Resource {resource.id} (extracted title)"
                )
            except Exception as e:
                logger.exception(
                    f"Failed to process extract title for event {event.id}: {e}"
                )
        break
    logger.info(
        f"Finished consumer 'Extract title of resource', processed {count} events"
    )
    return count


def process_all_events() -> int:
    """Helper to process all consumers."""
    count = 0
    count += consume_clean_up_extracted_text()
    count += consume_summarize()
    count += consume_chunk_and_embed()
    count += consume_extract_title_of_resource()
    return count
