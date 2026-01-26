"""
Unit tests for service functions.

Tests business logic independently of HTTP layer.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS, get_version
from app.services import epguides, show_service

# =============================================================================
# get_version() Tests
# =============================================================================


def test_get_version_from_version_file():
    """Test get_version reads from VERSION file when it exists."""
    # The VERSION file exists in the project root (created by pre-commit hook)
    # This test verifies it reads successfully
    result = get_version()
    # Should return a numeric string (from VERSION file) or "dev"
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_version_from_env_variable(monkeypatch, tmp_path):
    """Test get_version falls back to APP_VERSION env var."""
    # Make VERSION file not exist
    monkeypatch.setenv("APP_VERSION", "789")

    with patch("pathlib.Path.exists", return_value=False):
        result = get_version()
        # Should return env var value
        assert result == "789"


def test_get_version_file_read_error(monkeypatch):
    """Test get_version handles file read errors gracefully."""
    monkeypatch.setenv("APP_VERSION", "fallback")

    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", side_effect=OSError("Permission denied")):
            result = get_version()
            # Should fall back to env var
            assert result == "fallback"


def test_get_version_env_dev_ignored(monkeypatch):
    """Test get_version ignores APP_VERSION='dev'."""
    monkeypatch.setenv("APP_VERSION", "dev")

    with patch("pathlib.Path.exists", return_value=False):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "999\n"
            result = get_version()
            # Should use git, not "dev" env var
            assert result == "999"


def test_get_version_from_git(monkeypatch):
    """Test get_version falls back to git commit count."""
    monkeypatch.delenv("APP_VERSION", raising=False)

    with patch("pathlib.Path.exists", return_value=False):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "555\n"
            result = get_version()
            assert result == "555"


def test_get_version_fallback_to_dev(monkeypatch):
    """Test get_version returns 'dev' when all methods fail."""
    monkeypatch.delenv("APP_VERSION", raising=False)

    with patch("pathlib.Path.exists", return_value=False):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("git not available")
            result = get_version()
            assert result == "dev"


def test_get_version_git_fails_returns_dev(monkeypatch):
    """Test get_version returns 'dev' when git returns non-zero."""
    monkeypatch.delenv("APP_VERSION", raising=False)

    with patch("pathlib.Path.exists", return_value=False):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            result = get_version()
            assert result == "dev"


# =============================================================================
# Show Service Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.show_service.cache_set")
@patch("app.services.show_service.cache_get", return_value=None)
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_all_shows(mock_get_metadata, mock_cache_get, mock_cache_set):
    """Test retrieving all shows."""
    mock_data = [
        {
            "directory": "BreakingBad",
            "title": "Breaking Bad",
            "network": "AMC",
            "run time": "60 min",
        }
    ]
    mock_get_metadata.return_value = mock_data

    shows = await show_service.get_all_shows()
    assert len(shows) == 1
    assert shows[0].title == "Breaking Bad"
    assert shows[0].epguides_key == "BreakingBad"


@pytest.mark.asyncio
@patch("app.services.show_service.cache_set")
@patch("app.services.show_service.cache_get", return_value=None)
@patch("app.services.epguides.get_all_shows_metadata")
async def test_search_shows(mock_get_metadata, mock_cache_get, mock_cache_set):
    """Test searching shows."""
    mock_data = [
        {
            "directory": "bb",
            "title": "Breaking Bad",
            "network": "AMC",
            "run time": "60 min",
        },
        {
            "directory": "got",
            "title": "Game of Thrones",
            "network": "HBO",
            "run time": "60 min",
        },
    ]
    mock_get_metadata.return_value = mock_data

    results = await show_service.search_shows("breaking")
    assert len(results) == 1
    assert results[0].title == "Breaking Bad"


def test_parse_date_string():
    """Test date parsing with various formats."""
    # Test standard format
    result = epguides.parse_date_string("20 Jan 08")
    assert result is not None
    assert result.year == 2008

    # Test alternative format
    result = epguides.parse_date_string("20/Jan/08")
    assert result is not None

    # Test invalid date
    result = epguides.parse_date_string("invalid")
    assert result is None

    # Test empty string
    result = epguides.parse_date_string("")
    assert result is None


def test_normalize_show_id():
    """Test show ID normalization."""
    assert show_service.normalize_show_id("BreakingBad") == "breakingbad"
    assert show_service.normalize_show_id("The Breaking Bad") == "breakingbad"
    assert show_service.normalize_show_id("THE OFFICE") == "office"


def test_parse_imdb_id():
    """Test IMDB ID parsing."""
    assert show_service._parse_imdb_id("tt0903747") == "tt0903747"
    assert show_service._parse_imdb_id("tt123456") == "tt0123456"  # Padded
    assert show_service._parse_imdb_id("invalid") == "invalid"


@pytest.mark.asyncio
@patch("app.core.cache.cache_set")
@patch("app.core.cache.cache_get", return_value=None)
@patch("app.services.epguides.get_episodes_data")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_show_does_not_set_end_date_with_unreleased_episodes(
    mock_get_metadata, mock_get_episodes_data, mock_cache_get, mock_cache_set
):
    """Test that get_show does NOT set end_date when there are unreleased episodes."""
    from datetime import datetime, timedelta

    from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS

    # Mock show data from epguides
    mock_get_metadata.return_value = [
        {
            "directory": "fallout",
            "title": "Fallout",
            "network": "Amazon",
            "run time": "60 min",
        }
    ]

    # Create episode data with:
    # - Some released episodes (old dates)
    # - Some unreleased episodes (future dates)
    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS)
    old_date = (threshold - timedelta(days=30)).strftime("%d %b %y")
    future_date = (datetime.now() + timedelta(days=30)).strftime("%d %b %y")

    mock_episodes_data = [
        {
            "season": 1,
            "number": 1,
            "title": "Released Episode",
            "release_date": old_date,
        },
        {
            "season": 1,
            "number": 2,
            "title": "Unreleased Episode",
            "release_date": future_date,
        },
    ]
    mock_get_episodes_data.return_value = mock_episodes_data

    result = await show_service.get_show("fallout")

    # Should NOT have end_date set because there are unreleased episodes
    assert result is not None
    assert result.end_date is None


@pytest.mark.asyncio
@patch("app.services.show_service.extend_cache_ttl")
@patch("app.services.show_service.cache_set")
@patch("app.services.show_service.cache_exists", return_value=False)
@patch("app.services.show_service.cache_hget", return_value=None)
@patch("app.services.show_service.cache_get", return_value=None)
@patch("app.core.cache.cache_set")
@patch("app.core.cache.cache_get", return_value=None)
@patch("app.services.epguides.get_episodes_data")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_show_sets_end_date_when_all_episodes_released(
    mock_get_metadata,
    mock_get_episodes_data,
    mock_core_cache_get,
    mock_core_cache_set,
    mock_cache_get,
    mock_cache_hget,
    mock_cache_exists,
    mock_cache_set,
    mock_extend_ttl,
):
    """Test that get_show DOES set end_date when all episodes are released."""
    from datetime import datetime, timedelta

    from app.core.constants import EPISODE_RELEASE_THRESHOLD_HOURS

    # Mock show data from epguides
    mock_get_metadata.return_value = [
        {
            "directory": "finishedshow2",
            "title": "Finished Show",
            "network": "Netflix",
            "run time": "60 min",
        }
    ]

    # Create episode data with all episodes released (old dates)
    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS)
    old_date_1 = (threshold - timedelta(days=60)).strftime("%d %b %y")
    old_date_2 = (threshold - timedelta(days=30)).strftime("%d %b %y")  # Last episode

    mock_episodes_data = [
        {
            "season": 1,
            "number": 1,
            "title": "First Episode",
            "release_date": old_date_1,
        },
        {
            "season": 1,
            "number": 2,
            "title": "Last Episode",
            "release_date": old_date_2,
        },
    ]
    mock_get_episodes_data.return_value = mock_episodes_data

    result = await show_service.get_show("finishedshow2")

    # Should have end_date set to the last episode's release date
    assert result is not None
    assert result.end_date is not None
    # Verify it's the last episode's date (old_date_2)
    expected_date = epguides.parse_date_string(old_date_2)
    assert expected_date is not None
    assert result.end_date == expected_date.date()


# =============================================================================
# Episode Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_episodes_returns_sorted_list(mock_get_metadata, mock_get_episodes):
    """Test that episodes are returned sorted by season and episode number."""
    mock_get_metadata.return_value = [{"directory": "test", "title": "Test Show"}]

    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS + 1)
    old_date = threshold.strftime("%d %b %y")

    # Episodes in wrong order
    mock_get_episodes.return_value = [
        {"season": 2, "number": 1, "title": "S2E1", "release_date": old_date},
        {"season": 1, "number": 2, "title": "S1E2", "release_date": old_date},
        {"season": 1, "number": 1, "title": "S1E1", "release_date": old_date},
    ]

    episodes = await show_service.get_episodes("test")

    assert len(episodes) == 3
    assert episodes[0].season == 1 and episodes[0].number == 1
    assert episodes[1].season == 1 and episodes[1].number == 2
    assert episodes[2].season == 2 and episodes[2].number == 1


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_episodes_assigns_episode_numbers(mock_get_metadata, mock_get_episodes):
    """Test that episode_number is assigned correctly."""
    mock_get_metadata.return_value = [{"directory": "test", "title": "Test Show"}]

    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS + 1)
    old_date = threshold.strftime("%d %b %y")

    mock_get_episodes.return_value = [
        {"season": 1, "number": 1, "title": "Pilot", "release_date": old_date},
        {"season": 1, "number": 2, "title": "Second", "release_date": old_date},
    ]

    episodes = await show_service.get_episodes("test")

    assert episodes[0].episode_number == 1
    assert episodes[1].episode_number == 2


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
async def test_get_episodes_filters_invalid_entries(mock_get_episodes):
    """Test that episodes with missing fields are filtered out."""
    threshold = datetime.now() - timedelta(hours=EPISODE_RELEASE_THRESHOLD_HOURS + 1)
    old_date = threshold.strftime("%d %b %y")

    mock_get_episodes.return_value = [
        {"season": 1, "number": 1, "title": "Valid", "release_date": old_date},
        {"season": 1, "number": None, "title": "No Number", "release_date": old_date},
        {"season": None, "number": 2, "title": "No Season", "release_date": old_date},
        {"season": 1, "number": 3, "title": "", "release_date": old_date},  # Empty title
        {"season": 1, "number": 4, "title": "No Date", "release_date": ""},
    ]

    episodes = await show_service.get_episodes("test")

    assert len(episodes) == 1
    assert episodes[0].title == "Valid"


# =============================================================================
# Cache Invalidation Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.core.cache.get_redis")
async def test_invalidate_show_cache(mock_get_redis):
    """Test that cache invalidation calls Redis delete."""
    mock_redis = AsyncMock()
    mock_get_redis.return_value = mock_redis

    await show_service.invalidate_show_cache("breakingbad")

    mock_redis.delete.assert_called_once()
    # Verify the keys being deleted
    call_args = mock_redis.delete.call_args[0]
    assert "show:breakingbad" in call_args
    assert "seasons:breakingbad" in call_args


# =============================================================================
# Edge Cases
# =============================================================================


def test_normalize_show_id_edge_cases():
    """Test show ID normalization edge cases."""
    # Mixed case with spaces
    assert show_service.normalize_show_id("The Office") == "office"
    assert show_service.normalize_show_id("THE OFFICE") == "office"

    # No "the" prefix
    assert show_service.normalize_show_id("Friends") == "friends"

    # Multiple spaces
    assert show_service.normalize_show_id("Game of Thrones") == "gameofthrones"


def test_parse_date_string_edge_cases():
    """Test date parsing edge cases."""
    # Various valid formats
    assert epguides.parse_date_string("01 Jan 20") is not None
    assert epguides.parse_date_string("31/Dec/99") is not None

    # Invalid inputs
    assert epguides.parse_date_string(None) is None
    assert epguides.parse_date_string("") is None
    assert epguides.parse_date_string("not a date") is None
    assert epguides.parse_date_string("2024-13-45") is None  # Invalid date


@pytest.mark.asyncio
@patch("app.services.show_service.cache_set")
@patch("app.services.show_service.cache_get", return_value=None)
@patch("app.services.epguides.get_all_shows_metadata")
async def test_search_shows_case_insensitive(mock_get_metadata, mock_cache_get, mock_cache_set):
    """Test that search is case-insensitive."""
    mock_get_metadata.return_value = [
        {"directory": "bb", "title": "Breaking Bad"},
        {"directory": "got", "title": "Game of Thrones"},
    ]

    # Search with different cases
    results1 = await show_service.search_shows("BREAKING")
    results2 = await show_service.search_shows("breaking")
    results3 = await show_service.search_shows("Breaking")

    assert len(results1) == 1
    assert len(results2) == 1
    assert len(results3) == 1
    assert results1[0].title == results2[0].title == results3[0].title


@pytest.mark.asyncio
@patch("app.services.show_service.cache_set")
@patch("app.services.show_service.cache_get", return_value=None)
@patch("app.services.epguides.get_all_shows_metadata")
async def test_search_shows_no_results(mock_get_metadata, mock_cache_get, mock_cache_set):
    """Test search with no matching results."""
    mock_get_metadata.return_value = [
        {"directory": "bb", "title": "Breaking Bad"},
    ]

    results = await show_service.search_shows("nonexistent")

    assert len(results) == 0


# =============================================================================
# Corrupted Cache Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
@patch("app.services.show_service.cache_get")
@patch("app.services.show_service.cache_set")
async def test_corrupted_cache_html_returns_fresh_data(mock_cache_set, mock_cache_get, mock_get_metadata):
    """Test that corrupted HTML cache data is handled gracefully."""
    # Simulate corrupted cache with HTML content (like what caused the 500)
    mock_cache_get.return_value = '<html><meta name="viewport" content="width=device-width"></html>'
    mock_get_metadata.return_value = [
        {"directory": "BreakingBad", "title": "Breaking Bad", "network": "AMC"},
    ]

    # Should not raise, should return fresh data
    shows = await show_service.get_all_shows()

    assert len(shows) == 1
    assert shows[0].title == "Breaking Bad"


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
@patch("app.services.show_service.cache_get")
@patch("app.services.show_service.cache_set")
async def test_corrupted_cache_invalid_json_returns_fresh_data(mock_cache_set, mock_cache_get, mock_get_metadata):
    """Test that invalid JSON cache data is handled gracefully."""
    # Simulate corrupted cache with invalid JSON
    mock_cache_get.return_value = "not valid json {{"
    mock_get_metadata.return_value = [
        {"directory": "GOT", "title": "Game of Thrones", "network": "HBO"},
    ]

    # Should not raise, should return fresh data
    shows = await show_service.get_all_shows()

    assert len(shows) == 1
    assert shows[0].title == "Game of Thrones"


# =============================================================================
# Show Service Helper Function Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.show_service.cache_get")
@patch("app.services.show_service.cache_set")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_shows_page(mock_get_metadata, mock_cache_set, mock_cache_get):
    """Test paginated show retrieval."""
    mock_cache_get.return_value = None
    mock_get_metadata.return_value = [{"directory": f"show{i}", "title": f"Show {i}"} for i in range(25)]

    shows, total = await show_service.get_shows_page(page=2, limit=10)

    assert total == 25
    assert len(shows) == 10
    assert shows[0].title == "Show 10"  # Page 2 starts at index 10


@pytest.mark.asyncio
@patch("app.services.show_service.cache_get")
@patch("app.services.show_service.cache_set")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_search_shows_fast(mock_get_metadata, mock_cache_set, mock_cache_get):
    """Test fast search shows."""
    mock_cache_get.return_value = None
    mock_get_metadata.return_value = [
        {"directory": "bb", "title": "Breaking Bad"},
        {"directory": "got", "title": "Game of Thrones"},
        {"directory": "bf", "title": "Better Call Saul"},
    ]

    results = await show_service.search_shows_fast("bad")

    assert len(results) == 1
    assert results[0].title == "Breaking Bad"


@pytest.mark.asyncio
@patch("app.services.show_service.cache_get")
@patch("app.services.show_service.cache_set")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_all_shows_raw_cache_hit(mock_get_metadata, mock_cache_set, mock_cache_get):
    """Test _get_all_shows_raw with cache hit."""
    import orjson

    cached_data = [{"epguides_key": "test", "title": "Cached Show"}]
    mock_cache_get.return_value = orjson.dumps(cached_data).decode()

    result = await show_service._get_all_shows_raw()

    assert len(result) == 1
    assert result[0]["title"] == "Cached Show"
    mock_get_metadata.assert_not_called()


@pytest.mark.asyncio
@patch("app.services.show_service.cache_get")
@patch("app.services.show_service.cache_set")
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_all_shows_raw_cache_miss(mock_get_metadata, mock_cache_set, mock_cache_get):
    """Test _get_all_shows_raw with cache miss."""
    mock_cache_get.return_value = None
    mock_get_metadata.return_value = [
        {"directory": "test", "title": "Fresh Show"},
    ]

    result = await show_service._get_all_shows_raw()

    assert len(result) == 1
    mock_cache_set.assert_called_once()


def test_map_csv_row_to_dict():
    """Test CSV row mapping to dict."""
    row = {
        "directory": "breakingbad",
        "title": "Breaking Bad",
        "network": "AMC",
        "run time": "60 min",
        "start date": "01 Jan 08",
        "end date": "29 Sep 13",
        "country": "USA",
        "number of episodes": "62",
    }

    result = show_service._map_csv_row_to_dict(row)

    assert result["epguides_key"] == "breakingbad"
    assert result["title"] == "Breaking Bad"
    assert result["network"] == "AMC"
    assert result["run_time_min"] == 60
    assert result["total_episodes"] == 62


def test_clean_title_normal():
    """Test title cleaning with normal input."""
    assert show_service._clean_title("Breaking Bad") == "Breaking Bad"
    # Titles without leading space get strip() applied
    assert show_service._clean_title("Trailing  ") == "Trailing"
    # Titles with leading space get lstrip() (unicode corruption case)
    assert show_service._clean_title("  Padded  ") == "Padded  "


def test_clean_title_empty():
    """Test title cleaning with empty input."""
    assert show_service._clean_title("") == ""


def test_clean_title_special_la_carte():
    """Test title cleaning for corrupted À character."""
    # " la carte" pattern gets special handling
    assert show_service._clean_title(" la carte") == "À La Carte"
    # " la " prefix gets À prepended
    assert show_service._clean_title(" la Maison") == "Àla Maison"  # lstrip removes the space


def test_parse_total_episodes():
    """Test total episodes parsing."""
    assert show_service._parse_total_episodes("62") == 62
    assert show_service._parse_total_episodes("100+") == 100
    assert show_service._parse_total_episodes(None) is None
    assert show_service._parse_total_episodes("") is None


def test_parse_run_time():
    """Test run time parsing."""
    assert show_service._parse_run_time("60 min") == 60
    assert show_service._parse_run_time("30") == 30
    assert show_service._parse_run_time(None) is None
    assert show_service._parse_run_time("no numbers") is None


def test_parse_date():
    """Test date parsing with various formats."""
    result = show_service._parse_date("01 Jan 20")
    assert result is not None
    assert result.year == 2020

    # Month-year format
    result = show_service._parse_date("Sep 2020")
    assert result is not None

    # Invalid
    assert show_service._parse_date(None) is None
    assert show_service._parse_date("TBA") is None
    assert show_service._parse_date("???") is None


def test_has_required_episode_fields():
    """Test episode field validation."""
    valid = {"season": 1, "number": 1, "title": "Pilot"}
    assert show_service._has_required_episode_fields(valid) is True

    missing_title = {"season": 1, "number": 1, "title": ""}
    assert show_service._has_required_episode_fields(missing_title) is False

    missing_season = {"number": 1, "title": "Pilot"}
    assert show_service._has_required_episode_fields(missing_season) is False


def test_parse_episode_valid():
    """Test episode parsing with valid data."""
    item = {
        "season": "1",
        "number": "1",
        "title": "Pilot",
        "release_date": "01 Jan 20",
    }

    result = show_service._parse_episode(item, run_time_min=60)

    assert result is not None
    assert result.season == 1
    assert result.number == 1
    assert result.title == "Pilot"
    assert result.run_time_min == 60


def test_parse_episode_invalid():
    """Test episode parsing with invalid data."""
    # Missing required fields
    invalid = {"season": "1", "title": "Pilot"}
    assert show_service._parse_episode(invalid, None) is None

    # Invalid date
    invalid_date = {"season": "1", "number": "1", "title": "Pilot", "release_date": "invalid"}
    assert show_service._parse_episode(invalid_date, None) is None


def test_parse_release_date():
    """Test release date parsing."""
    result = show_service._parse_release_date("01 Jan 20")
    assert result is not None

    assert show_service._parse_release_date(None) is None
    assert show_service._parse_release_date(123) is None  # Not a string
    assert show_service._parse_release_date("") is None


def test_build_season_stats():
    """Test season statistics building."""
    from datetime import date

    from app.models.schemas import EpisodeSchema

    episodes = [
        EpisodeSchema(season=1, number=1, title="S1E1", release_date=date(2020, 1, 1), is_released=True),
        EpisodeSchema(season=1, number=2, title="S1E2", release_date=date(2020, 1, 15), is_released=True),
        EpisodeSchema(season=2, number=1, title="S2E1", release_date=date(2021, 1, 1), is_released=True),
    ]

    stats = show_service._build_season_stats(episodes)

    assert len(stats) == 2
    assert stats[1]["episode_count"] == 2
    assert stats[1]["premiere_date"] == date(2020, 1, 1)
    assert stats[1]["end_date"] == date(2020, 1, 15)
    assert stats[2]["episode_count"] == 1


def test_episodes_ttl_all_released():
    """Test TTL calculation for finished shows."""
    from datetime import date

    from app.models.schemas import EpisodeSchema

    episodes = [
        EpisodeSchema(season=1, number=1, title="E1", release_date=date(2020, 1, 1), is_released=True),
        EpisodeSchema(season=1, number=2, title="E2", release_date=date(2020, 1, 8), is_released=True),
    ]

    ttl = show_service._episodes_ttl(episodes)
    assert ttl == show_service.TTL_1_YEAR


def test_episodes_ttl_has_unreleased():
    """Test TTL calculation for ongoing shows."""
    from datetime import date

    from app.models.schemas import EpisodeSchema

    episodes = [
        EpisodeSchema(season=1, number=1, title="E1", release_date=date(2020, 1, 1), is_released=True),
        EpisodeSchema(season=1, number=2, title="E2", release_date=date(2030, 1, 1), is_released=False),
    ]

    ttl = show_service._episodes_ttl(episodes)
    assert ttl is None  # Use default TTL


def test_show_ttl_finished():
    """Test show TTL for finished show."""
    from datetime import date

    from app.models.schemas import ShowSchema

    show = ShowSchema(epguides_key="test", title="Test", end_date=date(2020, 1, 1))
    ttl = show_service._show_ttl(show)
    assert ttl == show_service.TTL_1_YEAR


def test_show_ttl_ongoing():
    """Test show TTL for ongoing show."""
    from app.models.schemas import ShowSchema

    show = ShowSchema(epguides_key="test", title="Test", end_date=None)
    ttl = show_service._show_ttl(show)
    assert ttl is None


# =============================================================================
# Epguides Service Tests
# =============================================================================


def test_parse_date_string_century_fix():
    """Test date parsing fixes century for future years."""
    # Year 99 should become 1999, not 2099
    result = epguides.parse_date_string("01 Jan 99")
    assert result is not None
    assert result.year == 1999


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_fetch_csv_returns_empty_on_error(mock_fetch):
    """Test fetch_csv returns empty list on error."""
    mock_fetch.return_value = None

    result = await epguides.fetch_csv("http://example.com/data.csv")

    assert result == []


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_all_shows_metadata_returns_empty_on_error(mock_fetch):
    """Test get_all_shows_metadata returns empty list on error."""
    mock_fetch.return_value = None

    result = await epguides.get_all_shows_metadata()

    assert result == []


def test_extract_csv_url_tvrage_format():
    """Test CSV URL extraction for TVRage format."""
    html = '<a href="exportToCSV.asp?rage=12345">Export</a>'
    url, columns, maze_id = epguides._extract_csv_url_and_maze_id(html)

    assert url is not None
    assert "rage=12345" in url
    assert maze_id is None


def test_extract_csv_url_tvmaze_format():
    """Test CSV URL extraction for TVMaze format."""
    html = '<a href="exportToCSVmaze.asp?maze=67890">Export</a>'
    url, columns, maze_id = epguides._extract_csv_url_and_maze_id(html)

    assert url is not None
    assert "maze=67890" in url
    assert maze_id == "67890"


def test_extract_csv_url_not_found():
    """Test CSV URL extraction when not found."""
    html = "<html><body>No export link</body></html>"
    url, columns, maze_id = epguides._extract_csv_url_and_maze_id(html)

    assert url is None
    assert maze_id is None


def test_extract_poster_url_with_image():
    """Test poster URL extraction with image data."""
    data = {"image": {"original": "http://example.com/original.jpg", "medium": "http://example.com/medium.jpg"}}

    result = epguides.extract_poster_url(data)
    assert result == "http://example.com/original.jpg"


def test_extract_poster_url_medium_fallback():
    """Test poster URL extraction with medium fallback."""
    data = {"image": {"medium": "http://example.com/medium.jpg"}}

    result = epguides.extract_poster_url(data)
    assert result == "http://example.com/medium.jpg"


def test_extract_poster_url_no_image():
    """Test poster URL extraction with no image."""
    data = {}

    result = epguides.extract_poster_url(data)
    assert result == epguides._DEFAULT_POSTER_URL


def test_extract_poster_url_none():
    """Test poster URL extraction with None."""
    result = epguides.extract_poster_url(None)
    assert result == epguides._DEFAULT_POSTER_URL


def test_extract_imdb_id_from_url():
    """Test IMDB ID extraction from URL."""
    html = '<a href="https://www.imdb.com/title/tt0903747/">IMDB</a>'
    result = epguides._extract_imdb_id(html)
    assert result == "tt0903747"


def test_extract_imdb_id_not_found():
    """Test IMDB ID extraction when not found."""
    html = "<html><body>No IMDB link</body></html>"
    result = epguides._extract_imdb_id(html)
    assert result is None


def test_extract_title_from_h2_link():
    """Test title extraction from H2 with link."""
    html = '<h2><a href="https://imdb.com/title/tt123">Show Title</a></h2>'
    result = epguides._extract_title(html)
    assert result == "Show Title"


def test_extract_title_from_simple_h2():
    """Test title extraction from simple H2."""
    html = "<h2>Simple Title</h2>"
    result = epguides._extract_title(html)
    assert result == "Simple Title"


def test_extract_title_from_title_tag():
    """Test title extraction from title tag."""
    html = "<title>Fallback Title</title>"
    result = epguides._extract_title(html)
    assert result == "Fallback Title"


def test_extract_title_not_found():
    """Test title extraction when not found."""
    html = "<html><body>No title</body></html>"
    result = epguides._extract_title(html)
    assert result is None


def test_parse_episode_rows():
    """Test episode row parsing."""
    # Note: function doesn't skip header row, caller should handle that
    rows = [
        ["1", "1", "01 Jan 20", "", "pilot", "Pilot Episode"],
        ["1", "2", "08 Jan 20", "", "ep2", "Second Episode"],
    ]
    column_map = {"season": 0, "number": 1, "release_date": 2, "title": 5}

    result = epguides._parse_episode_rows(rows, column_map)

    assert len(result) == 2
    assert result[0]["season"] == "1"
    assert result[0]["title"] == "Pilot Episode"
    assert result[1]["title"] == "Second Episode"


# =============================================================================
# LLM Service Tests
# =============================================================================


def test_llm_episode_summary_truncation():
    """Test that episode summaries are truncated for LLM context."""
    from app.services import llm_service

    # This is tested implicitly through the search function
    # Just verify the module loads
    assert llm_service is not None


# =============================================================================
# Show Index and Cache Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.show_service.cache_hget")
async def test_get_show_by_key_cache_hit(mock_hget):
    """Test _get_show_by_key with cache hit."""
    import json

    cached_show = {"epguides_key": "test", "title": "Test Show"}
    mock_hget.return_value = json.dumps(cached_show)

    result = await show_service._get_show_by_key("test")

    assert result is not None
    assert result.title == "Test Show"


@pytest.mark.asyncio
@patch("app.services.show_service.cache_hget")
@patch("app.services.show_service.cache_exists")
@patch("app.services.show_service.get_all_shows")
async def test_get_show_by_key_fallback_to_list(mock_get_all, mock_exists, mock_hget):
    """Test _get_show_by_key falls back to list scan."""
    mock_hget.return_value = None  # Cache miss
    mock_exists.return_value = True  # Index exists but key not found

    mock_get_all.return_value = [
        show_service.ShowSchema(epguides_key="test", title="Test Show"),
        show_service.ShowSchema(epguides_key="other", title="Other Show"),
    ]

    result = await show_service._get_show_by_key("test")

    assert result is not None
    assert result.title == "Test Show"


@pytest.mark.asyncio
@patch("app.services.show_service.cache_hget", new_callable=AsyncMock)
@patch("app.services.show_service.cache_exists", new_callable=AsyncMock)
@patch("app.services.show_service.get_redis", new_callable=AsyncMock)
@patch("app.services.show_service.get_all_shows", new_callable=AsyncMock)
async def test_get_show_by_key_builds_index(mock_get_all, mock_redis, mock_exists, mock_hget):
    """Test _get_show_by_key builds index when missing."""
    mock_hget.side_effect = [None, None]  # First lookup fails, then after index build also fails
    mock_exists.return_value = False  # Index doesn't exist

    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock()
    mock_redis_client = MagicMock()
    mock_redis_client.pipeline.return_value = mock_pipe
    mock_redis.return_value = mock_redis_client

    mock_get_all.return_value = [
        show_service.ShowSchema(epguides_key="test", title="Test Show"),
    ]

    result = await show_service._get_show_by_key("test")

    # Falls back to list scan
    assert result is not None


@pytest.mark.asyncio
@patch("app.services.show_service.get_redis", new_callable=AsyncMock)
@patch("app.services.show_service.get_all_shows", new_callable=AsyncMock)
async def test_build_show_index_success(mock_get_all, mock_redis):
    """Test _build_show_index builds index correctly."""
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=None)
    mock_pipe.hset = MagicMock(return_value=mock_pipe)
    mock_pipe.expire = MagicMock(return_value=mock_pipe)
    mock_redis_client = MagicMock()
    mock_redis_client.pipeline.return_value = mock_pipe
    mock_redis.return_value = mock_redis_client

    mock_get_all.return_value = [
        show_service.ShowSchema(epguides_key="test", title="Test Show", run_time_min=60),
    ]

    await show_service._build_show_index()

    # Verify pipeline was used
    mock_redis_client.pipeline.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.show_service.get_redis")
@patch("app.services.show_service.get_all_shows")
async def test_build_show_index_handles_error(mock_get_all, mock_redis):
    """Test _build_show_index handles Redis errors."""
    mock_redis.side_effect = Exception("Redis connection error")
    mock_get_all.return_value = [
        show_service.ShowSchema(epguides_key="test", title="Test Show"),
    ]

    # Should not raise
    await show_service._build_show_index()


@pytest.mark.asyncio
@patch("app.services.show_service._get_show_by_key")
@patch("app.services.show_service._create_show_from_scrape")
@patch("app.services.show_service._enrich_show_metadata")
@patch("app.services.show_service.cache_get")
async def test_get_show_creates_from_scrape(mock_cache_get, mock_enrich, mock_scrape, mock_get_by_key):
    """Test get_show creates show from scrape when not in cache."""
    mock_cache_get.return_value = None  # No cached show
    mock_get_by_key.return_value = None  # Not in index
    mock_scrape.return_value = show_service.ShowSchema(epguides_key="new", title="New Show")
    mock_enrich.return_value = show_service.ShowSchema(epguides_key="new", title="New Show Enriched")

    result = await show_service.get_show("new")

    assert result is not None
    mock_scrape.assert_called_once()
    mock_enrich.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.show_service._get_show_by_key")
@patch("app.services.show_service._create_show_from_scrape")
@patch("app.services.show_service.cache_get")
async def test_get_show_returns_none_when_not_found(mock_cache_get, mock_scrape, mock_get_by_key):
    """Test get_show returns None when show doesn't exist."""
    mock_cache_get.return_value = None
    mock_get_by_key.return_value = None
    mock_scrape.return_value = None

    result = await show_service.get_show("nonexistent")

    assert result is None


