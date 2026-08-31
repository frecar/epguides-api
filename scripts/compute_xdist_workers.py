#!/usr/bin/env python3
"""Choose pytest-xdist workers from visible CPU, finite memory, and suite knee.

The public CI job runs on GitHub-hosted hardware whose size can change. This
selector therefore reads scheduler/cgroup-visible capacity instead of assuming
a runner topology. The final cap is the suite's same-commit measured scaling
knee, not a machine-size constant.

DELIBERATE, PERMANENT VENDORED COPY (decided 2026-08-31) -- not a pending
migration. Several sibling private repos have converged the equivalent logic
into a small shared internal package, consumed as a pinned git dependency.
This repo is public and ships `scripts/check_no_private_git_deps.py`
specifically to reject any owner-scoped git dependency other than its own, so
`uv sync` here must never need to clone a private repository -- doing so would
fail for every outside contributor and every public fork PR's CI run (no
injected credential is available there). Keep this file's logic in sync by
hand with the shared internal module when either changes; do not add a
private-repo dependency here to "finish" a migration to it.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

CPU_FRACTION = 0.80
MEMORY_FRACTION = 0.80
MEASURED_BYTES_PER_WORKER = 256 * 1024 * 1024
MEASURED_SUITE_KNEE = 8


@dataclass(frozen=True)
class WorkerSelection:
    workers: int
    visible_cpus: int | None
    available_memory_bytes: int | None
    cpu_budget: int
    memory_budget: int
    reason: str


def select_workers(visible_cpus: int | None, available_memory_bytes: int | None) -> WorkerSelection:
    """Return a fail-closed worker selection for discovered capacity."""
    if not visible_cpus or visible_cpus < 1:
        return WorkerSelection(1, visible_cpus, available_memory_bytes, 1, 1, "CPU discovery failed")
    if not available_memory_bytes or available_memory_bytes < 1:
        return WorkerSelection(1, visible_cpus, available_memory_bytes, 1, 1, "memory discovery failed")

    cpu_budget = max(1, math.floor(visible_cpus * CPU_FRACTION))
    memory_budget = max(1, math.floor(available_memory_bytes * MEMORY_FRACTION / MEASURED_BYTES_PER_WORKER))
    workers = min(cpu_budget, memory_budget, MEASURED_SUITE_KNEE)
    return WorkerSelection(
        workers, visible_cpus, available_memory_bytes, cpu_budget, memory_budget, "capacity selected"
    )


def _read_positive_int(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if raw == "max":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def discover_visible_cpus() -> int | None:
    """Return the lower of process affinity and a finite cgroup-v2 quota."""
    try:
        affinity_count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity_count = os.cpu_count()

    quota_count: int | None = None
    try:
        quota_raw, period_raw = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="utf-8").split()
        if quota_raw != "max":
            quota_count = max(1, math.floor(int(quota_raw) / int(period_raw)))
    except (OSError, ValueError):
        pass

    candidates = [value for value in (affinity_count, quota_count) if value and value > 0]
    return min(candidates) if candidates else None


def _proc_available_memory() -> int | None:
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("MemAvailable:"):
            try:
                return int(line.split()[1]) * 1024
            except (IndexError, ValueError):
                return None
    return None


def discover_available_memory() -> int | None:
    """Return finite cgroup headroom bounded by host MemAvailable."""
    host_available = _proc_available_memory()
    cgroup_limit = _read_positive_int(Path("/sys/fs/cgroup/memory.max"))
    cgroup_current = _read_positive_int(Path("/sys/fs/cgroup/memory.current")) or 0
    if cgroup_limit is not None:
        cgroup_available = max(0, cgroup_limit - cgroup_current)
        return min(host_available, cgroup_available) if host_available is not None else cgroup_available
    return host_available


def redis_db_for_worker(worker_id: str) -> int | None:
    """Map an xdist ``gwN`` identity to a dedicated non-default Redis DB."""
    if not worker_id.startswith("gw") or not worker_id[2:].isdigit():
        return None
    database = int(worker_id[2:]) + 1
    if database > 15:
        raise ValueError(f"xdist worker {worker_id} exceeds Redis's default 16-database range")
    return database


def current_selection() -> WorkerSelection:
    return select_workers(discover_visible_cpus(), discover_available_memory())


def main() -> int:
    selection = current_selection()
    memory_mib = (
        selection.available_memory_bytes // (1024 * 1024) if selection.available_memory_bytes is not None else "unknown"
    )
    print(
        "epguides xdist capacity: "
        f"workers={selection.workers} visible_cpus={selection.visible_cpus or 'unknown'} "
        f"available_memory_mib={memory_mib} cpu_budget={selection.cpu_budget} "
        f"memory_budget={selection.memory_budget} suite_knee={MEASURED_SUITE_KNEE} "
        f"reason={selection.reason}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
