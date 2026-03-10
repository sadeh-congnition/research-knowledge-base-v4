import pytest
from textual.widgets import Static, Label
from kb.tui.app import ResearchKBApp
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


async def test_show_resource_details_invalid_id():
    app = ResearchKBApp()
    async with app.run_test() as pilot:
        app._show_resource_details("abc")
        await pilot.pause()

        welcome = app.query_one("#welcome", Static)
        content = str(welcome.render())
        assert "Invalid resource ID. Must be a number." in content