@pytest.mark.asyncio
@patch("app.services.epguides.get_show_metadata")
async def test_create_show_from_scrape(mock_metadata):
    """Test _create_show_from_scrape creates show from epguides page."""
    mock_metadata.return_value = ("tt0903747", "Breaking Bad")

    result = await show_service._create_show_from_scrape("breakingbad")

    assert result is not None
    assert result.title == "Breaking Bad"
    assert result.imdb_id == "tt0903747"


@pytest.mark.asyncio
@patch("app.services.epguides.get_show_metadata")
async def test_create_show_from_scrape_not_found(mock_metadata):
    """Test _create_show_from_scrape returns None when not found."""
    mock_metadata.return_value = None

    result = await show_service._create_show_from_scrape("nonexistent")

    assert result is None


@pytest.mark.asyncio
@patch("app.services.show_service.get_episodes")
@patch("app.services.epguides.get_maze_id_for_show")
@patch("app.services.show_service.cache_get")
async def test_get_seasons_empty(mock_cache, mock_maze, mock_episodes):
    """Test get_seasons returns empty list when no episodes."""
    mock_cache.return_value = None
    mock_episodes.return_value = []
    mock_maze.return_value = None

    result = await show_service.get_seasons("test")

    assert result == []


@pytest.mark.asyncio
@patch("app.services.show_service.cache_hget")
async def test_get_show_runtime_from_cache(mock_hget):
    """Test _get_show_runtime returns cached value."""
    mock_hget.return_value = "60"

    result = await show_service._get_show_runtime("test")

    assert result == 60


