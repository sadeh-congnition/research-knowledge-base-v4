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
    ]

    TITLE = "Research Knowledge Base"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(
                "[bold]Welcome to Research Knowledge Base[/bold]\n\n"
                "Commands:\n"
                "  [bold]add[/bold]       - Add a new resource\n"
                "  [bold]list[/bold]      - List all resources\n"
                "  [bold]chat <id>[/bold] - Chat with a resource\n"
                "  [bold]setup-llm[/bold] - Configure default LLM\n"
                "  [bold]add-key[/bold]   - Add an API key / secret\n"
                "  [bold]help[/bold]      - Show this help\n",
                id="welcome",
            ),
            id="main-container",
        )
        yield Input(placeholder="Enter command...", id="command-input")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command input and form submissions."""
        input_id = event.input.id

        # Route form submissions
        if input_id == "add-type":
            self._handle_add_resource()
            return
        elif input_id == "llm-secret-id":
            self._handle_setup_llm()
            return
        elif input_id == "key-value":
            self._handle_add_key()
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
        elif cmd == "chat":
            self._start_chat(args)
        elif cmd == "setup-llm":
            self._show_setup_llm()
        elif cmd == "add-key":
            self._show_add_key()
        else:
            self._show_message(f"Unknown command: {cmd}. Type 'help' for commands.")

    def _show_message(self, text: str) -> None:
        container = self.query_one("#main-container", Container)
        container.remove_children()
        container.mount(Static(text, id="welcome"))

    def _show_welcome(self) -> None:
        self._show_message(
            "[bold]Welcome to Research Knowledge Base[/bold]\n\n"
            "Commands:\n"
            "  [bold]add[/bold]       - Add a new resource\n"
            "  [bold]list[/bold]      - List all resources\n"
            "  [bold]chat <id>[/bold] - Chat with a resource\n"
            "  [bold]setup-llm[/bold] - Configure default LLM\n"
            "  [bold]add-key[/bold]   - Add an API key / secret\n"
            "  [bold]help[/bold]      - Show this help\n"
        )

    # ---- Add Resource ----

    def _show_add_resource(self) -> None:
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
                self._show_message(
                    f"[green]✓ Resource added![/green]\n"
                    f"  ID: {data['id']}\n"
                    f"  URL: {data['url']}\n"
                    f"  Type: {data['resource_type']}\n"
                    f"  Text length: {len(data.get('extracted_text', ''))}"
                )
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
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
                        "Use 'setup-llm' to configure one.\n"
                        "Use 'add-key' to add an API key first if needed."
                    )
                    return

                # Check that the default config has a secret
                default_config = next(c for c in configs if c["is_default"])
                if default_config.get("secret_id") is None:
                    self._show_message(
                        "[red]Default LLM has no API key![/red]\n\n"
                        "Use 'add-key' to add a secret, then 'setup-llm' to "
                        "link it to your LLM config."
                    )
                    return
        except Exception as e:
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
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- Setup LLM Config ----

    def _show_setup_llm(self) -> None:
        container = self.query_one("#main-container", Container)
        container.remove_children()

        # First show existing secrets to reference
        secrets_info = ""
        try:
            response = httpx.get(f"{BASE_URL}/secrets/", timeout=10.0)
            if response.status_code == 200:
                secrets = response.json()
                if secrets:
                    secrets_info = "\n[bold]Available Secrets:[/bold]\n"
                    for s in secrets:
                        secrets_info += f"  ID {s['id']}: {s['title']}\n"
                else:
                    secrets_info = (
                        "\n[yellow]No secrets found. Use 'add-key' first.[/yellow]\n"
                    )
        except Exception:
            pass

        container.mount(
            Container(
                Label(f"[bold]Setup Default LLM[/bold]{secrets_info}"),
                Label("Config name:"),
                Input(placeholder="my-llm", id="llm-name"),
                Label("Model name (e.g. ollama_chat/qwen3:4b):"),
                Input(placeholder="ollama_chat/qwen3:4b", id="llm-model"),
                Label("Secret ID (for API key):"),
                Input(placeholder="1", id="llm-secret-id"),
                Label("Press Enter on Secret ID field to submit"),
                classes="form-container",
            )
        )

    def _handle_setup_llm(self) -> None:
        name_input = self.query_one("#llm-name", Input)
        model_input = self.query_one("#llm-model", Input)
        secret_id_input = self.query_one("#llm-secret-id", Input)

        name = name_input.value.strip()
        model_name = model_input.value.strip()
        secret_id_str = secret_id_input.value.strip()

        if not name or not model_name:
            self._show_message("[red]Name and model are required.[/red]")
            return

        secret_id = int(secret_id_str) if secret_id_str else None

        try:
            from kb.schemas import LLMConfigIn

            payload = LLMConfigIn(
                name=name,
                model_name=model_name,
                is_default=True,
                secret_id=secret_id,
            )
            response = httpx.post(
                f"{BASE_URL}/llm-configs/",
                json=payload.dict(),
                timeout=30.0,
            )
            if response.status_code == 200:
                data = response.json()
                self._show_message(
                    f"[green]✓ LLM configured![/green]\n"
                    f"  Name: {data['name']}\n"
                    f"  Model: {data['model_name']}\n"
                    f"  Default: {data['is_default']}"
                )
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            self._show_message(f"[red]Error: {e}[/red]")

    # ---- Add API Key / Secret ----

    def _show_add_key(self) -> None:
        container = self.query_one("#main-container", Container)
        container.remove_children()
        container.mount(
            Container(
                Label("[bold]Add API Key / Secret[/bold]"),
                Label("Title (e.g. JINA_API_KEY, OPENAI_API_KEY):"),
                Input(placeholder="OPENAI_API_KEY", id="key-title"),
                Label("Value (the API key):"),
                Input(placeholder="sk-...", id="key-value", password=True),
                Label("Press Enter on Value field to submit"),
                classes="form-container",
            )
        )

    def _handle_add_key(self) -> None:
        title_input = self.query_one("#key-title", Input)
        value_input = self.query_one("#key-value", Input)

        title = title_input.value.strip()
        value = value_input.value.strip()

        if not title or not value:
            self._show_message("[red]Title and value are required.[/red]")
            return

        try:
            from kb.schemas import SecretIn

            payload = SecretIn(title=title, value=value)
            response = httpx.post(
                f"{BASE_URL}/secrets/",
                json=payload.dict(),
                timeout=30.0,
            )
            if response.status_code == 200:
                data = response.json()
                self._show_message(
                    f"[green]✓ Secret added![/green]\n"
                    f"  ID: {data['id']}\n"
                    f"  Title: {data['title']}"
                )
            else:
                self._show_message(f"[red]Error: {response.text}[/red]")
        except Exception as e:
            self._show_message(f"[red]Error: {e}[/red]")
