"""Regression test: the prod Docker publish must be IPv4-only.

A bare ``"3000:3000"`` ports mapping binds BOTH the IPv4 wildcard
``0.0.0.0:3000`` AND the IPv6 ``[::]:3000`` dual-stack listener. This API is
only ever reached over IPv4 behind a reverse proxy, so the ``[::]`` listener is
an unguarded ingress surface with no purpose. The fix is to pin the IPv4
wildcard explicitly (``"0.0.0.0:3000:3000"``), which removes the IPv6 listener
while preserving the exact IPv4 reachability the proxy uses today.

``0.0.0.0`` is deliberate over the two alternatives:

  * ``127.0.0.1`` would publish only on loopback inside the container's network
    namespace, breaking any remote reverse-proxy that connects over a routable
    host IP.
  * A specific host IP is brittle: it breaks the in-container loopback
    healthcheck and fails if the container starts before that IP is assigned.

This test guards against a future edit silently reverting to a dual-stack
publish.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = _REPO_ROOT / "docker-compose.prod.yml"


def _published_ports(service_name: str) -> list[str]:
    compose = yaml.safe_load(PROD_COMPOSE.read_text()) or {}
    service = (compose.get("services") or {}).get(service_name) or {}
    return [str(entry) for entry in (service.get("ports") or [])]


def test_prod_api_publish_is_ipv4_only_no_dual_stack_listener() -> None:
    ports = _published_ports("epguides-api")
    assert ports, "expected at least one published port on the prod epguides-api service"

    for spec in ports:
        assert spec.startswith("0.0.0.0:"), (
            f"prod epguides-api publishes {spec!r} — must pin the IPv4 wildcard "
            f'(e.g. "0.0.0.0:3000:3000") so no IPv6 [::] dual-stack listener is '
            f"bound. 127.0.0.1 would break a remote reverse-proxy; a bare "
            f"host:port binds [::] too."
        )