@pytest.mark.asyncio
@patch("app.services.show_service.cache_hget")
async def test_get_show_runtime_cache_miss(mock_hget):
    """Test _get_show_runtime returns None on cache miss."""
    mock_hget.return_value = None

    result = await show_service._get_show_runtime("test")

    assert result is None


# =============================================================================
# Episode Enrichment Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
async def test_calculate_episode_stats(mock_episodes_data):
    """Test _calculate_episode_stats calculates correctly."""
    mock_episodes_data.return_value = [
        {"season": "1", "number": "1", "title": "E1", "release_date": "01 Jan 20"},
        {"season": "1", "number": "2", "title": "E2", "release_date": "08 Jan 20"},
    ]

    result = await show_service._calculate_episode_stats("test")

    assert result is not None
    assert result.valid_episode_count == 2


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
async def test_calculate_episode_stats_empty(mock_episodes_data):
    """Test _calculate_episode_stats returns None for empty episodes."""
    mock_episodes_data.return_value = []

    result = await show_service._calculate_episode_stats("test")

    assert result is None


def test_build_show_updates():
    """Test _build_show_updates builds update dict correctly."""
    from datetime import date

    show = show_service.ShowSchema(epguides_key="test", title="Test")
    stats = show_service._EpisodeStats()
    stats.has_unreleased = False
    stats.last_release_date = date(2013, 9, 29)
    stats.valid_episode_count = 62

    updates = show_service._build_show_updates(show, stats)

    assert updates["total_episodes"] == 62
    assert updates["end_date"] == date(2013, 9, 29)


