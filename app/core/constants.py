"""
Application-wide constants.

Centralizes hardcoded values that should be consistent across the codebase.
These constants are immutable and should not be modified at runtime.
"""

# =============================================================================
# External Service URLs
# =============================================================================

EPGUIDES_BASE_URL = "http://www.epguides.com"
"""Base URL for epguides.com - the primary data source."""

# =============================================================================
# Versioning
# =============================================================================

VERSION = "2.2.0"
"""Application version (semver format). Update for releases."""

MCP_PROTOCOL_VERSION = "2024-11-05"
"""Model Context Protocol version this server implements."""

# =============================================================================
# Episode Configuration
# =============================================================================

EPISODE_RELEASE_THRESHOLD_HOURS = 80
"""
Hours after airtime before an episode is considered 'released'.

This accounts for timezone differences and delayed availability.
Episodes that aired less than this many hours ago are marked as unreleased.
"""

# =============================================================================
# Date Parsing
# =============================================================================

DATE_FORMATS = (
    "%d %b %y",  # e.g., "20 Jan 08"
    "%d/%b/%y",  # e.g., "20/Jan/08"
    "%Y-%m-%d",  # ISO format
)
"""
Supported date format strings for parsing episode release dates.

Order matters - formats are tried in sequence until one succeeds.
"""

# =============================================================================
# HTTP Configuration
# =============================================================================

HTTP_TIMEOUT_SECONDS = 5.0
"""Default timeout for HTTP requests to external services."""

# =============================================================================
# Caching Defaults
# =============================================================================

CACHE_TTL_SHOWS_METADATA_SECONDS = 86400  # 24 hours
"""Cache TTL for the master show list (rarely changes)."""
