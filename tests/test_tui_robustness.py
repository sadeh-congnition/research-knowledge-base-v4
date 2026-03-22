import pytest
from textual.widgets import Static, Label, Input, OptionList
from kb.tui.app import ResearchKBApp, _get_command_suggestions
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_httpx():
    with patch("httpx.get") as mock_get:
        # Determine what to return based on the URL being called
        def side_effect(*args, **kwargs):
            url = args[0]
            resp = MagicMock(status_code=200)
            if "embedding-configs" in url:
                resp.json.return_value = {"is_valid": True, "message": "OK"}
            else:
                resp.json.return_value = []
            return resp

        mock_get.side_effect = side_effect
        yield mock_get


async def test_show_message_robustness(mock_httpx):
    """Test that _show_message can be called multiple times without DuplicateIds error."""
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        # Initial message
        app._show_message("First message")
        await pilot.pause()

        # Second message (should update existing)
        app._show_message("Second message")
        await pilot.pause()

        # Third message
        app._show_message("Third message")
        await pilot.pause()

        # Verify only one #welcome exists
        assert len(app.query("#welcome")) == 1


async def test_list_resources_no_results_error(mock_httpx):
    """Test the specific reported case: 'list' command with no results."""
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        # Mock empty response for list_resources
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock(status_code=200)
            mock_response.json.return_value = []
            mock_get.return_value = mock_response

            # This should call _show_message
            app._list_resources()
            await pilot.pause()

            # Verify only one #welcome exists
            assert len(app.query("#welcome")) == 1

            # Call it again - this is where it would crash before
            app._list_resources()
            await pilot.pause()

            assert len(app.query("#welcome")) == 1


async def test_show_resource_details_success(mock_httpx):
    """Test functionality of the 'dr' (details resource) command."""
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        # Mock successful resource fetch
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock(status_code=200)
            mock_response.json.return_value = {
                "id": 1,
                "url": "https://example.com",
                "resource_type": "paper",
                "date_created": "2023-01-01T12:00:00Z",
                "extracted_text": "hello",
                "summary": "A short summary",
            }
            mock_get.return_value = mock_response

            app._show_resource_details("1")
            await pilot.pause()

            # Verify new layout components
            header = app.query_one(".details-header", Label)
            content = str(header.render())
            assert "Resource Details (ID: 1)" in content
            assert "https://example.com" in content

            # Verify left pane
            left_pane = app.query_one("#details-left Label", Label)
            left_content = str(left_pane.render())
            assert "Extracted Text" in left_content
            assert "hello" in left_content

            # Verify right pane
            right_pane = app.query_one("#details-right Label", Label)
            right_content = str(right_pane.render())
            assert "Summary" in right_content
            assert "A short summary" in right_content


async def test_show_resource_details_not_found(mock_httpx):
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock(status_code=404)
            mock_get.return_value = mock_response

            app._show_resource_details("999")
            await pilot.pause()

            welcome = app.query_one("#welcome", Static)
            content = str(welcome.render())
            assert "Resource 999 not found" in content


async def test_show_resource_details_invalid_id(mock_httpx):
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        app._show_resource_details("abc")
        await pilot.pause()

        welcome = app.query_one("#welcome", Static)
        content = str(welcome.render())
        assert "Invalid resource ID. Must be a number." in content


# ---- Slash Command Tests ----


async def test_resolve_command_with_slash(mock_httpx):
    """Test that slash commands are resolved correctly."""
    from kb.tui.app import _resolve_command

    # Test canonical commands
    cmd, canonical, args = _resolve_command("/help")
    assert cmd is not None
    assert canonical == "/help"
    assert args is None

    cmd, canonical, args = _resolve_command("/resource-list")
    assert cmd is not None
    assert canonical == "/resource-list"
    assert args is None

    cmd, canonical, args = _resolve_command("/chat-start 123")
    assert cmd is not None
    assert canonical == "/chat-start"
    assert args == "123"


