"""Capacity-relative pytest worker selection regression tests."""

import pytest

from scripts.compute_xdist_workers import (
    MEASURED_BYTES_PER_WORKER,
    MEASURED_SUITE_KNEE,
    redis_db_for_worker,
    select_workers,
)


def test_scales_up_and_down_with_visible_cpu() -> None:
    memory = 64 * MEASURED_BYTES_PER_WORKER
    assert select_workers(1, memory).workers == 1
    assert select_workers(2, memory).workers == 1
    assert select_workers(4, memory).workers == 3
    assert select_workers(8, memory).workers == 6
    assert select_workers(16, memory).workers == 8
    assert select_workers(128, memory).workers == 8


def test_finite_memory_can_bind_before_cpu() -> None:
    assert select_workers(128, 2 * MEASURED_BYTES_PER_WORKER).workers == 1
    assert select_workers(128, 4 * MEASURED_BYTES_PER_WORKER).workers == 3


def test_discovery_failure_is_fail_closed_and_visible() -> None:
    cpu_failure = select_workers(None, 8 * MEASURED_BYTES_PER_WORKER)
    memory_failure = select_workers(8, None)
    assert (cpu_failure.workers, cpu_failure.reason) == (1, "CPU discovery failed")
    assert (memory_failure.workers, memory_failure.reason) == (1, "memory discovery failed")


def test_suite_knee_is_not_a_runner_topology_constant() -> None:
    selection = select_workers(192, 192 * MEASURED_BYTES_PER_WORKER)
    assert selection.cpu_budget > selection.workers
    assert selection.memory_budget > selection.workers
    assert selection.workers == 8


def test_each_normal_xdist_worker_gets_a_dedicated_redis_database() -> None:
    assert MEASURED_SUITE_KNEE <= 15
    assert redis_db_for_worker("gw0") == 1
    assert redis_db_for_worker(f"gw{MEASURED_SUITE_KNEE - 1}") == MEASURED_SUITE_KNEE
    assert redis_db_for_worker("master") is None
    with pytest.raises(ValueError, match="exceeds Redis"):
        redis_db_for_worker("gw15")
