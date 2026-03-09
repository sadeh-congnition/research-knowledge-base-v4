from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    Static,
)

import httpx
from loguru import logger

BASE_URL = "http://localhost:8001/api"


class ChatMessage(Static):
    """A single chat message."""

    def __init__(self, text: str, is_user: bool = True) -> None:
        prefix = "You" if is_user else "AI"
        super().__init__(f"[bold]{prefix}:[/bold] {text}")
        self.add_class("user-msg" if is_user else "ai-msg")


class ResourceChatScreen(Container):
    """Chat interface for chatting with a resource."""

    def __init__(self, resource_id: int, resource_url: str) -> None:
        super().__init__()
        self.resource_id = resource_id
        self.resource_url = resource_url
        self.chat_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Label(
            f"[bold]Chatting with:[/bold] {self.resource_url}",
            id="chat-resource-label",
        )
        yield VerticalScroll(id="chat-messages")
        yield Input(placeholder="Type a message...", id="chat-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
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
                resource_id=self.resource_id,
                message=message,
            )
            response = httpx.post(
                f"{BASE_URL}/chat/",
                json=payload.dict(),
                timeout=120.0,
            )
            if response.status_code == 200:
                data = response.json()
                self.chat_id = data["chat_id"]
                messages_container.mount(
                    ChatMessage(data["ai_message"], is_user=False)
                )
            else:
                messages_container.mount(
                    ChatMessage(
                        f"Error: {response.json().get('error', response.text)}",
                        is_user=False,
                    )
                )
        except Exception as e:
            logger.exception("Error during chat message sending")
            messages_container.mount(ChatMessage(f"Error: {e}", is_user=False))

        messages_container.scroll_end()


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
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("escape", "escape", "Cancel/Back"),
    ]

    TITLE = "Research Knowledge Base"

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self._check_default_llm()
        self._check_jina_api_key()
        self._check_embedding_model()

    def _check_jina_api_key(self) -> None:
        """Check if JINA AI API key is configured."""
        try:
            # Get text extraction configs
            response = httpx.get(f"{BASE_URL}/text-extraction-configs/", timeout=10.0)
            if response.status_code == 200:
                configs = response.json()
                jina_config = next((c for c in configs if c["title"] == "JINA AI API"), None)
                if jina_config:
                    # Check if secret exists
                    secret_response = httpx.get(
                        f"{BASE_URL}/text-extraction-configs/{jina_config['id']}/secret/",
                        timeout=10.0
                    )
                    if secret_response.status_code == 404:
                        self.notify(
                            "JINA AI API key not configured! Please use 'text-extraction-configs' to add it.",
                            severity="warning",
                            timeout=10.0,
                        )
        except Exception as e:
            logger.exception("Could not connect to backend to check Text Extraction configs")
            self.notify(
                f"Could not connect to backend to check Text Extraction configs: {e}",
                severity="error",
                timeout=5.0,
            )

    def _check_default_llm(self) -> None:
        """Check if a default LLM is configured."""
        try:
            response = httpx.get(f"{BASE_URL}/llm-configs/", timeout=10.0)
            if response.status_code == 200:
                configs = response.json()
                has_default = any(c["is_default"] for c in configs)
                if not has_default:
                    self.notify(
                        "No default LLM configured! Please use the 'llm-configs' command to configure one.",
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
            response = httpx.get(f"{BASE_URL}/embedding-configs/status/", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if not data["is_valid"]:
                    self.notify(
                        f"Embedding Provider Issue: {data['message']}",
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
                "Commands:\n"
                "  [bold]add[/bold]       - Add a new resource\n"
                "  [bold]list[/bold]      - List all resources\n"
                "  [bold]chats[/bold]     - List all chats\n"
                "  [bold]chat <id>[/bold] - Chat with a resource\n"
                "  [bold]llm-configs[/bold] - LLM Configs\n"
                "  [bold]text-extraction-configs[/bold] - Text Extraction Configs\n"
                "  [bold]help[/bold]      - Show this help\n",
                id="welcome",
            ),
            id="main-container",
        )
        yield Input(placeholder="Enter command...", id="command-input")
        yield Footer()

    def action_escape(self) -> None:
        """Handle the escape key to return to the main view."""
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
            self._handle_add_resource()
            return
        elif input_id == "llm-api-key":
            await self._handle_llm_configs()
            return
        elif input_id == "jina-api-key":
            self._handle_text_extraction_configs()
            return
        elif input_id != "command-input":
            return

        command = event.value.strip()
        event.input.value = ""

        if not command:
            return

        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "help":
            self._show_welcome()
        elif cmd == "add":
            self._show_add_resource()
        elif cmd == "list":
            self._list_resources()
        elif cmd == "chats":
            self._list_chats()
        elif cmd == "chat":
            self._start_chat(args)
        elif cmd == "llm-configs":
            self._show_llm_configs()
        elif cmd == "text-extraction-configs":
            self._show_text_extraction_configs()
        else:
            self._show_message(f"Unknown command: {cmd}. Type 'help' for commands.")

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
        self._show_message(
            "[bold]Welcome to Research Knowledge Base[/bold]\n\n"
            "Commands:\n"
            "  [bold]add[/bold]       - Add a new resource\n"
            "  [bold]list[/bold]      - List all resources\n"
            "  [bold]chats[/bold]     - List all chats\n"
            "  [bold]chat <id>[/bold] - Chat with a resource\n"
            "  [bold]llm-configs[/bold] - LLM Configs\n"
            "  [bold]text-extraction-configs[/bold] - Text Extraction Configs\n"
            "  [bold]help[/bold]      - Show this help\n"
        )
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

    def _handle_add_resource(self) -> None:
        url_input = self.query_one("#add-url", Input)
        type_input = self.query_one("#add-type", Input)
        url = url_input.value.strip()
        resource_type = type_input.value.strip() or "paper"

        if not url:
            self._show_message("[red]URL is required[/red]")
            return

        self._show_message(f"[yellow]Adding resource from {url}...[/yellow]")

        try:
            from kb.schemas import ResourceIn

            payload = ResourceIn(url=url, resource_type=resource_type)
            response = httpx.post(
                f"{BASE_URL}/resources/",
                json=payload.dict(),
                timeout=120.0,
            )
            if response.status_code == 200:
                data = response.json()
                self.notify(
                    f"Resource added!\n"
                    f"ID: {data['id']}\n"
                    f"URL: {data['url']}\n"
                    f"Type: {data['resource_type']}\n"
                    f"Text length: {len(data.get('extracted_text', ''))}",
                    title="Success",
                    severity="information",
                )
                self._show_welcome()
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- List Resources ----

    def _list_resources(self) -> None:
        try:
            response = httpx.get(f"{BASE_URL}/resources/", timeout=30.0)
            if response.status_code == 200:
                resources = response.json()
                if not resources:
                    self._show_message("No resources found. Use 'add' to add one.")
                    return

                lines = ["[bold]Resources:[/bold]\n"]
                for r in resources:
                    lines.append(
                        f"  [bold]{r['id']}[/bold] | {r['resource_type']} | {r['url']}"
                    )
                lines.append("\nUse 'chat <id>' to chat with a resource.")
                self._show_message("\n".join(lines))
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- List Chats ----

    def _list_chats(self) -> None:
        try:
            response = httpx.get(f"{BASE_URL}/chat/", timeout=30.0)
            if response.status_code == 200:
                chats = response.json()
                if not chats:
                    self._show_message("No chats found. Use 'chat <resource_id>' to start one.")
                    return

                lines = ["[bold]Existing Chats:[/bold]\n"]
                for c in chats:
                    # Truncate last message for display
                    last_msg = c['last_message'].replace('\n', ' ')
                    if len(last_msg) > 50:
                        last_msg = last_msg[:47] + "..."
                    
                    lines.append(
                        f"  [bold]{c['id']}[/bold] | {c['resource_url']}\n"
                        f"    [italic]{last_msg}[/italic]"
                    )
                lines.append("\nUse 'chat <id>' (using resource ID) to start a new chat or continue.")
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
                "[red]Usage: chat <resource_id>[/red]\n"
                "Use 'list' to see available resources."
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
                        "Use 'llm-configs' to configure one."
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
            response = httpx.get(
                f"{BASE_URL}/resources/{resource_id}/", timeout=10.0
            )
            if response.status_code == 200:
                self.query_one("#command-input", Input).display = False
                resource = response.json()
                container = self.query_one("#main-container", Container)
                container.remove_children()
                chat_screen = ResourceChatScreen(
                    resource_id=resource_id, resource_url=resource["url"]
                )
                container.mount(chat_screen)
                # Focus the chat input
                chat_input = self.query_one("#chat-input", Input)
                chat_input.focus()
            elif response.status_code == 404:
                self._show_message(
                    f"[red]Resource {resource_id} not found.[/red]\n"
                    "Use 'list' to see available resources."
                )
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

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
                Label("\n[bold]Setup Default LLM[/bold]\n[italic]This LLM will be used for all chats by default.\nYou can later use different models for different purposes.[/italic]"),
                Label("Provider (e.g. openai, ollama, groq, openrouter):"),
                Input(placeholder="openai", id="llm-provider"),
                Label("Model name (e.g. groq/llama-3.1-8b-instant, ollama_chat/qwen3:4b, lm_studio/<model_name>, openai/gpt-4o):\nFor more info see: https://docs.litellm.ai/docs/#basic-usage"),
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

        self._show_message("[yellow]Please wait while I test the LLM connection!...[/yellow]")

        try:
            from kb.schemas import DefaultLLMConfigIn

            payload = DefaultLLMConfigIn(
                model_name=model_name,
                provider=provider,
                api_key=api_key if api_key else None,
            )
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{BASE_URL}/llm-configs/default/",
                    json=payload.dict(),
                    timeout=30.0,
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
                    severity="information"
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
                        timeout=10.0
                    )
                    if sec_response.status_code == 200:
                        jina_configured = True
                        configs_info += "\n[green]JINA AI API Key is configured.[/green]\n"

        except Exception:
            logger.exception("Could not fetch configurations")
            configs_info += "  [red]Could not fetch configurations.[/red]\n"

        self._jina_config_id = jina_config_id

        if not jina_configured and jina_config_id is not None:
            container.mount(
                Container(
                    Label(configs_info),
                    Label("\n[bold]Configure JINA AI API[/bold]"),
                    Label("Please provide your API key. Get a free API key at: https://jina.ai/reader/"),
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
                    Label("\n[italic]All configurations are set. Press Escape to return.[/italic]"),
                    classes="form-container"
                )
            )

    def _handle_text_extraction_configs(self) -> None:
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
                    severity="information"
                )
                self._show_welcome()
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")

        except Exception as e:
            logger.exception("An error occurred")
            self._show_message(f"[red]Error: {e}[/red]")

