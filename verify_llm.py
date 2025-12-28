#!/usr/bin/env python3
"""
Simple script to verify LLM service works with your configured endpoint.

This script:
1. Loads settings from .env file
2. Tests if LLM is enabled
3. Makes a real API call to your LLM endpoint
4. Verifies the response format
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.services import llm_service


async def verify_llm():
    """Verify LLM service is working."""
    print("🔍 Verifying LLM Configuration...")
    print(f"   LLM_ENABLED: {settings.LLM_ENABLED}")
    print(f"   LLM_API_URL: {settings.LLM_API_URL}")
    print(f"   LLM_API_KEY: {'***' if settings.LLM_API_KEY else '(not set)'}")
    print()

    if not settings.LLM_ENABLED:
        print("❌ LLM is disabled. Set LLM_ENABLED=true in .env to enable.")
        return False

    if not settings.LLM_API_URL:
        print("❌ LLM_API_URL is not set. Configure it in .env file.")
        return False

    print("✅ Configuration looks good!")
    print()
    print("🧪 Testing LLM with sample query...")

    # Sample episodes for testing
    test_episodes = [
        {"season": 1, "number": 1, "title": "Pilot", "release_date": "2008-01-20"},
        {"season": 1, "number": 2, "title": "Cat's in the Bag", "release_date": "2008-01-27"},
        {"season": 2, "number": 1, "title": "Seven Thirty-Seven", "release_date": "2009-03-08"},
        {"season": 2, "number": 2, "title": "Grilled", "release_date": "2009-03-15"},
    ]

    test_query = "episodes with pilot or seven in the title"

    try:
        result = await llm_service.parse_natural_language_query(test_query, test_episodes)

        if result is None:
            print("❌ LLM returned None. Check logs for errors.")
            return False

        print(f"✅ LLM query successful!")
        print(f"   Query: '{test_query}'")
        print(f"   Input episodes: {len(test_episodes)}")
        print(f"   Filtered episodes: {len(result)}")
        print()
        print("   Matching episodes:")
        for ep in result:
            print(f"     - S{ep['season']}E{ep['number']}: {ep['title']}")

        return True

    except Exception as e:
        print(f"❌ Error testing LLM: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(verify_llm())
    sys.exit(0 if success else 1)