async def test_resolve_command_aliases(mock_httpx):
    """Test that slash aliases resolve to canonical commands."""
    from kb.tui.app import _resolve_command

    # Test aliases
    cmd, canonical, args = _resolve_command("/h")
    assert cmd is not None
    assert canonical == "/help"

    cmd, canonical, args = _resolve_command("/rl")
    assert cmd is not None
    assert canonical == "/resource-list"

    cmd, canonical, args = _resolve_command("/rd 456")
    assert cmd is not None
    assert canonical == "/resource-details"
    assert args == "456"

    cmd, canonical, args = _resolve_command("/cs 789")
    assert cmd is not None
    assert canonical == "/chat-start"
    assert args == "789"


async def test_resolve_bare_command_rejected(mock_httpx):
    """Test that bare commands (without /) return None with helpful info."""
    from kb.tui.app import _resolve_command

    cmd, canonical, args = _resolve_command("help")
    assert cmd is None
    assert canonical == "help"

    cmd, canonical, args = _resolve_command("list")
    assert cmd is None
    assert canonical == "list"

    cmd, canonical, args = _resolve_command("chat 123")
    assert cmd is None
    assert canonical == "chat"
    assert args == "123"


async def test_resolve_unknown_command(mock_httpx):
    """Test that unknown slash commands are handled correctly."""
    from kb.tui.app import _resolve_command

    cmd, canonical, args = _resolve_command("/unknown")
    assert cmd is None
    assert canonical == "/unknown"


async def test_bare_command_error_message(mock_httpx):
    """Test that bare commands show a helpful error message about slash requirement."""
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        # Submit a bare command
        await pilot.press("h")
        await pilot.press("e")
        await pilot.press("l")
        await pilot.press("p")
        await pilot.press("enter")
        await pilot.pause()

        # Check the error message
        welcome = app.query_one("#welcome", Static)
        content = str(welcome.render())
        assert "Commands must start with a forward slash" in content
        assert "/help" in content


async def test_slash_help_renders_commands(mock_httpx):
    """Test that /help renders all implemented commands from the registry."""
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        # Submit /help
        await pilot.press("/")
        await pilot.press("h")
        await pilot.press("e")
        await pilot.press("l")
        await pilot.press("p")
        await pilot.press("enter")
        await pilot.pause()

        # Check the help text
        welcome = app.query_one("#welcome", Static)
        content = str(welcome.render())

        # Verify all implemented commands are listed
        assert "/help" in content
        assert "/resource-add" in content
        assert "/resource-list" in content
        assert "/resource-details" in content
        assert "/chat-list" in content
        assert "/chat-start" in content
        assert "/chat-continue" in content
        assert "/search" in content
        assert "/llm-configs" in content
        assert "/text-extraction-configs" in content
        assert "/kg-configs" in content

        # Verify the slash requirement hint is present
        assert "All commands must start with /" in content


async def test_slash_aliases_in_help(mock_httpx):
    """Test that /help shows aliases for commands."""
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        await pilot.press("/")
        await pilot.press("h")
        await pilot.press("e")
        await pilot.press("l")
        await pilot.press("p")
        await pilot.press("enter")
        await pilot.pause()

        welcome = app.query_one("#welcome", Static)
        content = str(welcome.render())

        # Check that aliases are shown in some form
        assert "/h" in content  # help alias
        assert "/ra" in content  # resource-add alias
        assert "/rl" in content  # resource-list alias
        assert "/rd" in content  # resource-details alias
        assert "/cl" in content  # chat-list alias
        assert "/cs" in content  # chat-start alias
        assert "/cc" in content  # chat-continue alias
        assert "/ss" in content  # search alias
        assert "/lc" in content  # llm-configs alias
        assert "/tec" in content  # text-extraction-configs alias
        assert "/kgc" in content  # kg-configs alias


# ---- Autocomplete Tests ----


async def test_get_command_suggestions(mock_httpx):
    """Test that command suggestions work for partial matches."""
    from kb.tui.app import _get_command_suggestions

    # Test partial match of canonical name
    suggestions = _get_command_suggestions("/he")
    assert len(suggestions) >= 1
    assert any(cmd.name == "/help" for cmd in suggestions)

    # Test no match for non-slash
    suggestions = _get_command_suggestions("he")
    assert len(suggestions) == 0

    # Test empty for non-matching
    suggestions = _get_command_suggestions("/xyz")
    assert len(suggestions) == 0