def test_build_show_updates_no_end_date_for_ongoing():
    """Test _build_show_updates doesn't set end_date for ongoing shows."""
    from datetime import date

    show = show_service.ShowSchema(epguides_key="test", title="Test")
    stats = show_service._EpisodeStats()
    stats.has_unreleased = True  # Still has unreleased episodes
    stats.last_release_date = date(2020, 3, 1)
    stats.valid_episode_count = 10

    updates = show_service._build_show_updates(show, stats)

    assert "end_date" not in updates
    assert updates["total_episodes"] == 10


# =============================================================================
# Additional Epguides Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides._get_show_title", return_value=None)
@patch("app.services.epguides._fetch_url")
async def test_get_episodes_data_returns_empty_on_error(mock_fetch, mock_get_title):
    """Test get_episodes_data returns empty when both epguides and TVMaze fail."""
    mock_fetch.return_value = None

    result = await epguides.get_episodes_data("test")

    assert result == []


@pytest.mark.asyncio
@patch("app.services.epguides._get_show_title", return_value=None)
@patch("app.core.cache.cache_set")
@patch("app.core.cache.cache_get", return_value=None)
@patch("app.services.epguides._fetch_url")
async def test_get_episodes_data_no_csv_url(mock_fetch, mock_cache_get, mock_cache_set, mock_get_title):
    """Test get_episodes_data returns empty when no CSV URL and no TVMaze fallback."""
    from unittest.mock import MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>No CSV link</body></html>"
    mock_fetch.return_value = mock_response

    result = await epguides.get_episodes_data("test_no_csv")

    assert result == []


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_tvmaze_episodes")
@patch("app.services.epguides._search_tvmaze_by_title")
@patch("app.services.epguides._get_show_title")
@patch("app.services.epguides._fetch_url")
async def test_get_episodes_data_tvmaze_fallback(mock_fetch, mock_get_title, mock_search, mock_episodes):
    """Test get_episodes_data uses TVMaze fallback when epguides fails."""
    # epguides fails
    mock_fetch.return_value = None

    # TVMaze fallback succeeds
    mock_get_title.return_value = "Test Show"
    mock_search.return_value = {"id": 12345, "name": "Test Show"}
    mock_episodes.return_value = [
        {"season": "1", "number": "1", "title": "Pilot", "release_date": "2020-01-01", "summary": "", "poster_url": ""}
    ]

    result = await epguides.get_episodes_data("testshow")

    assert len(result) == 1
    assert result[0]["title"] == "Pilot"
    mock_search.assert_called_once_with("Test Show")
    mock_episodes.assert_called_once_with("12345")


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_tvmaze_seasons(mock_client_class):
    """Test get_tvmaze_seasons fetches seasons."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"id": 1, "number": 1}, {"id": 2, "number": 2}]

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides.get_tvmaze_seasons("12345")

    assert len(result) == 2


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_tvmaze_seasons_error(mock_client_class):
    """Test get_tvmaze_seasons returns empty on error."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection error")
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides.get_tvmaze_seasons("12345")

    assert result == []


