"""
Application-wide constants.

Centralizes hardcoded values that should be consistent across the codebase.
"""

# Epguides.com base URL
EPGUIDES_BASE_URL = "http://www.epguides.com"

# Application version (update this for releases)
VERSION = "2.2.0"

# MCP Protocol version
MCP_PROTOCOL_VERSION = "2024-11-05"

# Episode release threshold (hours)
# Episodes are considered "released" if they aired more than this many hours ago
EPISODE_RELEASE_THRESHOLD_HOURS = 80

# Date format strings for parsing
DATE_FORMATS = ["%d %b %y", "%d/%b/%y", "%Y-%m-%d"]
