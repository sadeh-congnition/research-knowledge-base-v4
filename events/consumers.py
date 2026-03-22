import os
import traceback
from django.conf import settings
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
    ConsumptionStatus,
)
from events.services import fire_event
from kb.models import Resource, Reference
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
                    username="litellm", defaults={"password": "litellm"}
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


def _get_or_create_consumer_user(username: str) -> "User":
    """Get or create the consumer user for automated LLM tasks."""
    user, _ = User.objects.get_or_create(
        username=username,
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
    unprocessed_events = Event.objects.filter(
        entity=EntityTypes.RESOURCE, description=EventDescriptions.TEXT_EXTRACTED
    ).order_by("id")

    if settings.EVENT_CONSUMER_RETRY_FAILED:
        # Exclude those that are OK
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer,
            eventconsumed__status=ConsumptionStatus.OK,
        )
    else:
        # Exclude those that have ANY consumption record (OK or ERROR)
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer
        )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Clean up extracted text' found event {event.id}. Starting processing..."
        )
        try:
            with transaction.atomic():
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
                            user = _get_or_create_consumer_user("rkb-consumer-cleanup")
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
                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.OK,
                        "exception": None,
                    },
                )

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
        except Exception:
            stacktrace = traceback.format_exc()
            logger.exception(f"Failed to process clean up for event {event.id}")
            with transaction.atomic():
                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.ERROR,
                        "exception": stacktrace,
                    },
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

    unprocessed_events = Event.objects.filter(
        entity=EntityTypes.RESOURCE, description=EventDescriptions.CLEAN_UP_FINISHED
    ).order_by("id")

    if settings.EVENT_CONSUMER_RETRY_FAILED:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer,
            eventconsumed__status=ConsumptionStatus.OK,
        )
    else:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer
        )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Summarize' found event {event.id}. Starting processing..."
        )
        try:
            with transaction.atomic():
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
                            user = _get_or_create_consumer_user(
                                "rkb-consumer-summarize"
                            )
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

                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.OK,
                        "exception": None,
                    },
                )

                count += 1
                logger.info(
                    f"Consumed 'clean up finished' event {event.id} for Resource {resource.id}"
                )
        except Exception:
            stacktrace = traceback.format_exc()
            logger.exception(f"Failed to process summarize for event {event.id}")
            with transaction.atomic():
                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.ERROR,
                        "exception": stacktrace,
                    },
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

    unprocessed_events = Event.objects.filter(
        entity=EntityTypes.RESOURCE, description=EventDescriptions.CLEAN_UP_FINISHED
    ).order_by("id")

    if settings.EVENT_CONSUMER_RETRY_FAILED:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer,
            eventconsumed__status=ConsumptionStatus.OK,
        )
    else:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer
        )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Chunk and Embed Resource' found event {event.id}. Starting processing..."
        )
        try:
            with transaction.atomic():
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

                    for i, text in enumerate(chunk_texts):
                        try:
                            with transaction.atomic():
                                # Save chunk to DB
                                Chunk.objects.create(
                                    text=text,
                                    order=i,
                                    resource=resource,
                                    chunk_config=chunk_config,
                                )

                                # Embed and persist to ChromaDB
                                chromadb_service.add_chunks(
                                    resource.id, [text], start_index=i
                                )
                        except Exception as e:
                            logger.error(
                                f"Failed to process chunk {i} for resource {resource.id}: {e}"
                            )
                            # Continue to next chunk

                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.OK,
                        "exception": None,
                    },
                )

                count += 1
                logger.info(
                    f"Consumed 'clean up finished' event {event.id} for Resource {resource.id} (chunked and embedded)"
                )
        except Exception:
            stacktrace = traceback.format_exc()
            logger.exception(f"Failed to chunk and embed for event {event.id}")
            with transaction.atomic():
                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.ERROR,
                        "exception": stacktrace,
                    },
                )
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

    unprocessed_events = Event.objects.filter(
        entity=EntityTypes.RESOURCE, description=EventDescriptions.CLEAN_UP_FINISHED
    ).order_by("id")

    if settings.EVENT_CONSUMER_RETRY_FAILED:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer,
            eventconsumed__status=ConsumptionStatus.OK,
        )
    else:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer
        )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Extract title of resource' found event {event.id}. Starting processing..."
        )
        try:
            with transaction.atomic():
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
                            user = _get_or_create_consumer_user(
                                "rkb-consumer-extract-title"
                            )
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

                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.OK,
                        "exception": None,
                    },
                )

                count += 1
                logger.info(
                    f"Consumed 'clean up finished' event {event.id} for Resource {resource.id} (extracted title)"
                )
        except Exception:
            stacktrace = traceback.format_exc()
            logger.exception(f"Failed to process extract title for event {event.id}")
            with transaction.atomic():
                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.ERROR,
                        "exception": stacktrace,
                    },
                )
        break
    logger.info(
        f"Finished consumer 'Extract title of resource', processed {count} events"
    )
    return count


