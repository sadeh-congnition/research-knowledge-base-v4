from dataclasses import dataclass
from typing import Callable, Awaitable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    Static,
    DataTable,
    OptionList,
)

import httpx
from loguru import logger

from kb.tui_logging_config import setup_textual_logging, setup_from_env

BASE_URL = "http://localhost:8001/api"


@dataclass
class Command:
    """TUI command definition."""

    name: str  # canonical slash command, e.g., "/help"
    aliases: list[str]  # slash aliases, e.g., ["/h"]
    usage: str  # usage string, e.g., "/help" or "/chat <res_id>"
    description: str  # short description for help and autocomplete
    takes_argument: bool  # whether the command expects an argument
    handler: Callable[
        ["ResearchKBApp", str], None | Awaitable[None]
    ]  # handler to invoke


# Command registry - centralized source of truth for all TUI commands
COMMAND_REGISTRY: dict[str, Command] = {}


def _register_command(cmd: Command) -> None:
    """Register a command and its aliases in the global registry."""
    COMMAND_REGISTRY[cmd.name] = cmd
    for alias in cmd.aliases:
        COMMAND_REGISTRY[alias] = cmd


def _resolve_command(input_text: str) -> tuple[Command | None, str, str | None]:
    """Resolve user input to a command.

    Returns: (command_or_none, canonical_name, argument_or_none)
    """
    parts = input_text.strip().split(maxsplit=1)
    if not parts:
        return None, "", None

    cmd_key = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    # Check if it's a bare command (no leading slash)
    if not cmd_key.startswith("/"):
        return None, cmd_key, args if args else None

    cmd = COMMAND_REGISTRY.get(cmd_key)
    if cmd:
        return cmd, cmd.name, args if args else None

    return None, cmd_key, args if args else None


def _get_all_commands() -> list[Command]:
    """Get all unique commands (by canonical name) from the registry."""
    seen = set()
    result = []
    for cmd in COMMAND_REGISTRY.values():
        if cmd.name not in seen:
            seen.add(cmd.name)
            result.append(cmd)
    return sorted(result, key=lambda c: c.name)


def _format_help_text() -> str:
    """Generate help text from the command registry."""
    lines = ["[bold]Welcome to Research Knowledge Base[/bold]\n", "Commands:"]

    for cmd in _get_all_commands():
        alias_str = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
        lines.append(f"  [bold]{cmd.name}[/bold]{alias_str}")
        lines.append(f"      Usage: {cmd.usage}")
        lines.append(f"      {cmd.description}")

    lines.append("\n[italic]All commands must start with / (e.g., /help)[/italic]")
    return "\n".join(lines)


def _get_command_suggestions(partial: str) -> list[Command]:
    """Get command suggestions matching the partial input.

    partial: The partial command starting with /
    """
    if not partial.startswith("/"):
        return []

    partial_lower = partial.lower()
    matches = []
    seen = set()

    for cmd in _get_all_commands():
        # Match against canonical name
        if cmd.name.startswith(partial_lower) and cmd.name not in seen:
            seen.add(cmd.name)
            matches.append(cmd)
        else:
            # Match against aliases
            for alias in cmd.aliases:
                if alias.startswith(partial_lower) and cmd.name not in seen:
                    seen.add(cmd.name)
                    matches.append(cmd)
                    break

    return matches


def _format_suggestion(cmd: Command) -> str:
    """Format a command for the suggestion list."""
    alias_str = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
    return f"{cmd.name}{alias_str} - {cmd.description}"


class ChatMessage(Static):
    """A single chat message."""

    def __init__(self, text: str, is_user: bool = True) -> None:
        self.prefix = "You" if is_user else "AI"
        self.message_text = text
        super().__init__(f"[bold]{self.prefix}:[/bold] {text}")
        self.add_class("user-msg" if is_user else "ai-msg")

    def update_text(self, text: str) -> None:
        """Update the message text."""
        self.message_text = text
        self.update(f"[bold]{self.prefix}:[/bold] {self.message_text}")


