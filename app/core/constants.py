"""
Application-wide constants.

Centralizes hardcoded values that should be consistent across the codebase.
These constants are immutable and should not be modified at runtime.
"""

EPGUIDES_BASE_URL = "http://www.epguides.com"
"""Base URL for epguides.com - the primary data source."""


MCP_PROTOCOL_VERSION = "2025-06-18"
"""Model Context Protocol version this server implements."""


def get_version() -> str:
    """
    Get application version (build number).

    Priority:
    1. VERSION file (auto-updated by pre-commit hook)
    2. APP_VERSION environment variable (for CI/Docker)
    3. Git commit count (fallback for local dev)
    4. "dev" fallback

    The version is a simple incrementing number based on commit count.
    """
    import os
    from pathlib import Path

    version_file = Path(__file__).parent.parent.parent / "VERSION"
    if version_file.exists():
        try:
            return version_file.read_text().strip()
        except Exception:
            pass

    env_version = os.environ.get("APP_VERSION")
    if env_version and env_version != "dev":
        return env_version

    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return "dev"


VERSION = get_version()


EPISODE_RELEASE_THRESHOLD_HOURS = 80
"""
Hours after airtime before an episode is considered 'released'.

This accounts for timezone differences and delayed availability.
Episodes that aired less than this many hours ago are marked as unreleased.
"""


DATE_FORMATS = (
    "%d %b %y",
    "%d/%b/%y",
    "%Y-%m-%d",
)
"""
Supported date format strings for parsing episode release dates.

Order matters - formats are tried in sequence until one succeeds.
"""


CACHE_TTL_SHOWS_METADATA_SECONDS = 2592000
"""Cache TTL for the master show list (new shows added infrequently)."""