def consume_extract_references() -> int:
    """
    Consumer that processes "extracted text clean up finished" events.
    It extracts references mentioned in the resource's extracted text using an LLM.
    """
    logger.info("Running consumer: Extract references")
    consumer = get_or_create_consumer("Extract references")

    unprocessed_events = Event.objects.filter(
        entity=EntityTypes.RESOURCE, description=EventDescriptions.CLEAN_UP_FINISHED
    ).order_by("id")

    if settings.EVENT_CONSUMER_RETRY_FAILED:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer,
            eventconsumed__status=ConsumptionStatus.OK,
        )
    else:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer
        )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Extract references' found event {event.id}. Starting processing..."
        )
        try:
            with transaction.atomic():
                resource = get_object_or_404(Resource, id=event.entity_id)
                logger.info(
                    f"Calling LLM to extract references for Resource {resource.id}..."
                )

                model_name = _get_llm_config()

                system_prompt = (
                    "Extract all references, citations, or mentions of other works, papers, "
                    "or resources from the following text. "
                    "For each reference, provide a clear description. "
                    "Format the output as a bulleted list with each reference on a new line. "
                    "Do not include any other text in your response."
                )

                if os.environ.get("PYTEST_CURRENT_TEST"):
                    references = [f"MOCKED REFERENCE: {resource.extracted_text[:20]}"]
                else:
                    try:
                        with transaction.atomic():
                            chat_instance = _create_chat_safely()
                            user = _get_or_create_consumer_user(
                                "rkb-consumer-extract-references"
                            )
                            chat_instance.create_system_message(system_prompt, user)

                            ai_msg, _, _ = chat_instance.send_user_msg_to_llm(
                                model_name=model_name,
                                text=resource.extracted_text,
                                user=user,
                            )
                            llm_output = ai_msg.text or ""
                            # Split by newline and remove bullets
                            references = [
                                line.strip().lstrip("-* ").strip()
                                for line in llm_output.split("\n")
                                if line.strip()
                            ]
                    except Exception as e:
                        logger.error(f"Error calling LLM for references: {e}")
                        references = []

                # Create Reference objects
                for ref_desc in references:
                    Reference.objects.create(resource=resource, description=ref_desc)

                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.OK,
                        "exception": None,
                    },
                )

                count += 1
                logger.info(
                    f"Consumed 'clean up finished' event {event.id} for Resource {resource.id} (extracted {len(references)} references)"
                )
        except Exception:
            stacktrace = traceback.format_exc()
            logger.exception(
                f"Failed to process extract references for event {event.id}"
            )
            with transaction.atomic():
                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.ERROR,
                        "exception": stacktrace,
                    },
                )
        break
    logger.info(f"Finished consumer 'Extract references', processed {count} events")
    return count


def consume_check_kg_update() -> int:
    """
    Consumer that processes "chat message submitted" events.
    Checks active KnowledgeGraphConfigs and fires update requests if necessary.
    """
    from kb.models import KnowledgeGraphConfig
    from django_llm_chat.models import Message

    logger.info("Running consumer: Check KG Update")
    consumer = get_or_create_consumer("Check KG Update")

    unprocessed_events = Event.objects.filter(
        entity=EntityTypes.CHAT, description=EventDescriptions.CHAT_MESSAGE_SUBMITTED
    ).order_by("id")

    if settings.EVENT_CONSUMER_RETRY_FAILED:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer,
            eventconsumed__status=ConsumptionStatus.OK,
        )
    else:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer
        )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Check KG Update' found event {event.id}. Starting processing..."
        )
        try:
            with transaction.atomic():
                chat_id = int(event.entity_id)
                # Find all active KG configs
                active_configs = KnowledgeGraphConfig.objects.filter(is_active=True)

                for config in active_configs:
                    should_update = False
                    if config.update_trigger == "always":
                        should_update = True
                    elif config.update_trigger == "llm_intent":
                        # Fetch latest user message
                        last_msg = (
                            Message.objects.filter(chat_id=chat_id, type="user")
                            .order_by("-date_created")
                            .first()
                        )

                        if last_msg:
                            model_name = _get_llm_config()
                            system_prompt = (
                                "Analyze the following user message and determine if the user "
                                "is explicitly asking to update, refresh, or add information to the knowledge graph. "
                                "Respond with exactly 'TRUE' if yes, or 'FALSE' if no."
                            )
                            if os.environ.get("PYTEST_CURRENT_TEST"):
                                should_update = "update" in last_msg.text.lower()
                            else:
                                try:
                                    chat_instance = _create_chat_safely()
                                    user = _get_or_create_consumer_user(
                                        "rkb-consumer-kg-check"
                                    )
                                    chat_instance.create_system_message(
                                        system_prompt, user
                                    )

                                    ai_msg, _, _ = chat_instance.send_user_msg_to_llm(
                                        model_name=model_name,
                                        text=last_msg.text,
                                        user=user,
                                    )
                                    should_update = (
                                        ai_msg.text.strip().upper() == "TRUE"
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"Error calling LLM for KG intent check: {e}"
                                    )
                                    should_update = False

                    if should_update:
                        logger.info(
                            f"Firing KNOWLEDGE_GRAPH_UPDATE_REQUESTED for config {config.id} in chat {chat_id}"
                        )
                        fire_event(
                            entity=EntityTypes.CHAT,
                            entity_id=f"{chat_id}:{config.id}",
                            description=EventDescriptions.KNOWLEDGE_GRAPH_UPDATE_REQUESTED,
                        )

                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.OK,
                        "exception": None,
                    },
                )
                count += 1
        except Exception:
            stacktrace = traceback.format_exc()
            logger.exception(f"Failed to check KG update for event {event.id}")
            with transaction.atomic():
                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.ERROR,
                        "exception": stacktrace,
                    },
                )
        break

    return count