class ResourceChatScreen(Container):
    """Chat interface for chatting with a resource."""

    def __init__(
        self,
        resource_id: int,
        resource_url: str,
        resource_title: str | None = None,
        resource_summary: str | None = None,
        chat_id: int | None = None,
    ) -> None:
        super().__init__()
        self.resource_id = resource_id
        self.resource_url = resource_url
        self.resource_title = resource_title
        self.resource_summary = resource_summary
        self.chat_id = chat_id

    def on_mount(self) -> None:
        """Called when the screen is mounted."""
        if self.chat_id:
            self._load_history()

    def _load_history(self) -> None:
        """Load history for an existing chat."""
        messages_container = self.query_one("#chat-messages", VerticalScroll)
        messages_container.mount(ChatMessage("Loading history...", is_user=False))

        try:
            response = httpx.get(
                f"{BASE_URL}/chat/{self.chat_id}/messages/", timeout=5.0
            )
            messages_container.remove_children()
            if response.status_code == 200:
                messages = response.json()
                for msg in messages:
                    if msg["type"] == "system":
                        continue
                    is_user = msg["type"] == "user"
                    messages_container.mount(ChatMessage(msg["text"], is_user=is_user))
                messages_container.scroll_end()
            else:
                messages_container.mount(
                    ChatMessage(
                        f"Error loading history: {response.text}", is_user=False
                    )
                )
        except Exception as e:
            logger.exception("Error loading chat history")
            messages_container.mount(
                ChatMessage(f"Error loading history: {e}", is_user=False)
            )

    def compose(self) -> ComposeResult:
        title_display = (
            f"{self.resource_title} ({self.resource_url})"
            if self.resource_title
            else self.resource_url
        )
        yield Label(
            f"[bold]Chatting with:[/bold] {title_display}",
            id="chat-resource-label",
        )
        if self.resource_summary:
            with VerticalScroll(id="chat-resource-summary-container"):
                yield Static(
                    f"[italic]Summary:[/italic]\n{self.resource_summary}",
                    id="chat-resource-summary",
                )
        yield VerticalScroll(id="chat-messages")
        yield Input(placeholder="Type a message...", id="chat-input")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle chat input submission."""
        message = event.value.strip()
        if not message:
            return

        event.input.value = ""
        messages_container = self.query_one("#chat-messages", VerticalScroll)
        messages_container.mount(ChatMessage(message, is_user=True))

        try:
            from kb.schemas import ChatMessageIn

            payload = ChatMessageIn(
                resource_id=self.resource_id if self.chat_id is None else None,
                chat_id=self.chat_id,
                message=message,
            )

            # Create an empty AI message to stream into
            ai_message_widget = ChatMessage("", is_user=False)
            messages_container.mount(ai_message_widget)
            messages_container.scroll_end()

            full_response = ""
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{BASE_URL}/chat/stream/",
                    json=payload.dict(),
                    timeout=30.0,
                ) as response:
                    if response.status_code == 200:
                        async for chunk in response.aiter_text():
                            if not chunk:
                                continue

                            # Handle special chat_id chunk
                            if chunk.startswith("__CHAT_ID__:"):
                                self.chat_id = int(chunk.split(":")[1])
                                continue

                            full_response += chunk
                            ai_message_widget.update_text(full_response)
                            messages_container.scroll_end()
                    else:
                        error_text = await response.aread()
                        ai_message_widget.update_text(f"Error: {error_text.decode()}")
        except Exception as e:
            logger.exception("Error during chat message sending")
            messages_container.mount(ChatMessage(f"Error: {e}", is_user=False))

        messages_container.scroll_end()


class ResourceDetailsScreen(Container):
    """Screen for displaying resource details in a split layout."""

    def __init__(self, resource: dict) -> None:
        super().__init__()
        self.resource = resource

    def compose(self) -> ComposeResult:
        res_id = self.resource.get("id", "Unknown")
        url = self.resource.get("url", "Unknown")
        title = self.resource.get("title", "No Title")

        # Prepare references text
        references = self.resource.get("references", [])
        if references:
            ref_lines = ["[bold]References[/bold]\n"]
            for ref in references:
                ref_lines.append(f"• {ref['description']}")
            references_text = "\n".join(ref_lines)
        else:
            references_text = "[bold]References[/bold]\n\nNo references extracted."

        yield Label(
            f"[bold]Resource Details (ID: {res_id})[/bold] | {title}\n{url}",
            classes="details-header",
        )
        yield Horizontal(
            VerticalScroll(
                Label(
                    "[bold]Extracted Text[/bold]\n\n"
                    + self.resource.get("extracted_text", "No text available.")
                ),
                id="details-left",
            ),
            VerticalScroll(
                Label(
                    "[bold]Summary[/bold]\n\n"
                    + self.resource.get("summary", "No summary available.")
                ),
                Label("\n" + references_text),
                id="details-right",
            ),
            id="details-container",
        )


class SemanticSearchScreen(Container):
    """Screen for semantic search against chunks."""

    def compose(self) -> ComposeResult:
        yield Label("[bold]Semantic Search[/bold]", classes="details-header")
        yield Input(placeholder="Type to search...", id="semantic-search-input")
        yield Horizontal(
            VerticalScroll(
                DataTable(id="semantic-search-results", cursor_type="row"),
                id="search-left",
            ),
            VerticalScroll(
                Static(
                    "[italic]Select a result to see context...[/italic]",
                    id="search-context-view",
                ),
                id="search-right",
            ),
            id="search-split-container",
        )

    def on_mount(self) -> None:
        table = self.query_one("#semantic-search-results", DataTable)
        table.add_columns("Score", "Res ID", "Order", "Text")

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Handle character changes for live search."""
        if event.input.id != "semantic-search-input":
            return

        query = event.value.strip()
        table = self.query_one(
            "#semantic-search-results",
            DataTable,
        )
        table.clear()

        if not query:
            return

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{BASE_URL}/search/",
                    params={"query": query, "n_results": 10},
                    timeout=5.0,
                )
            if response.status_code == 200:
                results = response.json()
                for res in results:
                    score_str = f"{res['distance']:.4f}"
                    # Truncate text for display
                    text = res["document"].replace("\n", " ")
                    if len(text) > 50:
                        text = text[:47] + "..."
                    table.add_row(
                        score_str,
                        str(res["resource_id"]),
                        str(res["chunk_order"]),
                        text,
                        key=f"res_{res['resource_id']}_chunk_{res['chunk_order']}",
                    )
        except Exception:
            logger.exception("Search API error")

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection to show context."""
        row_key = event.row_key.value
        if not row_key or not row_key.startswith("res_"):
            return

        # Parse res_{id}_chunk_{order}
        parts = row_key.split("_")
        res_id = int(parts[1])
        chunk_order = int(parts[3])

        context_view = self.query_one("#search-context-view", Static)
        context_view.update("[yellow]Loading context...[/yellow]")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{BASE_URL}/search/{res_id}/context/{chunk_order}/",
                    timeout=10.0,
                )
            if response.status_code == 200:
                data = response.json()
                content = ["[bold]In Context[/bold]\n"]
                for chunk in data["chunks"]:
                    chunk_text = chunk["text"].strip()
                    if chunk["is_target"]:
                        # Highlight the target chunk
                        content.append(f"[reverse][bold]{chunk_text}[/bold][/reverse]")
                    else:
                        content.append(chunk_text)
                    content.append("\n" + "-" * 20 + "\n")

                context_view.update("\n".join(content))
            else:
                context_view.update(
                    f"[red]Error loading context: {response.text}[/red]"
                )
        except Exception:
            logger.exception("Context API error")
            context_view.update("[red]Error loading context. Check logs.[/red]")


class ResearchKBApp(App):
    """Research Knowledge Base TUI."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-container {
        height: 1fr;
    }

    #welcome {
        content-align: center middle;
        height: 1fr;
    }

    #command-input {
        dock: bottom;
        margin: 0 1;
    }

    #chat-resource-label {
        padding: 1;
        background: $surface;
        text-style: bold;
    }

    #chat-messages {
        height: 1fr;
        padding: 1;
    }

    #chat-input {
        dock: bottom;
        margin: 0 1;
    }

    .user-msg {
        padding: 0 1;
        margin: 0 0 0 4;
        color: $text;
    }

    .ai-msg {
        padding: 0 1;
        margin: 0 4 0 0;
        color: $success;
    }

    #chat-resource-summary-container {
        height: auto;
        max-height: 10;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $accent;
    }

    #chat-resource-summary {
        color: $text-muted;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        padding: 0 1;
    }

    #resource-list {
        height: 1fr;
        padding: 1;
    }

    .form-container {
        padding: 1 2;
    }

    .form-container Label {
        margin: 1 0 0 0;
    }

    .form-container Input {
        margin: 0 0 1 0;
    }
    
    /* Resource Details Split Layout */
    .details-header {
        padding: 1;
        background: $surface;
        text-style: bold;
    }
    
    #details-container {
        height: 1fr;
    }
    
    #details-left {
        width: 1fr;
        height: 1fr;
        padding: 1;
        border-right: solid $accent;
    }
    
    #details-right {
        width: 1fr;
        height: 1fr;
        padding: 1;
    }
    
    /* Semantic Search Layout */
    #semantic-search-input {
        margin: 1;
    }
    
    #semantic-search-results {
        height: 1fr;
    }

    #search-split-container {
        height: 1fr;
        margin: 0 1 1 1;
    }

    #search-left {
        width: 1fr;
        height: 1fr;
        border-right: solid $accent;
    }

    #search-right {
        width: 1fr;
        height: 1fr;
        padding: 1;
    }

    #search-context-view {
        width: 100%;
    }

    #autocomplete-popup {
        dock: bottom;
        layer: overlay;
        width: auto;
        max-width: 60;
        height: auto;
        max-height: 10;
        margin: 0 1;
        padding: 0;
        border: solid $accent;
        background: $surface;
        display: none;
    }

    #autocomplete-popup OptionList {
        height: auto;
        max-height: 8;
        background: $surface;
        border: none;
    }

    #autocomplete-popup OptionList:focus {
        border: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("escape", "escape", "Cancel/Back"),
        Binding("up", "move_up", "Move Up", show=False),
        Binding("down", "move_down", "Move Down", show=False),
    ]

    TITLE = "Research Knowledge Base"

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        # Configure Textual logging to file
        self._setup_textual_logging()

        command_input = self.query_one("#command-input", Input)
        command_input.display = False
        self._show_message(
            "[bold]Running system checks...[/bold]\nConnecting to backend server..."
        )
        self.set_timer(0.1, self._run_startup_checks)

    def _setup_textual_logging(self) -> None:
        """Configure Textual logging to write to a file."""
        # Try environment-based configuration first
        log_file = setup_from_env()

        if log_file:
            logger.info(f"Textual logging configured from environment to: {log_file}")
        else:
            # Use default configuration
            log_file = setup_textual_logging()
            from kb.tui_logging_config import setup_exception_logging

            setup_exception_logging()
            logger.info(f"Textual logging configured to: {log_file}")

    def _run_startup_checks(self) -> None:
        """Run all startup checks."""
        if not self._check_backend_server():
            return
        self._check_default_llm()
        self._check_jina_api_key()
        self._check_embedding_model()

        try:
            container = self.query_one("#main-container", Container)
            if container.query("#welcome"):
                welcome = container.query_one("#welcome", Static)
                if "Running system checks" in str(welcome.render()):
                    self._show_welcome()
        except Exception:
            pass

    def _check_backend_server(self) -> bool:
        """Check if backend server is running."""
        try:
            httpx.get(f"{BASE_URL}/", timeout=1.0)
            return True
        except httpx.RequestError:
            self.exit(
                message="Error: Backend server is not running on localhost:8001.",
                return_code=1,
            )
            return False

    def _check_jina_api_key(self) -> None:
        """Check if JINA AI API key is configured."""
        try:
            # Get text extraction configs
            response = httpx.get(f"{BASE_URL}/text-extraction-configs/", timeout=1.0)
            if response.status_code == 200:
                configs = response.json()
                jina_config = next(
                    (c for c in configs if c["title"] == "JINA AI API"), None
                )
                if jina_config:
                    # Check if secret exists
                    secret_response = httpx.get(
                        f"{BASE_URL}/text-extraction-configs/{jina_config['id']}/secret/",
                        timeout=1.0,
                    )
                    if secret_response.status_code == 404:
                        self.notify(
                            "JINA AI API key not configured! Please use /text-extraction-configs to add it.",
                            severity="warning",
                            timeout=10.0,
                        )
        except Exception as e:
            logger.exception(
                "Could not connect to backend to check Text Extraction configs"
            )
            self.notify(
                f"Could not connect to backend to check Text Extraction configs: {e}",
                severity="error",
                timeout=5.0,
            )

    def _check_default_llm(self) -> None:
        """Check if a default LLM is configured."""
        try:
            response = httpx.get(f"{BASE_URL}/llm-configs/", timeout=1.0)
            if response.status_code == 200:
                configs = response.json()
                has_default = any(c["is_default"] for c in configs)
                if not has_default:
                    self.notify(
                        "No default LLM configured! Please use the /llm-configs command to configure one.",
                        severity="warning",
                        timeout=10.0,
                    )
        except Exception as e:
            logger.exception("Could not connect to backend to check LLM configuration")
            self.notify(
                f"Could not connect to backend to check LLM configuration: {e}",
                severity="error",
                timeout=5.0,
            )

    def _check_embedding_model(self) -> None:
        """Check if the embedding model is running and loaded."""
        try:
            response = httpx.get(f"{BASE_URL}/embedding-configs/status/", timeout=1.0)
            if response.status_code == 200:
                data = response.json()
                if not isinstance(data, dict):
                    self.notify(
                        "Embedding status check returned unexpected format.",
                        severity="warning",
                        timeout=10.0,
                    )
                    return
                if not data.get("is_valid"):
                    self.notify(
                        f"Embedding Provider Issue: {data.get('message', 'Unknown error')}",
                        severity="warning",
                        timeout=10.0,
                    )
            else:
                self.notify(
                    f"Could not check embedding status: {response.text}",
                    severity="error",
                    timeout=5.0,
                )
        except Exception as e:
            logger.exception("Could not connect to backend to check embedding status")
            self.notify(
                f"Could not connect to backend to check embedding status: {e}",
                severity="error",
                timeout=5.0,
            )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(
                "[bold]Welcome to Research Knowledge Base[/bold]\n\n"
                "Loading commands...",
                id="welcome",
            ),
            id="main-container",
        )
        yield Input(placeholder="Enter command (start with /)...", id="command-input")
        # Autocomplete popup (hidden by default)
        yield Container(
            OptionList(id="autocomplete-options"),
            id="autocomplete-popup",
        )
        yield Footer()

    def action_escape(self) -> None:
        """Handle the escape key to return to the main view."""
        # First, check if autocomplete popup is open and close it
        if self._close_autocomplete():
            return

        container = self.query_one("#main-container", Container)

        # Check if we are currently in form, chat, etc.
        # Welcome view contains #welcome
        if not container.query("#welcome"):
            self._show_welcome()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command input and form submissions."""
        input_id = event.input.id

        # Route form submissions
        if input_id == "add-type":
            await self._handle_add_resource()
            return
        elif input_id == "llm-api-key":
            await self._handle_llm_configs()
            return
        elif input_id == "jina-api-key":
            self._handle_text_extraction_configs()
            return
        elif input_id == "kg-active":
            self._handle_kg_configs()
            return
        elif input_id != "command-input":
            return

        # If autocomplete is open, commit the highlighted suggestion before resolving.
        self._apply_autocomplete_selection()
        self._close_autocomplete()

        command = event.input.value.strip()
        event.input.value = ""

        if not command:
            return

        cmd, canonical, args = _resolve_command(command)

        if cmd is None:
            # Check if it's a bare command (no leading slash)
            if not command.startswith("/"):
                self._show_message(
                    f"[red]Unknown command: {canonical}[/red]\n\n"
                    "Commands must start with a forward slash (e.g., /help).\n"
                    "Type /help for a list of available commands."
                )
            else:
                self._show_message(
                    f"[red]Unknown command: {canonical}[/red]\n"
                    "Type /help for a list of available commands."
                )
            return

        # Execute the command handler
        result = cmd.handler(self, args or "")
        if result is not None:
            await result

    def _show_message(self, text: str) -> None:
        container = self.query_one("#main-container", Container)
        try:
            welcome = container.query_one("#welcome", Static)
            welcome.update(text)
        except Exception:
            logger.exception("Error updating welcome message")
            container.remove_children()
            container.mount(Static(text, id="welcome"))

    def _show_welcome(self) -> None:
        """Show the welcome/help screen with commands from the registry."""
        self._show_message(_format_help_text())
        command_input = self.query_one("#command-input", Input)
        command_input.display = True
        command_input.focus()

    # ---- Add Resource ----

    def _show_add_resource(self) -> None:
        self.query_one("#command-input", Input).display = False
        container = self.query_one("#main-container", Container)
        container.remove_children()
        container.mount(
            Container(
                Label("[bold]Add a New Resource[/bold]"),
                Label("URL:"),
                Input(placeholder="https://example.com/paper.pdf", id="add-url"),
                Label("Type (paper / blog_post):"),
                Input(placeholder="paper", id="add-type"),
                Label("Press Enter on Type field to submit"),
                classes="form-container",
            )
        )

        # Set up handler for when type field is submitted
        type_input = self.query_one("#add-type", Input)
        type_input.focus()

    async def _handle_add_resource(self) -> None:
        url_input = self.query_one("#add-url", Input)
        type_input = self.query_one("#add-type", Input)
        url = url_input.value.strip()
        resource_type = type_input.value.strip() or "paper"

        if not url:
            self._show_message("[red]URL is required[/red]")
            return

        self._show_message(f"[yellow]Adding resource from {url}...[/yellow]")

        try:
            from kb.schemas import ResourceIn, ResourceStreamUpdate
            import json

            payload = ResourceIn(url=url, resource_type=resource_type)
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{BASE_URL}/resources/",
                    json=payload.dict(),
                    timeout=60.0,
                ) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            try:
                                update_data = json.loads(line)
                                update = ResourceStreamUpdate(**update_data)

                                if update.type == "status":
                                    self._show_message(
                                        f"[yellow]{update.status}[/yellow]"
                                    )
                                elif update.type == "result" and update.resource:
                                    self.notify(
                                        f"Resource added!\n"
                                        f"ID: {update.resource.id}\n"
                                        f"Title: {update.resource.title or 'Extracting title...'}\n"
                                        f"URL: {update.resource.url}\n"
                                        f"Type: {update.resource.resource_type}\n"
                                        f"Text length: {len(update.resource.extracted_text or '')}",
                                        title="Success",
                                        severity="information",
                                    )
                                    self._show_welcome()
                            except Exception as parse_e:
                                logger.error(
                                    f"Failed to parse stream line: {line} - {parse_e}"
                                )
                    else:
                        error_text = await response.aread()
                        self._show_message(f"[red]Error: {error_text.decode()}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- List Resources ----

    def _list_resources(self) -> None:
        try:
            response = httpx.get(f"{BASE_URL}/resources/", timeout=5.0)
            if response.status_code == 200:
                resources = response.json()
                if not resources:
                    self._show_message(
                        "No resources found. Use /resource-add to add one."
                    )
                    return

                lines = ["[bold]Resources:[/bold]\n"]
                for r in resources:
                    title = r.get("title") or "No Title"
                    lines.append(
                        f"  [bold]{r['id']}[/bold] | {r['resource_type']} | {title} | {r['url']}"
                    )
                lines.append("\nUse /chat-start <id> to chat with a resource.")
                self._show_message("\n".join(lines))
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- Resource Details ----

    def _show_resource_details(self, resource_id_str: str) -> None:
        if not resource_id_str:
            self._show_message(
                "[red]Usage: /resource-details <resource_id> (or /rd <resource_id>)[/red]\n"
                "Use /resource-list to see available resources."
            )
            return

        try:
            resource_id = int(resource_id_str)
        except ValueError:
            self._show_message("[red]Invalid resource ID. Must be a number.[/red]")
            return

        try:
            response = httpx.get(f"{BASE_URL}/resources/{resource_id}/", timeout=10.0)
            if response.status_code == 200:
                self.query_one("#command-input", Input).display = False
                resource = response.json()
                container = self.query_one("#main-container", Container)
                container.remove_children()
                details_screen = ResourceDetailsScreen(resource)
                container.mount(details_screen)

                # focus the container to allow scrolling immediately
                self.call_after_refresh(lambda: container.focus())
            elif response.status_code == 404:
                self._show_message(
                    f"[red]Resource {resource_id} not found.[/red]\n"
                    "Use /list to see available resources."
                )
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- List Chats ----

    def _list_chats(self) -> None:
        try:
            response = httpx.get(f"{BASE_URL}/chat/", timeout=5.0)
            if response.status_code == 200:
                chats = response.json()
                if not chats:
                    self._show_message(
                        "No chats found. Use /chat <resource_id> to start one."
                    )
                    return

                lines = ["[bold]Existing Chats:[/bold]\n"]
                for c in chats:
                    # Truncate last message for display
                    last_msg = c["last_message"].replace("\n", " ")
                    if len(last_msg) > 50:
                        last_msg = last_msg[:47] + "..."

                    title = c.get("resource_title") or "No Title"
                    lines.append(
                        f"  [bold]ID: {c['id']}[/bold] | Res ID: {c['resource_id']} | {title} ({c['resource_url']})\n"
                        f"    [italic]{last_msg}[/italic]"
                    )
                lines.append("\nUse /continue <chat_id> to resume a chat.")
                lines.append("Use /chat <resource_id> to start a new chat.")
                self._show_message("\n".join(lines))
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- Chat with Resource ----

    def _start_chat(self, resource_id_str: str) -> None:
        if not resource_id_str:
            self._show_message(
                "[red]Usage: /chat <resource_id>[/red]\n"
                "Use /list to see available resources."
            )
            return

        # Check if LLM is configured
        try:
            response = httpx.get(f"{BASE_URL}/llm-configs/", timeout=10.0)
            if response.status_code == 200:
                configs = response.json()
                has_default = any(c["is_default"] for c in configs)
                if not has_default:
                    self._show_message(
                        "[red]No default LLM configured![/red]\n\n"
                        "You must configure an LLM before chatting.\n"
                        "Use /llm-configs to configure one."
                    )
                    return
        except Exception as e:
            logger.exception("Error checking LLM config before chat")
            self._show_message(f"[red]Error checking LLM config: {e}[/red]")
            return

        try:
            resource_id = int(resource_id_str)
        except ValueError:
            self._show_message("[red]Invalid resource ID. Must be a number.[/red]")
            return

        # Get resource details
        try:
            response = httpx.get(f"{BASE_URL}/resources/{resource_id}/", timeout=10.0)
            if response.status_code == 200:
                self.query_one("#command-input", Input).display = False
                resource = response.json()
                container = self.query_one("#main-container", Container)
                container.remove_children()
                chat_screen = ResourceChatScreen(
                    resource_id=resource_id,
                    resource_url=resource["url"],
                    resource_title=resource.get("title"),
                    resource_summary=resource.get("summary"),
                )
                container.mount(chat_screen)
                # Focus the chat input
                chat_input = self.query_one("#chat-input", Input)
                chat_input.focus()
            elif response.status_code == 404:
                self._show_message(
                    f"[red]Resource {resource_id} not found.[/red]\n"
                    "Use /list to see available resources."
                )
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- Continue Chat ----

    def _continue_chat(self, chat_id_str: str) -> None:
        if not chat_id_str:
            self._show_message(
                "[red]Usage: /continue <chat_id>[/red]\n"
                "Use /chat-list to see existing chats."
            )
            return

        try:
            chat_id = int(chat_id_str)
        except ValueError:
            self._show_message("[red]Invalid chat ID. Must be a number.[/red]")
            return

        # Check if LLM is configured
        try:
            response = httpx.get(f"{BASE_URL}/llm-configs/", timeout=10.0)
            if response.status_code == 200:
                configs = response.json()
                has_default = any(c["is_default"] for c in configs)
                if not has_default:
                    self._show_message(
                        "[red]No default LLM configured![/red]\n\n"
                        "You must configure an LLM before chatting.\n"
                        "Use /llm-configs to configure one."
                    )
                    return
        except Exception as e:
            logger.exception("Error checking LLM config before chat")
            self._show_message(f"[red]Error checking LLM config: {e}[/red]")
            return

        # Find chat details to get resource_id and resource_url
        try:
            response = httpx.get(f"{BASE_URL}/chat/", timeout=10.0)
            if response.status_code == 200:
                chats = response.json()
                chat = next((c for c in chats if c["id"] == chat_id), None)
                if chat:
                    self.query_one("#command-input", Input).display = False
                    container = self.query_one("#main-container", Container)
                    container.remove_children()
                    chat_screen = ResourceChatScreen(
                        resource_id=chat["resource_id"],
                        resource_url=chat["resource_url"],
                        resource_title=chat.get("resource_title"),
                        resource_summary=chat.get("resource_summary"),
                        chat_id=chat_id,
                    )
                    container.mount(chat_screen)
                    # Focus the chat input
                    chat_input = self.query_one("#chat-input", Input)
                    chat_input.focus()
                else:
                    self._show_message(
                        f"[red]Chat {chat_id} not found.[/red]\n"
                        "Use /chat-list to see available chats."
                    )
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- Semantic Search ----

    def _show_semantic_search(self) -> None:
        self.query_one("#command-input", Input).display = False
        container = self.query_one("#main-container", Container)
        container.remove_children()

        # Check if LLM / Embedding is configured for search
        try:
            response = httpx.get(f"{BASE_URL}/embedding-configs/status/", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if not data["is_valid"]:
                    self._show_message(
                        f"[red]Cannot perform semantic search: {data['message']}[/red]"
                    )
                    return
        except Exception as e:
            logger.exception("Error checking embedding config before search")
            self._show_message(f"[red]Error checking embedding status: {e}[/red]")

        search_screen = SemanticSearchScreen()
        container.mount(search_screen)

        # Focus the search input field
        self.call_after_refresh(
            lambda: self.query_one("#semantic-search-input", Input).focus()
        )

    # ---- LLM Configs ----

    def _show_llm_configs(self) -> None:
        self.query_one("#command-input", Input).display = False
        container = self.query_one("#main-container", Container)
        container.remove_children()

        # First show existing LLM configs
        configs_info = "[bold]Existing LLM Configurations:[/bold]\n\n"
        try:
            response = httpx.get(f"{BASE_URL}/llm-configs/", timeout=10.0)
            if response.status_code == 200:
                configs = response.json()
                if configs:
                    for c in configs:
                        default_marker = " (DEFAULT)" if c.get("is_default") else ""
                        configs_info += f"  - {c.get('name')} [{c.get('provider')}/{c.get('model_name')}]{default_marker}\n"
                else:
                    configs_info += "  [yellow]No configurations found.[/yellow]\n"
        except Exception:
            logger.exception("Could not fetch configurations")
            configs_info += "  [red]Could not fetch configurations.[/red]\n"

        container.mount(
            Container(
                Label(configs_info),
                Label(
                    "\n[bold]Setup Default LLM[/bold]\n[italic]This LLM will be used for all chats by default.\nYou can later use different models for different purposes.[/italic]"
                ),
                Label("Provider (e.g. openai, ollama, groq, openrouter):"),
                Input(placeholder="openai", id="llm-provider"),
                Label(
                    "Model name (e.g. groq/llama-3.1-8b-instant, ollama_chat/qwen3:4b, lm_studio/<model_name>, openai/gpt-4o):\nFor more info see: https://docs.litellm.ai/docs/#basic-usage"
                ),
                Input(placeholder="ollama_chat/qwen3:4b", id="llm-model"),
                Label("API Key (optional):"),
                Input(placeholder="sk-...", id="llm-api-key", password=True),
                Label("Press Enter on API Key field to submit"),
                classes="form-container",
            )
        )

    async def _handle_llm_configs(self) -> None:
        provider_input = self.query_one("#llm-provider", Input)
        model_input = self.query_one("#llm-model", Input)
        api_key_input = self.query_one("#llm-api-key", Input)

        provider = provider_input.value.strip() or "openai"
        model_name = model_input.value.strip()
        api_key = api_key_input.value.strip()

        if not model_name:
            self._show_message("[red]Model name is required.[/red]")
            return

        self._show_message(
            "[yellow]Please wait while I test the LLM connection!...[/yellow]"
        )

        try:
            from kb.schemas import DefaultLLMConfigIn

            from kb.services.llm import LLMProvider

            try:
                provider_enum = LLMProvider(provider)
            except ValueError:
                self._show_message(f"[red]Unknown provider: {provider}[/red]")
                return

            payload = DefaultLLMConfigIn(
                model_name=model_name,
                provider=provider_enum,
                api_key=api_key if api_key else None,
            )
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{BASE_URL}/llm-configs/default/",
                    json=payload.dict(),
                    timeout=5.0,
                )
            if response.status_code == 200:
                data = response.json()
                test_output = data.get("test_response") or "No response"
                self.notify(
                    f"LLM configured!\n"
                    f"Name: {data['name']}\n"
                    f"Provider: {data['provider']}\n"
                    f"Model: {data['model_name']}\n"
                    f"Default: {data['is_default']}\n"
                    f"Test Response: {test_output}",
                    title="Success",
                    severity="information",
                )
                self._show_welcome()
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- Text Extraction Configs ----

    def _show_text_extraction_configs(self) -> None:
        self.query_one("#command-input", Input).display = False
        container = self.query_one("#main-container", Container)
        container.remove_children()

        configs_info = "[bold]Text Extraction Configurations:[/bold]\n\n"
        jina_config_id = None
        jina_configured = False

        try:
            response = httpx.get(f"{BASE_URL}/text-extraction-configs/", timeout=10.0)
            if response.status_code == 200:
                configs = response.json()
                if configs:
                    for c in configs:
                        configs_info += f"  - {c.get('title')}\n"
                        if c.get("title") == "JINA AI API":
                            jina_config_id = c.get("id")
                else:
                    configs_info += "  [yellow]No configurations found.[/yellow]\n"

                # Check secret for JINA AI API
                if jina_config_id is not None:
                    sec_response = httpx.get(
                        f"{BASE_URL}/text-extraction-configs/{jina_config_id}/secret/",
                        timeout=10.0,
                    )
                    if sec_response.status_code == 200:
                        jina_configured = True
                        configs_info += (
                            "\n[green]JINA AI API Key is configured.[/green]\n"
                        )

        except Exception:
            logger.exception("Could not fetch configurations")
            configs_info += "  [red]Could not fetch configurations.[/red]\n"

        self._jina_config_id = jina_config_id

        if not jina_configured and jina_config_id is not None:
            container.mount(
                Container(
                    Label(configs_info),
                    Label("\n[bold]Configure JINA AI API[/bold]"),
                    Label(
                        "Please provide your API key. Get a free API key at: https://jina.ai/reader/"
                    ),
                    Input(placeholder="jina_...", id="jina-api-key", password=True),
                    Label("Press Enter on API Key field to submit"),
                    classes="form-container",
                )
            )

            # Focus
            def _focus_input():
                try:
                    self.query_one("#jina-api-key", Input).focus()
                except Exception:
                    logger.exception("Error focusing Jina API key input")
                    pass

            self.call_after_refresh(_focus_input)
        else:
            container.mount(
                Container(
                    Label(configs_info),
                    Label(
                        "\n[italic]All configurations are set. Press Escape to return.[/italic]"
                    ),
                    classes="form-container",
                )
            )

    def _handle_text_extraction_configs(self) -> None:
        """Handle text extraction configuration submission."""
        try:
            api_key_input = self.query_one("#jina-api-key", Input)
            api_key = api_key_input.value.strip()

            if not api_key:
                self._show_message("[red]API Key is required.[/red]")
                return

            if not getattr(self, "_jina_config_id", None):
                self._show_message("[red]JINA AI API config not found.[/red]")
                return

            from kb.schemas import SecretIn

            payload = SecretIn(title="JINA_API_KEY", value=api_key)

            response = httpx.post(
                f"{BASE_URL}/text-extraction-configs/{self._jina_config_id}/secret/",
                json=payload.dict(),
                timeout=10.0,
            )
            if response.status_code == 200:
                self.notify(
                    "JINA AI API Key configured successfully!",
                    title="Success",
                    severity="information",
                )
                self._show_welcome()
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")

        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- Knowledge Graph Configs ----

    def _show_kg_configs(self) -> None:
        self.query_one("#command-input", Input).display = False
        container = self.query_one("#main-container", Container)
        container.remove_children()

        configs_info = "[bold]Knowledge Graph Configurations:[/bold]\n\n"

        try:
            response = httpx.get(f"{BASE_URL}/kg-configs/", timeout=10.0)
            if response.status_code == 200:
                configs = response.json()
                if configs:
                    for config in configs:
                        active_marker = " (ACTIVE)" if config.get("is_active") else ""
                        configs_info += (
                            f"  - {config.get('name')} "
                            f"[{config.get('package_name')} | {config.get('update_trigger')}]"
                            f"{active_marker}\n"
                        )
                else:
                    configs_info += "  [yellow]No configurations found.[/yellow]\n"
            else:
                configs_info += f"  [red]Error: {response.text}[/red]\n"
        except Exception:
            logger.exception("Could not fetch knowledge graph configurations")
            configs_info += "  [red]Could not fetch configurations.[/red]\n"

        container.mount(
            Container(
                Label(configs_info),
                Label("\n[bold]Create Knowledge Graph Config[/bold]"),
                Label("Name:"),
                Input(placeholder="Primary KG", id="kg-name"),
                Label("Package name:"),
                Input(placeholder="django_lightrag", id="kg-package-name"),
                Label("Update trigger (always / llm_intent):"),
                Input(placeholder="always", id="kg-update-trigger"),
                Label("Active? (true / false):"),
                Input(placeholder="false", id="kg-active"),
                Label("Press Enter on Active field to submit"),
                classes="form-container",
            )
        )

        self.call_after_refresh(lambda: self.query_one("#kg-name", Input).focus())

    def _handle_kg_configs(self) -> None:
        name_input = self.query_one("#kg-name", Input)
        package_name_input = self.query_one("#kg-package-name", Input)
        update_trigger_input = self.query_one("#kg-update-trigger", Input)
        active_input = self.query_one("#kg-active", Input)

        name = name_input.value.strip()
        package_name = package_name_input.value.strip() or "django_lightrag"
        update_trigger = update_trigger_input.value.strip() or "always"
        active_raw = active_input.value.strip().lower() or "false"

        if not name:
            self._show_message("[red]Name is required.[/red]")
            return

        if update_trigger not in {"always", "llm_intent"}:
            self._show_message(
                "[red]Update trigger must be 'always' or 'llm_intent'.[/red]"
            )
            return

        if active_raw not in {"true", "false"}:
            self._show_message("[red]Active must be 'true' or 'false'.[/red]")
            return

        from kb.schemas import KnowledgeGraphConfigIn

        payload = KnowledgeGraphConfigIn(
            name=name,
            package_name=package_name,
            update_trigger=update_trigger,
            is_active=active_raw == "true",
        )

        try:
            response = httpx.post(
                f"{BASE_URL}/kg-configs/",
                json=payload.dict(),
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                self.notify(
                    f"Knowledge graph config saved!\n"
                    f"Name: {data['name']}\n"
                    f"Package: {data['package_name']}\n"
                    f"Trigger: {data['update_trigger']}\n"
                    f"Active: {data['is_active']}",
                    title="Success",
                    severity="information",
                )
                self._show_welcome()
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- Autocomplete Handling ----

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes for autocomplete."""
        if event.input.id != "command-input":
            return

        value = event.value.strip()

        # Only show autocomplete if we're typing a slash command (first token)
        if not value.startswith("/"):
            self._close_autocomplete()
            return

        # Check if there's a space (more than one token)
        if " " in value:
            self._close_autocomplete()
            return

        # Get suggestions
        suggestions = _get_command_suggestions(value)

        if not suggestions:
            self._close_autocomplete()
            return

        # Update and show the autocomplete popup
        self._show_autocomplete(suggestions)

    def _show_autocomplete(self, suggestions: list[Command]) -> None:
        """Show the autocomplete popup with suggestions."""
        try:
            popup = self.query_one("#autocomplete-popup", Container)
            option_list = self.query_one("#autocomplete-options", OptionList)

            # Clear and populate options
            option_list.clear_options()
            for cmd in suggestions:
                option_list.add_option(_format_suggestion(cmd))

            # Show the popup without stealing focus from the command input.
            # Users should be able to keep typing after "/" to refine the command.
            popup.display = True
        except Exception:
            logger.exception("Error showing autocomplete")

    def _close_autocomplete(self) -> bool:
        """Close the autocomplete popup. Returns True if it was open."""
        try:
            popup = self.query_one("#autocomplete-popup", Container)
            if popup.display:
                popup.display = False
                # Return focus to command input
                try:
                    cmd_input = self.query_one("#command-input", Input)
                    cmd_input.focus()
                except Exception:
                    pass
                return True
        except Exception:
            logger.exception("Error closing autocomplete")
        return False

    def action_move_up(self) -> None:
        """Handle up arrow - navigate autocomplete or normal behavior."""
        try:
            popup = self.query_one("#autocomplete-popup", Container)
            if popup.display:
                option_list = self.query_one("#autocomplete-options", OptionList)
                option_list.action_cursor_up()
                return
        except Exception:
            pass

    def action_move_down(self) -> None:
        """Handle down arrow - navigate autocomplete or normal behavior."""
        try:
            popup = self.query_one("#autocomplete-popup", Container)
            if popup.display:
                option_list = self.query_one("#autocomplete-options", OptionList)
                option_list.action_cursor_down()
                return
        except Exception:
            pass

    def _apply_autocomplete_selection(self) -> bool:
        """Apply the highlighted autocomplete suggestion to the command input."""
        try:
            popup = self.query_one("#autocomplete-popup", Container)
            if not popup.display:
                return False

            cmd_input = self.query_one("#command-input", Input)
            suggestions = _get_command_suggestions(cmd_input.value.strip())
            if not suggestions:
                return False

            option_list = self.query_one("#autocomplete-options", OptionList)
            highlighted = option_list.highlighted
            if highlighted is None:
                highlighted = 0

            if 0 <= highlighted < len(suggestions):
                selected_cmd = suggestions[highlighted]
                suffix = " " if selected_cmd.takes_argument else ""
                cmd_input.value = selected_cmd.name + suffix
                cmd_input.cursor_position = len(cmd_input.value)
                cmd_input.focus()
                return True
        except Exception:
            logger.exception("Error applying autocomplete selection")
        return False

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle selection from the autocomplete popup."""
        try:
            popup = self.query_one("#autocomplete-popup", Container)
            if not popup.display:
                return

            self._apply_autocomplete_selection()
            self._close_autocomplete()
        except Exception:
            logger.exception("Error handling autocomplete selection")


# ---- Command Registration ----

# Define command handlers as standalone functions that call app methods


def _cmd_help(app: ResearchKBApp, args: str) -> None:
    """Show help screen."""
    app._show_welcome()


def _cmd_add(app: ResearchKBApp, args: str) -> None:
    """Add a new resource."""
    app._show_add_resource()


def _cmd_list(app: ResearchKBApp, args: str) -> None:
    """List all resources."""
    app._list_resources()


def _cmd_details(app: ResearchKBApp, args: str) -> None:
    """Show resource details."""
    app._show_resource_details(args)


def _cmd_chats(app: ResearchKBApp, args: str) -> None:
    """List all chats."""
    app._list_chats()


def _cmd_chat(app: ResearchKBApp, args: str) -> None:
    """Start a new chat with a resource."""
    app._start_chat(args)


def _cmd_continue(app: ResearchKBApp, args: str) -> None:
    """Continue an existing chat."""
    app._continue_chat(args)


def _cmd_search(app: ResearchKBApp, args: str) -> None:
    """Semantic search across chunks."""
    app._show_semantic_search()


def _cmd_llm_configs(app: ResearchKBApp, args: str) -> None:
    """Configure LLM settings."""
    app._show_llm_configs()


def _cmd_text_extraction_configs(app: ResearchKBApp, args: str) -> None:
    """Configure text extraction settings."""
    app._show_text_extraction_configs()


def _cmd_kg_configs(app: ResearchKBApp, args: str) -> None:
    """Configure knowledge graph settings."""
    app._show_kg_configs()


# Register all commands
_register_command(
    Command(
        name="/help",
        aliases=["/h"],
        usage="/help",
        description="Show this help message",
        takes_argument=False,
        handler=_cmd_help,
    )
)

_register_command(
    Command(
        name="/resource-add",
        aliases=["/ra"],
        usage="/resource-add",
        description="Add a new resource",
        takes_argument=False,
        handler=_cmd_add,
    )
)

_register_command(
    Command(
        name="/resource-list",
        aliases=["/rl"],
        usage="/resource-list",
        description="List all resources",
        takes_argument=False,
        handler=_cmd_list,
    )
)

_register_command(
    Command(
        name="/resource-details",
        aliases=["/rd"],
        usage="/resource-details <resource_id>",
        description="Show details of a resource",
        takes_argument=True,
        handler=_cmd_details,
    )
)

_register_command(
    Command(
        name="/chat-list",
        aliases=["/cl"],
        usage="/chat-list",
        description="List all chats",
        takes_argument=False,
        handler=_cmd_chats,
    )
)

_register_command(
    Command(
        name="/chat-start",
        aliases=["/cs"],
        usage="/chat-start <resource_id>",
        description="Start a NEW chat with a resource",
        takes_argument=True,
        handler=_cmd_chat,
    )
)

_register_command(
    Command(
        name="/chat-continue",
        aliases=["/cc"],
        usage="/chat-continue <chat_id>",
        description="Continue an existing chat",
        takes_argument=True,
        handler=_cmd_continue,
    )
)

_register_command(
    Command(
        name="/search",
        aliases=["/ss"],
        usage="/search",
        description="Semantic search across chunks",
        takes_argument=False,
        handler=_cmd_search,
    )
)

_register_command(
    Command(
        name="/llm-configs",
        aliases=["/lc"],
        usage="/llm-configs",
        description="Configure LLM settings",
        takes_argument=False,
        handler=_cmd_llm_configs,
    )
)

_register_command(
    Command(
        name="/text-extraction-configs",
        aliases=["/tec"],
        usage="/text-extraction-configs",
        description="Configure text extraction settings",
        takes_argument=False,
        handler=_cmd_text_extraction_configs,
    )
)

_register_command(
    Command(
        name="/kg-configs",
        aliases=["/kgc"],
        usage="/kg-configs",
        description="Configure knowledge graph settings",
        takes_argument=False,
        handler=_cmd_kg_configs,
    )
)