async def test_get_command_suggestions_multiple_matches(mock_httpx):
    """Test that command suggestions return multiple matches for shared prefixes."""
    from kb.tui.app import _get_command_suggestions

    suggestions = _get_command_suggestions("/c")
    # Should match /chat, /continue, /chats and their aliases
    assert len(suggestions) >= 1


async def test_format_help_text_contains_all_commands(mock_httpx):
    """Test that _format_help_text includes all registered commands."""
    from kb.tui.app import _format_help_text, _get_all_commands

    help_text = _format_help_text()

    # Verify all canonical commands are present
    commands = _get_all_commands()
    for cmd in commands:
        assert cmd.name in help_text
        assert cmd.description in help_text


# ---- Command Registry Tests ----


async def test_command_registry_has_all_commands(mock_httpx):
    """Test that all expected commands are registered."""
    from kb.tui.app import COMMAND_REGISTRY

    expected_canonical = [
        "/help",
        "/resource-add",
        "/resource-list",
        "/resource-details",
        "/chat-list",
        "/chat-start",
        "/chat-continue",
        "/search",
        "/llm-configs",
        "/text-extraction-configs",
        "/kg-configs",
    ]

    for cmd_name in expected_canonical:
        assert cmd_name in COMMAND_REGISTRY


async def test_kg_configs_registered(mock_httpx):
    """Test that kg-configs is registered."""
    from kb.tui.app import COMMAND_REGISTRY

    assert "/kg-configs" in COMMAND_REGISTRY


# ---- Integration Tests ----


async def test_help_command_via_alias(mock_httpx):
    """Test that /h alias works for help."""
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        # Submit /h
        await pilot.press("/")
        await pilot.press("h")
        await pilot.press("enter")
        await pilot.pause()

        welcome = app.query_one("#welcome", Static)
        content = str(welcome.render())
        assert "/help" in content


async def test_list_command_via_alias(mock_httpx):
    """Test that /rl alias is properly resolved to /resource-list command."""
    # Test the registry resolution directly
    from kb.tui.app import _resolve_command

    cmd, canonical, args = _resolve_command("/rl")
    assert cmd is not None
    assert canonical == "/resource-list"
    assert "/rl" in cmd.aliases


async def test_details_command_with_alias_and_arg(mock_httpx):
    """Test that /rd with argument works."""
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        # Mock httpx at the module level where it's imported
        with patch("kb.tui.app.httpx.get") as mock_get:
            mock_response = MagicMock(status_code=200)
            mock_response.json.return_value = {
                "id": 1,
                "url": "https://test.com",
                "resource_type": "paper",
                "extracted_text": "test",
                "summary": "test summary",
            }
            mock_get.return_value = mock_response
            await pilot.press("/")
            await pilot.press("r")
            await pilot.press("d")
            await pilot.press(" ")
            await pilot.press("1")
            await pilot.press("enter")
            await pilot.pause()

            # Should show details screen - command input should be hidden
            cmd_input_display = app.query_one("#command-input").display
            assert cmd_input_display is False


async def test_input_submit_applies_autocomplete_selection(mock_httpx):
    """Test that Enter submits the highlighted autocomplete command, not the partial."""
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        cmd_input = app.query_one("#command-input", Input)
        popup = app.query_one("#autocomplete-popup")
        option_list = app.query_one("#autocomplete-options", OptionList)

        cmd_input.value = "/res"
        suggestions = _get_command_suggestions("/res")
        app._show_autocomplete(suggestions)
        await pilot.pause()

        assert popup.display is True
        option_list.highlighted = [cmd.name for cmd in suggestions].index(
            "/resource-list"
        )

        await pilot.press("enter")
        await pilot.pause()

        welcome = app.query_one("#welcome", Static)
        content = str(welcome.render())
        assert "Unknown command: /res" not in content
        assert "No resources found" in content