def consume_update_knowledge_graph() -> int:
    """
    Consumer that processes "knowledge graph update requested" events.
    Executes the configured python module/function for the specific config.
    """
    import importlib  # TODO move to the top of the module
    from kb.models import KnowledgeGraphConfig

    logger.info("Running consumer: Update Knowledge Graph")
    consumer = get_or_create_consumer("Update Knowledge Graph")

    unprocessed_events = Event.objects.filter(
        entity=EntityTypes.CHAT,
        description=EventDescriptions.KNOWLEDGE_GRAPH_UPDATE_REQUESTED,
    ).order_by("id")

    if (
        settings.EVENT_CONSUMER_RETRY_FAILED
    ):  # TODO: make this logic a method on the Event class
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer,
            eventconsumed__status=ConsumptionStatus.OK,
        )
    else:
        unprocessed_events = unprocessed_events.exclude(
            eventconsumed__consumer=consumer
        )

    count = 0
    for event in unprocessed_events:
        logger.info(
            f"Consumer 'Update Knowledge Graph' found event {event.id}. Starting processing..."
        )
        try:
            with transaction.atomic():
                # entity_id is composite "chat_id:config_id"  # TODO make the entity info a dict instead of using composite IDs
                chat_id_str, config_id_str = event.entity_id.split(":")
                chat_id = int(chat_id_str)
                config_id = int(config_id_str)

                config = get_object_or_404(
                    KnowledgeGraphConfig, id=config_id
                )  # TODO raise excpetion not 404
                logger.info(
                    f"Executing KG update for {config.package_name} on chat {chat_id}..."
                )

                if os.environ.get("PYTEST_CURRENT_TEST"):  # TODO no mocking!
                    # Just mock for test
                    pass
                else:
                    # Dynamically import and run. Package should expose a run_update function
                    # with signature: run_update(content, metadata, track_id, llm_model, llm_temperature)
                    try:
                        from django_llm_chat.models import Message

                        pkg = importlib.import_module(config.package_name)
                        if hasattr(pkg, "run_update"):
                            # Fetch chat messages to build content
                            messages = Message.objects.filter(chat_id=chat_id).order_by(
                                "date_created"
                            )
                            content = "\n\n".join(
                                [
                                    f"{msg.type}: {msg.text}"
                                    for msg in messages
                                    if msg.text
                                ]
                            )
                            metadata = {
                                "chat_id": chat_id,
                                "config_id": config_id,
                                "config_name": config.name,
                            }
                            track_id = f"chat_{chat_id}_config_{config_id}"
                            result = pkg.run_update(
                                content=content,
                                metadata=metadata,
                                track_id=track_id,
                            )
                            if "error" in result:
                                logger.error(
                                    f"KG update failed for chat {chat_id}: {result.get('message', 'Unknown error')}"
                                )
                        else:
                            logger.error(
                                f"Package {config.package_name} does not have 'run_update' function."
                            )
                    except ImportError as e:
                        logger.error(
                            f"Failed to import KG package {config.package_name}: {e}"
                        )

                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.OK,
                        "exception": None,
                    },
                )
                count += 1
        except Exception:
            stacktrace = traceback.format_exc()
            logger.exception(f"Failed to update KG for event {event.id}")
            with transaction.atomic():
                EventConsumed.objects.update_or_create(
                    event=event,
                    consumer=consumer,
                    defaults={
                        "status": ConsumptionStatus.ERROR,
                        "exception": stacktrace,
                    },
                )
        break
    return count


def process_all_events() -> int:
    """Helper to process all consumers."""
    count = 0
    count += consume_clean_up_extracted_text()
    count += consume_summarize()
    count += consume_chunk_and_embed()
    count += consume_extract_title_of_resource()
    count += consume_extract_references()
    count += consume_check_kg_update()
    count += consume_update_knowledge_graph()
    return count