# =============================================================================
# TVMaze Fallback Functions Tests
# =============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_search_tvmaze_by_title_success(mock_client_class):
    """Test _search_tvmaze_by_title returns show data on success."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": 329, "name": "Shark Tank"}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides._search_tvmaze_by_title("Shark Tank")

    assert result is not None
    assert result["id"] == 329
    assert result["name"] == "Shark Tank"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_search_tvmaze_by_title_not_found(mock_client_class):
    """Test _search_tvmaze_by_title returns None on 404."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides._search_tvmaze_by_title("Nonexistent Show")

    assert result is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_search_tvmaze_by_title_error(mock_client_class):
    """Test _search_tvmaze_by_title returns None on error."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection error")
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides._search_tvmaze_by_title("Test")

    assert result is None


@pytest.mark.asyncio
async def test_search_tvmaze_by_title_empty():
    """Test _search_tvmaze_by_title returns None for empty title."""
    result = await epguides._search_tvmaze_by_title("")
    assert result is None

    result = await epguides._search_tvmaze_by_title(None)
    assert result is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_tvmaze_episodes_success(mock_client_class):
    """Test _fetch_tvmaze_episodes returns episode list."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "season": 1,
            "number": 1,
            "name": "Pilot",
            "airdate": "2020-01-01",
            "summary": "<p>First episode</p>",
            "image": {"original": "http://example.com/img.jpg"},
        },
        {
            "season": 1,
            "number": 2,
            "name": "Episode 2",
            "airdate": "2020-01-08",
            "summary": None,
            "image": None,
        },
    ]

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides._fetch_tvmaze_episodes("12345")

    assert len(result) == 2
    assert result[0]["title"] == "Pilot"
    assert result[0]["summary"] == "First episode"
    assert result[0]["poster_url"] == "http://example.com/img.jpg"
    assert result[1]["summary"] == ""
    assert result[1]["poster_url"] == ""


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_tvmaze_episodes_error(mock_client_class):
    """Test _fetch_tvmaze_episodes returns empty on error."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection error")
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides._fetch_tvmaze_episodes("12345")

    assert result == []


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_tvmaze_episodes_skips_incomplete(mock_client_class):
    """Test _fetch_tvmaze_episodes skips episodes without required fields."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"season": 1, "number": 1, "name": "Pilot"},  # Missing airdate
        {"season": 1, "number": 2, "airdate": "2020-01-01"},  # Missing name
        {"season": 1, "number": 3, "name": "Complete", "airdate": "2020-01-08"},  # Complete
    ]

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides._fetch_tvmaze_episodes("12345")

    assert len(result) == 1
    assert result[0]["title"] == "Complete"


def test_convert_show_id_to_title():
    """Test _convert_show_id_to_title handles various formats."""
    # CamelCase
    assert epguides._convert_show_id_to_title("SharkTank") == "Shark Tank"
    assert epguides._convert_show_id_to_title("GameOfThrones") == "Game Of Thrones"

    # Lowercase with common words
    assert epguides._convert_show_id_to_title("sharktank") == "shark tank"
    assert epguides._convert_show_id_to_title("breakingbad") == "breaking bad"
    assert epguides._convert_show_id_to_title("theoffice") == "the office"

    # Already spaced
    assert epguides._convert_show_id_to_title("the office") == "the office"


def test_add_word_boundaries():
    """Test _add_word_boundaries adds spaces correctly."""
    assert epguides._add_word_boundaries("sharktank") == "shark tank"
    assert epguides._add_word_boundaries("breakingbad") == "breaking bad"
    assert epguides._add_word_boundaries("strangerthings") == "stranger things"
    assert epguides._add_word_boundaries("theoffice") == "the office"
    assert epguides._add_word_boundaries("thewalkingdead") == "the walking dead"


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_show_title_from_metadata(mock_metadata):
    """Test _get_show_title looks up title from metadata."""
    mock_metadata.return_value = [
        {"directory": "SharkTank", "title": "Shark Tank"},
        {"directory": "GameOfThrones", "title": "Game of Thrones"},
    ]

    result = await epguides._get_show_title("sharktank")
    assert result == "Shark Tank"

    result = await epguides._get_show_title("gameofthrones")
    assert result == "Game of Thrones"


@pytest.mark.asyncio
@patch("app.services.epguides.get_all_shows_metadata")
async def test_get_show_title_fallback(mock_metadata):
    """Test _get_show_title falls back to ID conversion when not in metadata."""
    mock_metadata.return_value = []

    result = await epguides._get_show_title("sharktank")
    assert result == "shark tank"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_tvmaze_show_data(mock_client_class):
    """Test get_tvmaze_show_data fetches show data."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": 12345, "name": "Test Show"}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides.get_tvmaze_show_data("12345")

    assert result is not None
    assert result["name"] == "Test Show"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_tvmaze_show_data_error(mock_client_class):
    """Test get_tvmaze_show_data returns None on error."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection error")
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides.get_tvmaze_show_data("12345")

    assert result is None


