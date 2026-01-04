"""
LLM-powered natural language episode search.

Uses an LLM to parse complex natural language queries that
simple regex patterns cannot handle.

Only used when LLM_ENABLED is True in settings.
"""

import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# LLM configuration
_LLM_TIMEOUT_SECONDS = 5.0
_MAX_EPISODES_FOR_CONTEXT = 50


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
    if not settings.LLM_ENABLED or not settings.LLM_API_URL:
        logger.debug("LLM not enabled, skipping natural language parsing")
        return None

    try:
        return await _query_llm(query, episodes)
    except Exception as e:
        logger.error("Error using LLM for query parsing: %s", e, exc_info=True)
        return None


async def _query_llm(
    query: str,
    episodes: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """
    Make actual LLM API call to filter episodes.

    Args:
        query: Search query.
        episodes: Episodes to filter.

    Returns:
        Filtered episodes or None on error.
    """
    # Prepare episode summaries for context (limit to avoid token limits)
    episode_summaries = [
        {
            "season": ep.get("season"),
            "number": ep.get("number"),
            "title": ep.get("title"),
            "release_date": str(ep.get("release_date")),
        }
        for ep in episodes[:_MAX_EPISODES_FOR_CONTEXT]
    ]

    prompt = _build_prompt(query, episode_summaries)

    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{settings.LLM_API_URL}/chat/completions",
            headers=_build_headers(),
            json={
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
    return f"""You are a TV episode search assistant. Given a user query and a list of episodes,
return a JSON array of episode indices (0-based) that match the query.

User query: "{query}"

Episodes:
{json.dumps(episode_summaries, indent=2)}

Return ONLY a JSON array of matching indices, e.g., [0, 5, 12]. If no matches, return [].
Do not include any explanation or text outside the JSON array."""


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
