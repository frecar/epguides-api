"""Django --testrunner entry point extending settings.TEST_RUNNER unchanged."""

from django.conf import settings
from django.test.utils import get_runner

from .django import ShardRunnerMixin

if __name__ + ".ShardRunner" == settings.TEST_RUNNER:
    raise ValueError("keep settings.TEST_RUNNER as the existing runner; select the adapter with --testrunner")


class ShardRunner(ShardRunnerMixin, get_runner(settings)):
    pass