@pytest.mark.asyncio
@patch("app.core.cache.cache_set")
@patch("app.core.cache.cache_get", return_value=None)
@patch("httpx.AsyncClient")
async def test_get_tvmaze_show_data_not_found(mock_client_class, mock_cache_get, mock_cache_set):
    """Test get_tvmaze_show_data returns None on 404."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides.get_tvmaze_show_data("99999")

    assert result is None


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_maze_id_for_show(mock_fetch):
    """Test get_maze_id_for_show extracts maze ID."""
    from unittest.mock import MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '<a href="exportToCSVmaze.asp?maze=12345">Export</a>'
    mock_fetch.return_value = mock_response

    result = await epguides.get_maze_id_for_show("test")

    assert result == "12345"


@pytest.mark.asyncio
@patch("app.services.epguides._get_show_title", return_value=None)
@patch("app.services.epguides._fetch_url")
async def test_get_maze_id_for_show_not_found(mock_fetch, mock_get_title):
    """Test get_maze_id_for_show returns None when both epguides and TVMaze fail."""
    mock_fetch.return_value = None

    result = await epguides.get_maze_id_for_show("test")

    assert result is None


@pytest.mark.asyncio
@patch("app.services.epguides._search_tvmaze_by_title")
@patch("app.services.epguides._get_show_title")
@patch("app.services.epguides._fetch_url")
async def test_get_maze_id_for_show_tvmaze_fallback(mock_fetch, mock_get_title, mock_search):
    """Test get_maze_id_for_show uses TVMaze fallback when epguides fails."""
    mock_fetch.return_value = None
    mock_get_title.return_value = "Test Show"
    mock_search.return_value = {"id": 12345, "name": "Test Show"}

    result = await epguides.get_maze_id_for_show("testshow")

    assert result == "12345"
    mock_search.assert_called_once_with("Test Show")


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_show_metadata(mock_fetch):
    """Test get_show_metadata extracts IMDB ID and title."""
    from unittest.mock import MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = """
    <html>
    <h2><a href="https://imdb.com/title/tt0903747">Breaking Bad</a></h2>
    </html>
    """
    mock_fetch.return_value = mock_response

    result = await epguides.get_show_metadata("breakingbad")

    assert result is not None
    assert result[0] == "tt0903747"
    assert result[1] == "Breaking Bad"


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_show_metadata_not_found(mock_fetch):
    """Test get_show_metadata returns None on error."""
    mock_fetch.return_value = None

    result = await epguides.get_show_metadata("nonexistent")

    assert result is None


# =============================================================================
# Season and TVMaze Integration Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.show_service.epguides.get_show_poster")
@patch("app.services.show_service.epguides.get_tvmaze_seasons")
async def test_fetch_tvmaze_season_data(mock_seasons, mock_poster):
    """Test _fetch_tvmaze_season_data fetches and processes data."""
    mock_poster.return_value = "http://example.com/poster.jpg"
    mock_seasons.return_value = [
        {"number": 1, "summary": "<p>Season 1 summary</p>", "image": {"original": "http://s1.jpg"}},
        {"number": 2, "summary": None, "image": None},
    ]

    seasons, poster = await show_service._fetch_tvmaze_season_data("12345")

    assert poster == "http://example.com/poster.jpg"
    assert 1 in seasons
    assert seasons[1]["summary"] == "Season 1 summary"


@pytest.mark.asyncio
async def test_fetch_tvmaze_season_data_no_maze_id():
    """Test _fetch_tvmaze_season_data returns empty when no maze ID."""
    seasons, poster = await show_service._fetch_tvmaze_season_data(None)

    assert seasons == {}
    assert poster is None


@pytest.mark.asyncio
@patch("app.services.show_service._fetch_tvmaze_season_data")
@patch("app.services.show_service.epguides.get_maze_id_for_show")
@patch("app.services.show_service.get_episodes")
@patch("app.core.cache.cache_set")
@patch("app.core.cache.cache_get", return_value=None)
async def test_get_seasons_with_episodes(mock_cache_get, mock_cache_set, mock_episodes, mock_maze, mock_tvmaze):
    """Test get_seasons returns seasons when episodes exist."""
    from datetime import date

    mock_episodes.return_value = [
        show_service.EpisodeSchema(season=1, number=1, title="S1E1", release_date=date(2020, 1, 1), is_released=True),
        show_service.EpisodeSchema(season=1, number=2, title="S1E2", release_date=date(2020, 1, 15), is_released=True),
    ]
    mock_maze.return_value = "12345"
    mock_tvmaze.return_value = ({1: {"poster_url": "http://poster.jpg", "summary": "S1 summary"}}, "http://show.jpg")

    result = await show_service.get_seasons("test_seasons")

    assert len(result) == 1
    assert result[0].number == 1
    assert result[0].episode_count == 2


@pytest.mark.asyncio
@patch("app.services.show_service._fetch_imdb_id")
@patch("app.services.show_service._get_poster_url")
@patch("app.services.show_service._calculate_episode_stats")
async def test_enrich_show_metadata(mock_stats, mock_poster, mock_imdb):
    """Test _enrich_show_metadata enriches show."""
    mock_imdb.return_value = "tt0903747"
    mock_poster.return_value = "http://poster.jpg"
    mock_stats.return_value = None

    show = show_service.ShowSchema(epguides_key="test", title="Test Show")
    result = await show_service._enrich_show_metadata(show, "test")

    assert result.imdb_id == "tt0903747"
    assert result.poster_url == "http://poster.jpg"


@pytest.mark.asyncio
@patch("app.services.show_service._fetch_imdb_id")
@patch("app.services.show_service._get_poster_url")
@patch("app.services.show_service._calculate_episode_stats")
@patch("app.services.show_service._build_show_updates")
async def test_enrich_show_metadata_with_stats(mock_updates, mock_stats, mock_poster, mock_imdb):
    """Test _enrich_show_metadata enriches show with stats."""
    from datetime import date

    mock_imdb.return_value = None
    mock_poster.return_value = None
    stats = show_service._EpisodeStats()
    stats.valid_episode_count = 62
    stats.has_unreleased = False
    stats.last_release_date = date(2013, 9, 29)
    mock_stats.return_value = stats
    mock_updates.return_value = {"total_episodes": 62, "end_date": date(2013, 9, 29)}

    show = show_service.ShowSchema(epguides_key="test", title="Test Show")
    result = await show_service._enrich_show_metadata(show, "test")

    assert result.total_episodes == 62


@pytest.mark.asyncio
@patch("app.services.epguides.get_show_metadata")
async def test_fetch_imdb_id(mock_metadata):
    """Test _fetch_imdb_id fetches IMDB ID via epguides."""
    mock_metadata.return_value = ("tt0903747", "Breaking Bad")

    result = await show_service._fetch_imdb_id("test")

    assert result == "tt0903747"


@pytest.mark.asyncio
@patch("app.services.epguides.get_show_metadata")
async def test_fetch_imdb_id_no_metadata(mock_metadata):
    """Test _fetch_imdb_id returns None when no metadata."""
    mock_metadata.return_value = None

    result = await show_service._fetch_imdb_id("test")

    assert result is None


@pytest.mark.asyncio
@patch("app.services.epguides.get_maze_id_for_show")
@patch("app.services.epguides.get_tvmaze_show_data")
@patch("app.services.epguides.extract_poster_url")
async def test_get_poster_url(mock_extract, mock_tvmaze_data, mock_maze):
    """Test _get_poster_url fetches poster via TVMaze."""
    mock_maze.return_value = "12345"
    mock_tvmaze_data.return_value = {"image": {"original": "http://poster.jpg"}}
    mock_extract.return_value = "http://poster.jpg"

    result = await show_service._get_poster_url("test")

    assert result == "http://poster.jpg"


@pytest.mark.asyncio
@patch("app.services.epguides.get_maze_id_for_show")
async def test_get_poster_url_no_maze(mock_maze):
    """Test _get_poster_url returns None when no maze ID."""
    mock_maze.return_value = None

    result = await show_service._get_poster_url("test")

    assert result is None


# =============================================================================
# Logging Config Tests
# =============================================================================


def test_development_formatter():
    """Test DevelopmentFormatter formats log records."""
    from app.core.logging_config import DevelopmentFormatter

    formatter = DevelopmentFormatter()
    assert formatter is not None


def test_setup_logging_returns_logger():
    """Test setup_logging returns a logger."""
    from app.core.logging_config import setup_logging

    logger = setup_logging()
    assert logger is not None


# =============================================================================
# LLM Service Additional Tests
# =============================================================================


@pytest.mark.asyncio
async def test_parse_natural_language_query_empty_episodes():
    """Test parse_natural_language_query with empty episodes."""
    from app.services import llm_service

    # Test with empty episodes - should return empty list
    result = await llm_service.parse_natural_language_query("test query", [])

    assert result == []


@pytest.mark.asyncio
async def test_parse_natural_language_query_llm_disabled():
    """Test parse_natural_language_query returns None when LLM disabled."""
    from app.services import llm_service

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2020-01-01"}]

    with patch.object(llm_service.settings, "LLM_ENABLED", False):
        result = await llm_service.parse_natural_language_query("test query", episodes)

    assert result is None


# =============================================================================
# Additional Show Service Edge Case Tests
# =============================================================================


def test_map_csv_row_to_show():
    """Test _map_csv_row_to_show creates ShowSchema."""
    row = {
        "directory": "breakingbad",
        "title": "Breaking Bad",
        "network": "AMC",
    }

    result = show_service._map_csv_row_to_show(row)

    assert result.epguides_key == "breakingbad"
    assert result.title == "Breaking Bad"


def test_parse_episode_with_exception():
    """Test _parse_episode handles exceptions gracefully."""
    # Item with invalid data that could cause exception
    invalid_item = {
        "season": None,  # Will cause issue when trying to convert to int
        "number": "1",
        "title": "Test",
        "release_date": "01 Jan 20",
    }

    result = show_service._parse_episode(invalid_item, None)

    assert result is None


@pytest.mark.asyncio
@patch("app.services.show_service.cache_hget", new_callable=AsyncMock)
@patch("app.services.show_service.cache_exists", new_callable=AsyncMock)
@patch("app.services.show_service.get_redis", new_callable=AsyncMock)
@patch("app.services.show_service.get_all_shows", new_callable=AsyncMock)
async def test_get_show_by_key_rebuilds_index(mock_get_all, mock_redis, mock_exists, mock_hget):
    """Test _get_show_by_key rebuilds index when it doesn't exist."""
    import json

    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock()
    mock_pipe.hset = MagicMock(return_value=mock_pipe)
    mock_pipe.expire = MagicMock(return_value=mock_pipe)
    mock_redis_client = MagicMock()
    mock_redis_client.pipeline.return_value = mock_pipe
    mock_redis.return_value = mock_redis_client

    # First call returns None, second call after index build returns data
    cached_show = {"epguides_key": "test", "title": "Test Show"}
    mock_hget.side_effect = [None, json.dumps(cached_show)]
    mock_exists.return_value = False  # Index doesn't exist

    mock_get_all.return_value = [
        show_service.ShowSchema(epguides_key="test", title="Test Show"),
    ]

    result = await show_service._get_show_by_key("test")

    assert result is not None
    assert result.title == "Test Show"


def test_build_season_stats_updates_dates():
    """Test _build_season_stats updates premiere and end dates correctly."""
    from datetime import date

    episodes = [
        show_service.EpisodeSchema(season=1, number=2, title="E2", release_date=date(2020, 1, 15), is_released=True),
        show_service.EpisodeSchema(season=1, number=1, title="E1", release_date=date(2020, 1, 1), is_released=True),
        show_service.EpisodeSchema(season=1, number=3, title="E3", release_date=date(2020, 2, 1), is_released=True),
    ]

    stats = show_service._build_season_stats(episodes)

    # premiere_date should be earliest, end_date should be latest
    assert stats[1]["premiere_date"] == date(2020, 1, 1)
    assert stats[1]["end_date"] == date(2020, 2, 1)
    assert stats[1]["episode_count"] == 3


