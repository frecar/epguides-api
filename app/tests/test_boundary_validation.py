"""Configuration and entry-point scripts reject bad input with the field, value and fix."""

import logging
import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

import healthcheck
import verify_llm
from app import main as app_main
from app.core import cache
from app.core.config import LogFormat, LogLevel, Settings


def _settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


def test_log_level_and_format_are_case_insensitive():
    settings = _settings(LOG_LEVEL=" debug ", LOG_FORMAT="TEXT")

    assert settings.LOG_LEVEL is LogLevel.DEBUG
    assert settings.LOG_FORMAT is LogFormat.TEXT


def test_unknown_log_level_names_field_value_and_choices():
    with pytest.raises(ValidationError) as excinfo:
        _settings(LOG_LEVEL="verbose")

    message = str(excinfo.value)
    assert "LOG_LEVEL" in message
    assert "'DEBUG', 'INFO', 'WARNING', 'ERROR' or 'CRITICAL'" in message
    assert "input_value='VERBOSE'" in message


def test_unknown_log_format_lists_json_text_auto():
    with pytest.raises(ValidationError) as excinfo:
        _settings(LOG_FORMAT="pretty")

    assert "LOG_FORMAT" in str(excinfo.value)
    assert "'json', 'text' or 'auto'" in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("REDIS_PORT", "70000", "less than or equal to 65535"),
        ("HTTP_TIMEOUT_SECONDS", "0", "greater than 0"),
        ("CACHE_TTL_SECONDS", "-1", "greater than 0"),
        ("SENTRY_TRACES_SAMPLE_RATE", "1.5", "less than or equal to 1"),
        ("REDIS_MAX_CONNECTIONS", "0", "greater than or equal to 1"),
    ],
)
def test_out_of_range_settings_name_field_and_bound(field, value, expected):
    with pytest.raises(ValidationError) as excinfo:
        _settings(**{field: value})

    message = str(excinfo.value)
    assert field in message
    assert expected in message
    assert f"input_value='{value}'" in message


def _urlopen_returning(status: int, body: bytes) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    response.__enter__.return_value = response
    return MagicMock(return_value=response)


def test_healthcheck_healthy_exits_zero(capsys):
    with patch("urllib.request.urlopen", _urlopen_returning(200, b'{"status": "healthy"}')):
        assert healthcheck.main([]) == 0
        assert healthcheck.check_health() is True

    assert capsys.readouterr().err == ""


def test_healthcheck_reports_non_200_status(capsys):
    with patch("urllib.request.urlopen", _urlopen_returning(503, b"")):
        assert healthcheck.main(["--url", "http://api:3000/health"]) == 1

    assert capsys.readouterr().err == "unhealthy: GET http://api:3000/health returned HTTP 503, expected 200\n"


def test_healthcheck_reports_missing_healthy_marker(capsys):
    with patch("urllib.request.urlopen", _urlopen_returning(200, b'{"status": "degraded"}')):
        assert healthcheck.main([]) == 1

    assert 'body has no "healthy" status' in capsys.readouterr().err


def test_healthcheck_reports_connection_failure(capsys):
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        assert healthcheck.main([]) == 1

    err = capsys.readouterr().err
    assert err.startswith("unhealthy: GET http://localhost:3000/health failed: URLError:")
    assert "Connection refused" in err


def test_healthcheck_rejects_non_positive_timeout(capsys):
    with pytest.raises(SystemExit) as excinfo:
        healthcheck.main(["--timeout", "0"])

    assert excinfo.value.code == 2
    assert "--timeout must be greater than 0 seconds, got 0" in capsys.readouterr().err


def test_healthcheck_help_shows_example(capsys):
    with pytest.raises(SystemExit):
        healthcheck.main(["--help"])

    assert "example: python healthcheck.py --url" in capsys.readouterr().out


def test_verify_llm_help_shows_example(capsys):
    with pytest.raises(SystemExit):
        verify_llm.main(["--help"])

    out = capsys.readouterr().out
    assert "example: LLM_ENABLED=true LLM_API_URL=" in out
    assert "--query" in out


def test_verify_llm_disabled_names_setting(monkeypatch, capsys):
    monkeypatch.setattr(verify_llm.settings, "LLM_ENABLED", False)

    assert verify_llm.main([]) == 1
    assert "Set LLM_ENABLED=true" in capsys.readouterr().err


def test_verify_llm_missing_url_names_setting_and_example(monkeypatch, capsys):
    monkeypatch.setattr(verify_llm.settings, "LLM_ENABLED", True)
    monkeypatch.setattr(verify_llm.settings, "LLM_API_URL", None)

    assert verify_llm.main([]) == 1
    assert "LLM_API_URL is not set" in capsys.readouterr().err


def test_verify_llm_reports_unusable_answer_with_query(monkeypatch, capsys):
    monkeypatch.setattr(verify_llm.settings, "LLM_ENABLED", True)
    monkeypatch.setattr(verify_llm.settings, "LLM_API_URL", "http://llm.test/v1")

    with patch.object(verify_llm.llm_service, "parse_natural_language_query", new=AsyncMock(return_value=None)):
        assert verify_llm.main(["--query", "pilot"]) == 1

    assert "LLM at http://llm.test/v1 returned no usable answer for 'pilot'" in capsys.readouterr().err


def test_verify_llm_success_lists_matches(monkeypatch, capsys):
    monkeypatch.setattr(verify_llm.settings, "LLM_ENABLED", True)
    monkeypatch.setattr(verify_llm.settings, "LLM_API_URL", "http://llm.test/v1")
    match = [{"season": 1, "number": 1, "title": "Pilot"}]

    with patch.object(verify_llm.llm_service, "parse_natural_language_query", new=AsyncMock(return_value=match)):
        assert verify_llm.main([]) == 0

    assert "S1E1: Pilot" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cache_exists_failure_is_logged_with_key(caplog):
    with (
        patch("app.core.cache.get_redis", new=AsyncMock(side_effect=RedisConnectionError("redis down"))),
        caplog.at_level(logging.WARNING, logger="app.core.cache"),
    ):
        assert await cache.cache_exists("show_index") is False

    assert "Cache existence check failed for show_index, treating it as absent: redis down" in caplog.text


def test_logging_setup_failure_falls_back_and_says_why(caplog):
    with (
        patch("app.core.logging_config.setup_logging", side_effect=ValueError("bad handler")),
        caplog.at_level(logging.WARNING),
    ):
        app_main._initialize_logging()

    assert (
        "Structured logging setup failed (ValueError: bad handler); using basic INFO logging. "
        "Check LOG_LEVEL and LOG_FORMAT." in caplog.text
    )
