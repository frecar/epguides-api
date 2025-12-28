"""
Smart LLM service for natural language episode queries.

Uses LLM to parse complex natural language queries that regex cannot handle.
Only used when LLM_ENABLED is True and query doesn't match simple patterns.
"""

import json
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def parse_natural_language_query(query: str, episodes: list[dict]) -> list[dict] | None:
    """
    Use LLM to parse complex natural language queries.

    Examples:
    - "episodes where Walter dies"
    - "show me episodes from the first half of season 3"
    - "episodes with ratings above 9.0"

    Returns filtered episodes or None if LLM is disabled or query is too complex.
    """
    if not settings.LLM_ENABLED or not settings.LLM_API_URL:
        logger.debug("LLM not enabled or configured, skipping natural language parsing")
        return None

    if not episodes:
        return []

    try:
        # Prepare context for LLM
        episode_summaries = [
            {
                "season": ep.get("season"),
                "number": ep.get("number"),
                "title": ep.get("title"),
                "release_date": str(ep.get("release_date")),
            }
            for ep in episodes[:50]  # Limit context to avoid token limits
        ]

        prompt = f"""You are a TV episode search assistant. Given a user query and a list of episodes,
return a JSON array of episode indices (0-based) that match the query.

User query: "{query}"

Episodes:
{json.dumps(episode_summaries, indent=2)}

Return ONLY a JSON array of matching indices, e.g., [0, 5, 12]. If no matches, return [].
Do not include any explanation or text outside the JSON array."""

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{settings.LLM_API_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}" if settings.LLM_API_KEY else "",
                    "Content-Type": "application/json",
                },
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 100,
                },
            )

            if response.status_code != 200:
                logger.warning(f"LLM API returned status {response.status_code}")
                return None

            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "[]")
            indices = json.loads(content)

            if isinstance(indices, list):
                filtered = [episodes[i] for i in indices if 0 <= i < len(episodes)]
                logger.info(f"LLM filtered {len(episodes)} episodes to {len(filtered)} based on query: {query}")
                return filtered

    except Exception as e:
        logger.error(f"Error using LLM for query parsing: {e}", exc_info=True)
        return None

    return None
