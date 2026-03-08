import pytest
from textual.widgets import Static
from kb.tui.app import ResearchKBApp
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.asyncio

@pytest.fixture
def mock_httpx():
    with patch("httpx.get") as mock_get:
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = []
        mock_get.return_value = mock_response
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