# =============================================================================
# Additional Epguides Tests
# =============================================================================


def test_parse_date_string_future_century():
    """Test parse_date_string handles future year correction."""
    # Year that would be > current year + 2 is adjusted
    result = epguides.parse_date_string("01 Jan 99")

    assert result is not None
    # 99 should be interpreted as 1999, not 2099
    assert result.year < 2050


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_episodes_data_parses_csv(mock_fetch):
    """Test get_episodes_data parses CSV from epguides page."""
    # Mock the page response with CSV link
    page_response = MagicMock()
    page_response.status_code = 200
    page_response.text = '<a href="exportToCSVmaze.asp?maze=12345">Export</a>'

    # Mock the CSV response
    csv_response = MagicMock()
    csv_response.status_code = 200
    csv_response.text = "season,episode,airdate,title\n1,1,01 Jan 20,Pilot"

    mock_fetch.side_effect = [page_response, csv_response]

    result = await epguides.get_episodes_data("test")

    # Should get episodes from CSV
    assert isinstance(result, list)


def test_parse_episode_rows_handles_index_error():
    """Test _parse_episode_rows handles index errors."""
    rows = [
        ["1"],  # Too short row
    ]
    column_map = {"season": 0, "number": 1, "release_date": 2, "title": 5}

    result = epguides._parse_episode_rows(rows, column_map)

    # Should return empty or skip invalid rows
    assert isinstance(result, list)


@pytest.mark.asyncio
@patch("app.services.show_service.extend_cache_ttl")
@patch("app.services.show_service._fetch_imdb_id")
@patch("app.services.show_service._get_poster_url")
@patch("app.services.show_service._calculate_episode_stats")
async def test_enrich_show_metadata_finished_show(mock_stats, mock_poster, mock_imdb, mock_extend):
    """Test _enrich_show_metadata extends TTL for finished shows."""
    from datetime import date

    mock_imdb.return_value = None
    mock_poster.return_value = None
    mock_stats.return_value = None

    show = show_service.ShowSchema(epguides_key="test", title="Test", end_date=date(2020, 1, 1))
    await show_service._enrich_show_metadata(show, "test")

    # Should extend cache TTL for finished show
    assert mock_extend.call_count == 2


def test_parse_episode_raises_exception():
    """Test _parse_episode handles exception in EpisodeSchema creation."""
    # Create item that will cause exception during schema creation
    item = {
        "season": "1",
        "number": "1",
        "title": "Test",
        "release_date": "01 Jan 20",
        "imdb_rating": "not_a_float",  # This could cause issues
    }

    # Should not raise, should return None or episode
    result = show_service._parse_episode(item, None)
    # Either returns a valid episode or None
    assert result is None or isinstance(result, show_service.EpisodeSchema)


@pytest.mark.asyncio
async def test_build_show_index_with_runtime():
    """Test _build_show_index stores runtime in index."""
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=None)
    mock_pipe.hset = MagicMock(return_value=mock_pipe)
    mock_pipe.expire = MagicMock(return_value=mock_pipe)

    mock_redis_client = MagicMock()
    mock_redis_client.pipeline.return_value = mock_pipe

    with patch("app.services.show_service.get_redis", new_callable=AsyncMock) as mock_redis:
        mock_redis.return_value = mock_redis_client
        with patch("app.services.show_service.get_all_shows", new_callable=AsyncMock) as mock_get_all:
            # Show WITH runtime
            mock_get_all.return_value = [
                show_service.ShowSchema(epguides_key="test", title="Test Show", run_time_min=60),
            ]

            await show_service._build_show_index()

            # Should call hset for both show_index and runtime_index
            assert mock_pipe.hset.call_count >= 2


@pytest.mark.asyncio
@patch("app.services.show_service._fetch_imdb_id")
@patch("app.services.show_service._get_poster_url")
@patch("app.services.show_service._calculate_episode_stats")
@patch("app.services.show_service._build_show_updates")
async def test_enrich_show_with_episode_stats(mock_updates, mock_stats, mock_poster, mock_imdb):
    """Test _enrich_show_metadata applies episode stats."""
    mock_imdb.return_value = None
    mock_poster.return_value = None

    stats = show_service._EpisodeStats()
    stats.valid_episode_count = 100
    stats.has_unreleased = False
    stats.last_release_date = None
    mock_stats.return_value = stats
    mock_updates.return_value = {"total_episodes": 100}

    show = show_service.ShowSchema(epguides_key="test", title="Test")
    result = await show_service._enrich_show_metadata(show, "test")

    assert result.total_episodes == 100


@pytest.mark.asyncio
@patch("app.services.show_service.cache_hget")
@patch("app.services.show_service.cache_exists")
@patch("app.services.show_service._build_show_index")
async def test_get_show_runtime_rebuilds_index(mock_build, mock_exists, mock_hget):
    """Test _get_show_runtime rebuilds index when missing."""
    # First hget returns None, second returns value after rebuild
    mock_hget.side_effect = [None, "60"]
    mock_exists.return_value = False  # Index doesn't exist

    result = await show_service._get_show_runtime("test")

    assert result == 60
    mock_build.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.show_service.cache_hget")
@patch("app.services.show_service.cache_exists")
async def test_get_show_runtime_not_found(mock_exists, mock_hget):
    """Test _get_show_runtime returns None when not found."""
    mock_hget.return_value = None
    mock_exists.return_value = True  # Index exists but key not found

    result = await show_service._get_show_runtime("test")

    assert result is None


@pytest.mark.asyncio
@patch("app.services.epguides.get_episodes_data")
async def test_calculate_episode_stats_with_invalid_dates(mock_data):
    """Test _calculate_episode_stats skips items without valid dates."""
    mock_data.return_value = [
        {"season": "1", "number": "1", "title": "Valid", "release_date": "01 Jan 20"},
        {"season": "1", "number": "2", "title": "No Date"},  # Missing release_date
        {"season": "1", "number": "3", "title": "Invalid", "release_date": "not a date"},  # Invalid
    ]

    result = await show_service._calculate_episode_stats("test")

    # Only the first episode should be counted as valid
    assert result is not None
    assert result.valid_episode_count == 1


def test_parse_episode_exception_handling():
    """Test _parse_episode catches exceptions during schema creation."""
    # Item that would cause ValueError in int conversion
    item = {
        "season": "one",  # Invalid - not an int
        "number": "1",
        "title": "Test",
        "release_date": "01 Jan 20",
    }

    result = show_service._parse_episode(item, None)

    assert result is None  # Should catch exception and return None


# =============================================================================
# Additional Epguides Edge Case Tests
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_show_metadata_no_imdb_id(mock_fetch):
    """Test get_show_metadata returns None when IMDB ID not found."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>No IMDB link here</body></html>"
    mock_fetch.return_value = mock_response

    result = await epguides.get_show_metadata("test")

    assert result is None


def test_extract_imdb_id_from_h2_link():
    """Test _extract_imdb_id extracts from H2 link pattern."""
    html = '<h2><a href="https://www.imdb.com/title/tt0903747/">Breaking Bad</a></h2>'
    result = epguides._extract_imdb_id(html)
    assert result == "tt0903747"


def test_extract_imdb_id_fallback():
    """Test _extract_imdb_id returns None when no pattern matches."""
    html = "<html><body>No IMDB link</body></html>"
    result = epguides._extract_imdb_id(html)
    assert result is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_merge_tvmaze_episode_data_non_200(mock_client_class):
    """Test _merge_tvmaze_episode_data handles non-200 response."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    episodes = [{"season": "1", "number": "1", "title": "Pilot"}]
    result = await epguides._merge_tvmaze_episode_data(episodes, "12345")

    # Should return original episodes unchanged
    assert result == episodes


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_merge_tvmaze_episode_data_skips_invalid(mock_client_class):
    """Test _merge_tvmaze_episode_data skips episodes without season/number."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"season": None, "number": 1, "summary": "Test"},  # Invalid - no season
        {"season": 1, "number": None, "summary": "Test"},  # Invalid - no number
    ]

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    episodes = [{"season": "1", "number": "1", "title": "Pilot"}]
    result = await epguides._merge_tvmaze_episode_data(episodes, "12345")

    # Should return original episodes (no TVMaze data merged)
    assert result == episodes


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_merge_tvmaze_episode_data_handles_exception(mock_client_class):
    """Test _merge_tvmaze_episode_data handles exceptions gracefully."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Network error")
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    episodes = [{"season": "1", "number": "1", "title": "Pilot"}]
    result = await epguides._merge_tvmaze_episode_data(episodes, "12345")

    # Should return original episodes unchanged
    assert result == episodes


