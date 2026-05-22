"""
LLM-powered natural language episode search.

Uses an LLM to parse complex natural language queries that
simple regex patterns cannot handle.

Only used when LLM_ENABLED is True in settings.
"""

import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_THINK_TAG_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

# LLM configuration
_LLM_TIMEOUT_SECONDS = 30.0  # Longer timeout for processing episode summaries
_MAX_EPISODES_FOR_CONTEXT = 100  # Include more episodes since we have summaries


def _parse_allowed_hosts(value: str) -> frozenset[str]:
    """Parse comma-separated host allow-list into a frozenset of lowercase hostnames."""
    return frozenset(h.strip().lower() for h in value.split(",") if h.strip())


# Optional host allow-list. When set (comma-separated hostnames), only matching
# hosts are accepted for the LLM gateway URL. Empty/unset means no host
# enforcement — any configured `LLM_API_URL` is accepted. Override per-deployment
# by setting `ALLOWED_LLM_HOSTS` in the environment.
_ALLOWED_LLM_HOSTS = _parse_allowed_hosts(os.environ.get("ALLOWED_LLM_HOSTS", ""))


async def parse_natural_language_query(
    query: str,
    episodes: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """
    Use LLM to parse complex natural language queries.

    This function is useful for queries that can't be parsed with regex,
    such as:
    - "episodes where Walter dies"
    - "first half of season 3"
    - "episodes with ratings above 9.0"

    Args:
        query: Natural language search query.
        episodes: List of episode dictionaries to filter.

    Returns:
        Filtered episodes matching the query, or None if:
        - LLM is disabled
        - LLM API call fails
        - Query cannot be processed

    Note:
        Returns [] for empty episode lists regardless of LLM config.
    """
    # Fast path: empty episodes always returns empty
    if not episodes:
        return []

    # Check LLM configuration
    if not settings.LLM_ENABLED:
        logger.debug("LLM not enabled, skipping natural language parsing")
        return None

    base_url = _get_llm_base_url()
    if base_url is None:
        return None

    try:
        return await _query_llm(query, episodes, base_url=base_url)
    except Exception as e:
        logger.error("Error using LLM for query parsing: %s", e, exc_info=True)
        return None


def _get_llm_base_url() -> str | None:
    """Return the configured LLM base URL if it satisfies endpoint policy.

    When `ALLOWED_LLM_HOSTS` is empty (default), any configured URL is accepted.
    When set, only listed hosts pass — unless `LLM_ALLOW_EXTERNAL=true` is set
    for deliberate experiments with a non-listed endpoint.
    """
    base_url = _normalize_base_url(settings.LLM_API_URL)
    if base_url is None:
        logger.debug("LLM API URL not configured, skipping natural language parsing")
        return None

    # No allow-list configured -> no host enforcement.
    if not _ALLOWED_LLM_HOSTS:
        return base_url

    if settings.LLM_ALLOW_EXTERNAL:
        return base_url

    host = (urlsplit(base_url).hostname or "").lower()
    if host in _ALLOWED_LLM_HOSTS:
        return base_url

    logger.warning(
        "Ignoring LLM API URL %s; not in ALLOWED_LLM_HOSTS (set LLM_ALLOW_EXTERNAL=true to override)", base_url
    )
    return None


def _normalize_base_url(url: str | None) -> str | None:
    """Normalize an LLM gateway base URL without accepting empty values."""
    if url is None:
        return None
    stripped = url.strip().rstrip("/")
    if not stripped:
        return None
    parsed = urlsplit(stripped)
    if not parsed.scheme or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


async def _query_llm(
    query: str,
    episodes: list[dict[str, Any]],
    *,
    base_url: str | None = None,
) -> list[dict[str, Any]] | None:
    """
    Make actual LLM API call to filter episodes.

    Args:
        query: Search query.
        episodes: Episodes to filter.

    Returns:
        Filtered episodes or None on error.
    """
    # Prepare episode context for LLM (limit size to avoid token limits)
    episode_context: list[dict[str, Any]] = []
    for ep in episodes[:_MAX_EPISODES_FOR_CONTEXT]:
        ep_data: dict[str, Any] = {
            "idx": len(episode_context),  # Pre-calculate index for LLM
            "s": ep.get("season"),
            "e": ep.get("number"),
            "title": ep.get("title"),
            "date": str(ep.get("release_date")),
        }
        # Include truncated summary to save tokens
        summary = ep.get("summary")
        if summary:
            ep_data["plot"] = summary[:150] + "..." if len(summary) > 150 else summary
        episode_context.append(ep_data)
    episode_summaries = episode_context

    prompt = _build_prompt(query, episode_summaries)

    llm_base_url = base_url or _get_llm_base_url()
    if llm_base_url is None:
        return None

    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{llm_base_url}/chat/completions",
            headers=_build_headers(),
            json={
                "model": settings.LLM_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 100,
            },
        )

        if response.status_code != 200:
            logger.warning("LLM API returned status %d", response.status_code)
            return None

        return _parse_llm_response(response.json(), episodes, query)


def _build_prompt(query: str, episode_summaries: list[dict[str, Any]]) -> str:
    """Build the LLM prompt for episode filtering."""
    # Calculate season info for the prompt
    seasons: dict[int, list[int]] = {}
    for ep in episode_summaries:
        s = ep.get("s", 0)
        if s not in seasons:
            seasons[s] = []
        seasons[s].append(ep.get("idx", 0))

    season_info = ", ".join([f"S{s}: eps {min(eps)}-{max(eps)}" for s, eps in sorted(seasons.items())])

    return f"""Find episodes matching the query. Return their idx values as a JSON array.

DATA FIELDS: idx (use this for output), s (season), e (episode number), title, date, plot

SEASON STRUCTURE: {season_info}

RULES:
- "season finale" = highest episode number in each season
- "season premiere" = episode 1 of each season
- "pilot" = first episode ever (idx 0)
- For plot searches, check the "plot" field
- BE STRICT: Return [] if no clear match

Query: "{query}"

Episodes:
{json.dumps(episode_summaries)}

Return ONLY a JSON array of idx values, e.g. [0,5,12] or []. No text."""


def _build_headers() -> dict[str, str]:
    """Build HTTP headers for LLM API request."""
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    return headers


def _parse_llm_response(
    result: dict[str, Any],
    episodes: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]] | None:
    """
    Parse LLM response and extract matching episodes.

    Args:
        result: Raw LLM API response.
        episodes: Original episode list.
        query: Original query (for logging).

    Returns:
        Filtered episodes or None on parse error.
    """
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "[]")

    # Strip <think>...</think> blocks from reasoning models before JSON parsing
    content = _THINK_TAG_RE.sub("", content).strip()

    try:
        indices = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM response as JSON: %s", content)
        return None

    if not isinstance(indices, list):
        return None

    # Filter to valid indices only
    filtered = [episodes[i] for i in indices if isinstance(i, int) and 0 <= i < len(episodes)]

    logger.info(
        "LLM filtered %d episodes to %d for query: %s",
        len(episodes),
        len(filtered),
        query,
    )

    return filtered
