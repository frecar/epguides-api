"""Container health check: exit 0 when GET /health answers HTTP 200 with a healthy status, else 1.

Usage in Dockerfile/docker-compose:
    CMD ["python", "healthcheck.py"]
"""

import argparse
import sys
import urllib.error
import urllib.request

DEFAULT_HEALTH_URL = "http://localhost:3000/health"
DEFAULT_TIMEOUT_SECONDS = 5.0
HEALTHY_MARKER = '"healthy"'


def probe_health(url: str = DEFAULT_HEALTH_URL, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str | None:
    """Return None when healthy, otherwise the reason the probe failed."""
    request = urllib.request.Request(url, headers={"User-Agent": "docker-healthcheck"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return f"GET {url} returned HTTP {response.status}, expected 200"
            body = response.read().decode("utf-8")
    except (OSError, ValueError) as err:
        return f"GET {url} failed: {type(err).__name__}: {err}"
    if HEALTHY_MARKER not in body:
        return f"GET {url} body has no {HEALTHY_MARKER} status: {body[:200]!r}"
    return None


def check_health() -> bool:
    """Check API health endpoint returns 200 with healthy status."""
    return probe_health() is None


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Exit 0 if the API health endpoint reports healthy, 1 otherwise (reason on stderr).",
        epilog="example: python healthcheck.py --url http://localhost:3000/health --timeout 5",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.add_argument(
        "--url", default=DEFAULT_HEALTH_URL, help=f"health endpoint to probe (default: {DEFAULT_HEALTH_URL})"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"seconds to wait for a response (default: {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error(f"--timeout must be greater than 0 seconds, got {args.timeout:g}")
    reason = probe_health(args.url, args.timeout)
    if reason:
        print(f"unhealthy: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
