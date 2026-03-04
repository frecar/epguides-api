"""Docker health check script.

Verifies the API is responding correctly by checking:
1. HTTP status code is 200
2. Response body contains expected health status

Exit codes:
    0 - healthy
    1 - unhealthy

Usage in Dockerfile/docker-compose:
    CMD ["python", "healthcheck.py"]
"""

import sys
import urllib.request


def check_health() -> bool:
    """Check API health endpoint returns 200 with healthy status."""
    try:
        req = urllib.request.Request(
            "http://localhost:3000/health",
            headers={"User-Agent": "docker-healthcheck"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                return False
            body = response.read().decode("utf-8")
            return '"healthy"' in body
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(0 if check_health() else 1)
