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

_TEST_LLM_URL = "https://llm.example.com/v1"
_ALT_LLM_URL = "https://llm.alt.example.com/v1"


@pytest.fixture
def allow_listed_hosts(monkeypatch):
    """Configure the module's host allow-list to `llm.example.com` for one test."""
    monkeypatch.setattr(
        llm_service,
        "_ALLOWED_LLM_HOSTS",
        llm_service._parse_allowed_hosts("llm.example.com"),
    )


@pytest.fixture
def no_host_enforcement(monkeypatch):
    """Default state: empty allow-list -> no host enforcement."""
    monkeypatch.setattr(llm_service, "_ALLOWED_LLM_HOSTS", frozenset())


def _configure_settings(mock_settings):
    """Apply the common enabled-LLM settings used by the HTTP-level tests."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _TEST_LLM_URL
    mock_settings.LLM_API_KEY = "test-key"
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"


def _make_response(status_code, *, content=None, headers=None):
    """Build a mock httpx response with a synchronous `.json()` and real `.headers`."""
    response = AsyncMock()
    response.status_code = status_code
    response.headers = headers or {}
    if content is not None:
        response.json = lambda: {"choices": [{"message": {"content": content}}]}
    return response


def _make_client(mock_client_class, *, post):
    """Wire a mock async-context-manager httpx client whose `.post` is `post`."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = post
    mock_client_class.return_value = mock_client
    return mock_client


def _content_response(content):
    """Wrap raw model `content` in the OpenAI-style chat-completion envelope."""
    return {"choices": [{"message": {"content": content}}]}


_PARSE_EPISODES = [
    {"season": 1, "number": 1, "title": "Pilot"},
    {"season": 1, "number": 2, "title": "Cat"},
    {"season": 2, "number": 1, "title": "Seven"},
]


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
async def test_llm_disabled_returns_none(mock_settings, no_host_enforcement):
    """Test that LLM returns None when disabled."""
    mock_settings.LLM_ENABLED = False
    mock_settings.LLM_API_URL = settings.LLM_API_URL
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

    result = await llm_service.parse_natural_language_query("test query", [{"title": "Test"}])
    assert result is None


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
async def test_llm_no_api_url_returns_none(mock_settings, no_host_enforcement):
    """Test that LLM returns None when API URL is not configured."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = None
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

    result = await llm_service.parse_natural_language_query("test query", [{"title": "Test"}])
    assert result is None


@pytest.mark.asyncio
@patch("app.services.llm_service._query_llm", new_callable=AsyncMock)
@patch("app.services.llm_service.settings")
async def test_llm_url_outside_allow_list_is_blocked(mock_settings, mock_query_llm, allow_listed_hosts):
    """When ALLOWED_LLM_HOSTS is set, non-listed hosts are ignored by default."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _ALT_LLM_URL  # not in allow-list
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

    result = await llm_service.parse_natural_language_query("test query", [{"title": "Test"}])

    assert result is None
    mock_query_llm.assert_not_called()


@pytest.mark.asyncio
@patch("app.services.llm_service._query_llm", new_callable=AsyncMock)
@patch("app.services.llm_service.settings")
async def test_llm_allow_external_overrides_allow_list(mock_settings, mock_query_llm, allow_listed_hosts):
    """LLM_ALLOW_EXTERNAL=true bypasses the host allow-list for deliberate experiments."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _ALT_LLM_URL + "/"
    mock_settings.LLM_ALLOW_EXTERNAL = True
    mock_settings.LLM_MODEL_NAME = "auto"
    mock_query_llm.return_value = [{"title": "Test"}]

    result = await llm_service.parse_natural_language_query("test query", [{"title": "Test"}])

    assert result == [{"title": "Test"}]
    mock_query_llm.assert_awaited_once_with(
        "test query",
        [{"title": "Test"}],
        base_url=_ALT_LLM_URL,
    )


@pytest.mark.asyncio
@patch("app.services.llm_service._query_llm", new_callable=AsyncMock)
@patch("app.services.llm_service.settings")
async def test_llm_no_allow_list_accepts_any_host(mock_settings, mock_query_llm, no_host_enforcement):
    """Default behavior: empty allow-list -> any configured URL is accepted."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _ALT_LLM_URL + "/"
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"
    mock_query_llm.return_value = [{"title": "Test"}]

    result = await llm_service.parse_natural_language_query("test query", [{"title": "Test"}])

    assert result == [{"title": "Test"}]
    mock_query_llm.assert_awaited_once_with(
        "test query",
        [{"title": "Test"}],
        base_url=_ALT_LLM_URL,
    )