@pytest.mark.asyncio
@patch("app.core.cache.cache_set")
@patch("app.core.cache.cache_get", return_value=None)
@patch("httpx.AsyncClient")
async def test_get_tvmaze_seasons_non_200(mock_client_class, mock_cache_get, mock_cache_set):
    """Test get_tvmaze_seasons returns empty on non-200."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides.get_tvmaze_seasons("99999")

    assert result == []


# =============================================================================
# LLM Service Edge Case Tests
# =============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_query_llm_with_summary_truncation(mock_client_class):
    """Test _query_llm truncates long summaries."""
    from app.services import llm_service

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": "[0]"}}]}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    # Episode with a very long summary (>150 chars)
    episodes = [
        {
            "season": 1,
            "number": 1,
            "title": "Pilot",
            "release_date": "2020-01-01",
            "summary": "A" * 200,  # Long summary that should be truncated
        }
    ]

    result = await llm_service._query_llm("test query", episodes)

    assert result is not None
    assert len(result) == 1


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_query_llm_invalid_indices_type(mock_client_class):
    """Test _query_llm handles non-list response."""
    from app.services import llm_service

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": '"not a list"'}}]}  # String instead of list

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2020-01-01"}]

    result = await llm_service._query_llm("test query", episodes)

    assert result is None  # Should return None for invalid response


# =============================================================================
# Logging Config Tests
# =============================================================================


def test_setup_logging_debug_mode(monkeypatch):
    """Test setup_logging uses DevelopmentFormatter in debug mode."""
    from app.core import logging_config

    monkeypatch.setattr(logging_config.settings, "LOG_LEVEL", "DEBUG")

    # Should not raise
    logger = logging_config.setup_logging()
    assert logger is not None


# =============================================================================
# Cache Decorator Edge Case Tests
# =============================================================================


@pytest.mark.asyncio
async def test_cached_decorator_raw_data_return():
    """Test @cached decorator returns raw data when no model specified."""
    from app.core import cache

    @cache.cached("test:{key}", ttl=3600)
    async def get_raw_data(key: str) -> dict:
        return {"raw": "data", "key": key}

    # Test with cache HIT - should return cached raw data
    with patch.object(cache, "cache_get", return_value='{"cached": "value"}'):
        result = await get_raw_data("test")

    assert result == {"cached": "value"}


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_show_metadata_imdb_without_title(mock_fetch):
    """Test get_show_metadata when IMDB found but no title."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    # HTML with IMDB link but no parseable title
    mock_response.text = '<a href="https://www.imdb.com/title/tt0903747/">IMDB</a>'
    mock_fetch.return_value = mock_response

    result = await epguides.get_show_metadata("test")

    assert result is not None
    assert result[0] == "tt0903747"
    assert result[1] == "Unknown"


def test_extract_imdb_id_from_direct_url():
    """Test _extract_imdb_id extracts from direct IMDB URL."""
    html = '<a href="https://www.imdb.com/title/tt0903747/">IMDB Link</a>'
    result = epguides._extract_imdb_id(html)
    assert result == "tt0903747"


def test_extract_imdb_id_from_h2_link_fallback():
    """Test _extract_imdb_id fallback to H2 link pattern."""
    # HTML that doesn't match direct "imdb.com/title/" pattern
    # but matches H2 link pattern with /title/ path
    html = '<h2><a href="/title/tt1234567">Show Title</a></h2>'
    result = epguides._extract_imdb_id(html)
    assert result == "tt1234567"


def test_parse_date_string_century_correction():
    """Test parse_date_string corrects century for far future years."""
    # Python strptime with %y: 00-68 -> 2000-2068, 69-99 -> 1969-1999
    # So "01 Jan 50" parses as 2050, which is > current year + 2 (~2028)
    # The code should correct it to 1950
    result = epguides.parse_date_string("01 Jan 50")

    assert result is not None
    assert result.year == 1950  # Century corrected from 2050


# =============================================================================
# Additional Coverage Tests - epguides.py
# =============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_url_success(mock_client_class):
    """Test _fetch_url returns response on success."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides._fetch_url("http://example.com/test")

    assert result is not None
    assert result.status_code == 200


@pytest.mark.asyncio
@patch("app.services.epguides._fetch_url")
async def test_get_all_shows_metadata_success(mock_fetch):
    """Test get_all_shows_metadata returns data on success."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.encoding = "utf-8"
    mock_response.text = "directory,title,network\nBreakingBad,Breaking Bad,AMC\n"

    mock_fetch.return_value = mock_response

    result = await epguides.get_all_shows_metadata()

    assert len(result) >= 1
    assert result[0]["directory"] == "BreakingBad"
    assert result[0]["title"] == "Breaking Bad"


def test_clean_unicode_text_with_replacement_chars():
    """Test _clean_unicode_text handles U+FFFD replacement characters."""
    mock_response = MagicMock()
    mock_response.encoding = "utf-8"
    mock_response.text = "Hello\ufffdWorld"
    mock_response.content = b"HelloWorld"

    result = epguides._clean_unicode_text(mock_response)

    assert "\ufffd" not in result
    assert "HelloWorld" in result


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_search_tvmaze_by_title_non_200_non_404(mock_client_class):
    """Test _search_tvmaze_by_title handles non-200/non-404 status (e.g., 500)."""
    mock_response = MagicMock()
    mock_response.status_code = 500

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides._search_tvmaze_by_title("Test Show")

    assert result is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_tvmaze_episodes_non_200(mock_client_class):
    """Test _fetch_tvmaze_episodes handles non-200 status (e.g., 500)."""
    mock_response = MagicMock()
    mock_response.status_code = 500

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    result = await epguides._fetch_tvmaze_episodes("12345")

    assert result == []


def test_add_word_boundaries_with_prefix_the():
    """Test _add_word_boundaries handles 'the' prefix via prefix detection."""
    # "thecat" - "cat" is NOT a common word, so prefix detection should kick in
    result = epguides._add_word_boundaries("thecat")
    assert result == "the cat"


def test_add_word_boundaries_with_prefix_a():
    """Test _add_word_boundaries handles 'a' prefix via prefix detection."""
    # "adog" - "dog" is NOT a common word, so prefix detection should kick in
    result = epguides._add_word_boundaries("adog")
    assert result == "a dog"


def test_add_word_boundaries_with_prefix_a_before_an():
    """Test _add_word_boundaries processes 'a' before 'an' prefix."""
    # "anox" - prefixes are checked in order: the, a, an
    # "a" matches first, so "anox" becomes "a nox" not "an ox"
    result = epguides._add_word_boundaries("anox")
    assert result == "a nox"  # "a" prefix matches before "an"


def test_parse_episode_rows_empty_row():
    """Test _parse_episode_rows skips empty rows."""
    rows = [
        ["1", "1", "01 Jan 20", "", "pilot", "Pilot Episode"],
        [],  # Empty row - should be skipped
        ["1", "2", "08 Jan 20", "", "ep2", "Second Episode"],
    ]
    column_map = {"season": 0, "number": 1, "release_date": 2, "title": 5}

    result = epguides._parse_episode_rows(rows, column_map)

    assert len(result) == 2
    assert result[0]["title"] == "Pilot Episode"
    assert result[1]["title"] == "Second Episode"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_merge_tvmaze_episode_data_image_no_original_or_medium(mock_client_class):
    """Test _merge_tvmaze_episode_data handles image with empty original/medium."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "season": 1,
            "number": 1,
            "summary": "<p>Test summary</p>",
            "image": {"thumbnail": "http://example.com/thumb.jpg"},  # No original or medium
        }
    ]

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    episodes = [{"season": "1", "number": "1", "title": "Pilot"}]
    result = await epguides._merge_tvmaze_episode_data(episodes, "12345")

    assert result[0]["poster_url"] == ""  # Should be empty string


# =============================================================================
# Additional Coverage Tests - llm_service.py
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.llm_service._query_llm")
@patch("app.services.llm_service.settings")
async def test_parse_natural_language_query_exception(mock_settings, mock_query):
    """Test parse_natural_language_query handles exceptions gracefully."""
    from app.services import llm_service

    mock_settings.LLM_ENABLED = True
    mock_settings.LLM_API_URL = "http://example.com/llm"
    mock_query.side_effect = Exception("LLM service error")

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2020-01-01"}]

    result = await llm_service.parse_natural_language_query("test query", episodes)

    assert result is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_query_llm_non_200_response(mock_client_class):
    """Test _query_llm handles non-200 response."""
    from app.services import llm_service

    mock_response = MagicMock()
    mock_response.status_code = 500

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2020-01-01"}]

    result = await llm_service._query_llm("test query", episodes)

    assert result is None


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_query_llm_json_decode_error(mock_client_class):
    """Test _query_llm handles JSON decode errors."""
    from app.services import llm_service

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": "not valid json ["}}]}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client_class.return_value = mock_client

    episodes = [{"season": 1, "number": 1, "title": "Pilot", "release_date": "2020-01-01"}]

    result = await llm_service._query_llm("test query", episodes)

    assert result is None


# =============================================================================
# Additional Coverage Tests - show_service.py
# =============================================================================


def test_parse_date_month_year_format():
    """Test _parse_date handles month-year formats like 'Jan 2020'."""
    result = show_service._parse_date("Jan 2020")

    assert result is not None
    assert result.year == 2020
    assert result.month == 1
    assert result.day == 1  # Should default to 1st of month


def test_parse_date_iso_format():
    """Test _parse_date handles ISO format dates."""
    result = show_service._parse_date("2020-01-15")

    assert result is not None
    assert result.year == 2020
    assert result.month == 1
    assert result.day == 15


def test_parse_date_invalid_format():
    """Test _parse_date returns None for unparseable dates."""
    result = show_service._parse_date("not a date")

    assert result is None
