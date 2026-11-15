"""Deliberate CI-only failure used to verify the merge lane ejects a red PR."""

import os


def test_fails_only_on_ci() -> None:
    assert not os.environ.get("GITHUB_ACTIONS")
