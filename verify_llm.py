#!/usr/bin/env python3
"""Verify the configured LLM endpoint answers a natural-language episode query.

Reads LLM_ENABLED, LLM_API_URL and LLM_API_KEY from the environment or .env,
sends one sample query and exits 0 on a well-formed answer, 1 otherwise.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.services import llm_service

DEFAULT_QUERY = "episodes with pilot or seven in the title"
SAMPLE_EPISODES = [
    {"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"},
    {"season": 1, "number": 2, "title": "Cat's in the Bag", "release_date": "2008-01-27"},
    {"season": 2, "number": 1, "title": "Seven Thirty-Seven", "release_date": "2009-03-08"},
    {"season": 2, "number": 2, "title": "Grilled", "release_date": "2009-03-15"},
]


def configuration_problem() -> str | None:
    """Return why the LLM cannot be tested with the current settings, or None when it can."""
    if not settings.LLM_ENABLED:
        return "LLM is disabled. Set LLM_ENABLED=true in the environment or .env to enable it."
    if not settings.LLM_API_URL:
        return "LLM_API_URL is not set. Set it to an OpenAI-compatible base URL, e.g. LLM_API_URL=http://localhost:11434/v1."
    return None


async def verify_llm(query: str = DEFAULT_QUERY) -> bool:
    """Verify LLM service is working."""
    print("🔍 Verifying LLM Configuration...")
    print(f"   LLM_ENABLED: {settings.LLM_ENABLED}")
    print(f"   LLM_API_URL: {settings.LLM_API_URL}")
    print(f"   LLM_API_KEY: {'***' if settings.LLM_API_KEY else '(not set)'}")
    print()

    if problem := configuration_problem():
        print(f"❌ {problem}", file=sys.stderr)
        return False

    print("✅ Configuration looks good!")
    print()
    print(f"🧪 Testing LLM with query {query!r}...")

    result = await llm_service.parse_natural_language_query(query, SAMPLE_EPISODES)
    if result is None:
        print(
            f"❌ LLM at {settings.LLM_API_URL} returned no usable answer for {query!r}. "
            "Check the llm_service warnings above and GET /health/llm.",
            file=sys.stderr,
        )
        return False

    print("✅ LLM query successful!")
    print(f"   Input episodes: {len(SAMPLE_EPISODES)}")
    print(f"   Filtered episodes: {len(result)}")
    print()
    print("   Matching episodes:")
    for ep in result:
        print(f"     - S{ep['season']}E{ep['number']}: {ep['title']}")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send one natural-language query to the configured LLM endpoint and report the result.",
        epilog="example: LLM_ENABLED=true LLM_API_URL=http://localhost:11434/v1 python verify_llm.py --query pilot",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help=f"natural-language query to test (default: {DEFAULT_QUERY!r})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return 0 if asyncio.run(verify_llm(args.query)) else 1


if __name__ == "__main__":
    sys.exit(main())