@pytest.mark.asyncio
@patch("app.services.llm_service._query_llm", new_callable=AsyncMock)
@patch("app.services.llm_service.settings")
async def test_llm_gateway_url_normalized(mock_settings, mock_query_llm, allow_listed_hosts):
    """Allow-listed gateway URLs are normalized before requests are built."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = f" {_TEST_LLM_URL}/ "
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"
    mock_query_llm.return_value = [{"title": "Test"}]

    result = await llm_service.parse_natural_language_query("test query", [{"title": "Test"}])

    assert result == [{"title": "Test"}]
    mock_query_llm.assert_awaited_once_with(
        "test query",
        [{"title": "Test"}],
        base_url=_TEST_LLM_URL,
    )


def test_normalize_base_url_rejects_blank_and_relative_urls():
    """Blank and relative LLM URLs are treated as unconfigured."""
    assert llm_service._normalize_base_url("   ") is None
    assert llm_service._normalize_base_url("llm.example.com/v1") is None


def test_parse_allowed_hosts_handles_whitespace_and_case():
    """`_parse_allowed_hosts` strips whitespace, lowercases, and drops empties."""
    assert llm_service._parse_allowed_hosts("") == frozenset()
    assert llm_service._parse_allowed_hosts(" , ") == frozenset()
    assert llm_service._parse_allowed_hosts("LLM.Example.Com") == frozenset({"llm.example.com"})
    assert llm_service._parse_allowed_hosts("a.example.com, B.Example.Com ,") == frozenset(
        {"a.example.com", "b.example.com"}
    )


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
async def test_query_llm_returns_none_when_policy_rejects_url(mock_settings, allow_listed_hosts):
    """The lower-level query helper also enforces URL policy."""
    mock_settings.LLM_API_URL = "llm.example.com/v1"  # missing scheme -> normalizer rejects
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

    result = await llm_service._query_llm("test query", [{"title": "Test"}])

    assert result is None


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
async def test_llm_empty_episodes_returns_empty_list(mock_settings, no_host_enforcement):
    """Test that LLM returns empty list when no episodes provided, even if LLM is disabled."""
    # Test with LLM disabled (should still return [] for empty episodes)
    mock_settings.LLM_ENABLED = False
    mock_settings.LLM_API_URL = None
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

    result = await llm_service.parse_natural_language_query("test query", [])
    assert result == []


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_successful_query(mock_client_class, mock_settings, no_host_enforcement):
    """Test successful LLM query parsing."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _TEST_LLM_URL
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY or "test-key"
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

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
    assert call_args[1]["json"]["model"] == "auto"
    # Structured-output mode is requested so the gateway returns a JSON object.
    assert call_args[1]["json"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_no_api_key(mock_client_class, mock_settings, no_host_enforcement):
    """Test LLM query without API key - should not send Authorization header."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _TEST_LLM_URL
    mock_settings.LLM_API_KEY = None
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

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
    # Verify Authorization header is NOT included when no API key
    call_args = mock_client.post.call_args
    assert "Authorization" not in call_args[1]["headers"]


@pytest.mark.asyncio
@patch("app.services.llm_service.asyncio.sleep", new_callable=AsyncMock)
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_api_error(mock_client_class, mock_settings, mock_sleep, no_host_enforcement):
    """A persistent 5xx is retried once, then falls back cleanly (two attempts, None)."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _TEST_LLM_URL
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"}]

    mock_response = AsyncMock()
    mock_response.status_code = 500  # Server error
    mock_response.headers = {}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    result = await llm_service.parse_natural_language_query("test", episodes)
    assert result is None
    assert mock_client.post.call_count == 2  # one retry after the first 500
    mock_sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_invalid_json_response(mock_client_class, mock_settings, no_host_enforcement):
    """Test LLM with invalid JSON response."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _TEST_LLM_URL
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

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
async def test_llm_limits_episodes_to_100(mock_client_class, mock_settings, no_host_enforcement):
    """Test that LLM limits context to 100 episodes."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _TEST_LLM_URL
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

    # Create 120 episodes
    episodes = [{"season": 1, "number": i, "title": f"Episode {i}", "release_date": "2008-01-20"} for i in range(120)]

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"choices": [{"message": {"content": "[0]"}}]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client_class.return_value = mock_client

    await llm_service.parse_natural_language_query("test", episodes)

    # Verify only 100 episodes were sent in the prompt
    call_args = mock_client.post.call_args
    prompt = call_args[1]["json"]["messages"][0]["content"]
    episode_data = json.loads(prompt.split("Episodes:\n")[1].split("\n\nReturn")[0])
    assert len(episode_data) == 100


@pytest.mark.asyncio
@patch("app.services.llm_service.asyncio.sleep", new_callable=AsyncMock)
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_http_exception_handling(mock_client_class, mock_settings, mock_sleep, no_host_enforcement):
    """A persistent network error is retried once, then handled gracefully (None)."""
    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = _TEST_LLM_URL
    mock_settings.LLM_API_KEY = settings.LLM_API_KEY
    mock_settings.LLM_ALLOW_EXTERNAL = False
    mock_settings.LLM_MODEL_NAME = "auto"

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"}]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=httpx.RequestError("Connection error"))
    mock_client_class.return_value = mock_client

    result = await llm_service.parse_natural_language_query("test", episodes)
    assert result is None
    assert mock_client.post.call_count == 2  # one retry after the first network error
    mock_sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
@patch("app.services.llm_service.asyncio.sleep", new_callable=AsyncMock)
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_retries_on_5xx_then_succeeds(mock_client_class, mock_settings, mock_sleep, no_host_enforcement):
    """A transient 5xx is retried once; the second (200) response is used."""
    _configure_settings(mock_settings)
    episodes = [
        {"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"},
        {"season": 1, "number": 2, "title": "Cat", "release_date": "2008-01-27"},
    ]
    post = AsyncMock(side_effect=[_make_response(503), _make_response(200, content="[0]")])
    client = _make_client(mock_client_class, post=post)

    result = await llm_service.parse_natural_language_query("test", episodes)

    assert [ep["title"] for ep in result] == ["Pilot"]
    assert client.post.call_count == 2
    mock_sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
@patch("app.services.llm_service.asyncio.sleep", new_callable=AsyncMock)
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_retries_on_429_and_honors_retry_after(
    mock_client_class, mock_settings, mock_sleep, no_host_enforcement
):
    """A 429 is retried, waiting for the numeric `Retry-After` header before the retry."""
    _configure_settings(mock_settings)
    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"}]
    post = AsyncMock(
        side_effect=[
            _make_response(429, headers={"Retry-After": "1"}),
            _make_response(200, content='{"idx": [0]}'),
        ]
    )
    client = _make_client(mock_client_class, post=post)

    result = await llm_service.parse_natural_language_query("test", episodes)

    assert [ep["title"] for ep in result] == ["Pilot"]
    assert client.post.call_count == 2
    mock_sleep.assert_awaited_once_with(1.0)


@pytest.mark.asyncio
@patch("app.services.llm_service.asyncio.sleep", new_callable=AsyncMock)
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_retry_after_non_numeric_falls_back_to_backoff(
    mock_client_class, mock_settings, mock_sleep, no_host_enforcement
):
    """A non-numeric `Retry-After` is ignored and the default backoff is used."""
    _configure_settings(mock_settings)
    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"}]
    post = AsyncMock(
        side_effect=[
            _make_response(429, headers={"Retry-After": "soon"}),
            _make_response(200, content="[0]"),
        ]
    )
    _make_client(mock_client_class, post=post)

    result = await llm_service.parse_natural_language_query("test", episodes)

    assert [ep["title"] for ep in result] == ["Pilot"]
    mock_sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
@patch("app.services.llm_service.settings")
@patch("httpx.AsyncClient")
async def test_llm_no_retry_on_client_error(mock_client_class, mock_settings, no_host_enforcement):
    """A non-retryable 4xx (400) fails fast with no retry."""
    _configure_settings(mock_settings)
    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"}]
    post = AsyncMock(return_value=_make_response(400))
    client = _make_client(mock_client_class, post=post)

    result = await llm_service.parse_natural_language_query("test", episodes)

    assert result is None
    assert client.post.call_count == 1


@pytest.mark.parametrize(
    ("content", "expected_titles"),
    [
        ("[0, 2]", ["Pilot", "Seven"]),  # bare array (back-compat)
        ('{"idx": [0, 2]}', ["Pilot", "Seven"]),  # json_object mode
        ('{"indices": [1]}', ["Cat"]),  # alternate key
        ('<think>reasoning</think>{"idx": [0]}', ["Pilot"]),  # think-tag strip + object
        ("[]", []),  # empty array
        ('{"idx": []}', []),  # empty object
    ],
)
def test_parse_llm_response_accepts_array_and_object_shapes(content, expected_titles):
    """Both a bare array and a `{"idx": [...]}` / `{"indices": [...]}` object parse correctly."""
    result = llm_service._parse_llm_response(_content_response(content), _PARSE_EPISODES, "q")
    assert result is not None
    assert [ep["title"] for ep in result] == expected_titles


@pytest.mark.parametrize(
    "content",
    ['{"foo": 1}', '{"idx": "nope"}', '"scalar"', "5", "null", "not json at all"],
)
def test_parse_llm_response_rejects_unusable_shapes(content):
    """Missing keys, non-list values, scalars, and unparsable text all return None."""
    assert llm_service._parse_llm_response(_content_response(content), _PARSE_EPISODES, "q") is None
