"""
Tests for LLM service functionality.

Tests natural language query parsing with proper mocking and environment handling.
Uses actual settings from .env file where appropriate.
"""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.config import settings
from app.services import llm_service


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
async def test_llm_disabled_returns_none(mock_settings):
    """Test that LLM returns None when disabled."""
    mock_settings.LLM_ENABLED = False
    mock_settings.LLM_API_URL = settings.LLM_API_URL

    result = await llm_service.parse_natural_language_query("test query", [{"title": "Test"}])
    assert result is None


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
async def test_llm_no_api_url_returns_none(mock_settings):
    """Test that LLM returns None when API URL is not configured."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = None

    result = await llm_service.parse_natural_language_query("test query", [{"title": "Test"}])
    assert result is None


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
async def test_llm_empty_episodes_returns_empty_list(mock_settings):
    """Test that LLM returns empty list when no episodes provided."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = settings.LLM_API_URL

    result = await llm_service.parse_natural_language_query("test query", [])
    assert result == []


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_successful_query(mock_client_class, mock_settings):
    """Test successful LLM query parsing."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = settings.LLM_API_URL or "https://llm.local.carlsen.io/v1"
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY or "test-key"

    # Mock episodes
    episodes = [
        {"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"},
        {"season": 1, "number": 2, "title": "Cat's in the Bag", "release_date": "2008-01-27"},
        {"season": 2, "number": 1, "title": "Seven Thirty-Seven", "release_date": "2009-03-08"},
    ]

    # Mock HTTP response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"choices": [{"message": {"content": "[0, 2]"}}]}  # Return indices 0 and 2

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await llm_service.parse_natural_language_query("episodes with pilot or seven", episodes)

    assert result is not None
    assert len(result) == 2
    assert result[0]["title"] == "Pilot"
    assert result[1]["title"] == "Seven Thirty-Seven"

    # Verify the request was made correctly
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    expected_url = f"{mock_settings.LLM_API_URL}/chat/completions"
    assert call_args[0][0] == expected_url
    expected_auth = f"Bearer {mock_settings.LLM_API_KEY}" if mock_settings.LLM_API_KEY else ""
    assert call_args[1]["headers"]["Authorization"] == expected_auth
    assert "messages" in call_args[1]["json"]


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_no_api_key(mock_client_class, mock_settings):
    """Test LLM query without API key."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = settings.LLM_API_URL or "https://llm.local.carlsen.io/v1"
    mock_settings.LLM_API_KEY = None

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"}]

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"choices": [{"message": {"content": "[0]"}}]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await llm_service.parse_natural_language_query("test", episodes)

    assert result is not None
    # Verify Authorization header is empty string when no API key
    call_args = mock_client.post.call_args
    assert call_args[1]["headers"]["Authorization"] == ""


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_api_error(mock_client_class, mock_settings):
    """Test LLM API error handling."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = settings.LLM_API_URL or "https://llm.local.carlsen.io/v1"
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"}]

    mock_response = AsyncMock()
    mock_response.status_code = 500  # Server error

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await llm_service.parse_natural_language_query("test", episodes)
    assert result is None


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_invalid_json_response(mock_client_class, mock_settings):
    """Test LLM with invalid JSON response."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = settings.LLM_API_URL or "https://llm.local.carlsen.io/v1"
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"}]

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"choices": [{"message": {"content": "not valid json"}}]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await llm_service.parse_natural_language_query("test", episodes)
    # Should return None due to JSON parsing error
    assert result is None


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_limits_episodes_to_50(mock_client_class, mock_settings):
    """Test that LLM limits context to 50 episodes."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = settings.LLM_API_URL or "https://llm.local.carlsen.io/v1"
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY

    # Create 60 episodes
    episodes = [{"season": 1, "number": i, "title": f"Episode {i}", "release_date": "2008-01-20"} for i in range(60)]

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"choices": [{"message": {"content": "[0]"}}]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    await llm_service.parse_natural_language_query("test", episodes)

    # Verify only 50 episodes were sent in the prompt
    call_args = mock_client.post.call_args
    prompt = call_args[1]["json"]["messages"][0]["content"]
    episode_data = json.loads(prompt.split("Episodes:\n")[1].split("\n\nReturn")[0])
    assert len(episode_data) == 50


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_http_exception_handling(mock_client_class, mock_settings):
    """Test LLM handles HTTP exceptions gracefully."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = settings.LLM_API_URL or "https://llm.local.carlsen.io/v1"
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"}]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=httpx.RequestError("Connection error"))
    mock_client_class.return_value = mock_client

    result = await llm_service.parse_natural_language_query("test", episodes)
    assert result is None
