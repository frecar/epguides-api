"""
Custom exceptions for the Epguides API.

Provides a hierarchy of exception types for different error scenarios.
Each exception type maps to a specific HTTP status code.
"""


class EpguidesAPIException(Exception):
    """
    Base exception for all Epguides API errors.

    Use specific subclasses for particular error types.
    """


class ExternalServiceError(EpguidesAPIException):
    """
    Raised when external services fail.

    Examples:
    - epguides.com is unreachable or returns an error
    - Redis connection fails
    - Timeout waiting for external response

    Maps to HTTP 503 Service Unavailable.
    """


class ShowNotFoundError(EpguidesAPIException):
    """
    Raised when a requested show does not exist.

    Maps to HTTP 404 Not Found.
    """

    def __init__(self, show_id: str) -> None:
        self.show_id = show_id
        super().__init__(f"Show not found: {show_id}")


class EpisodeNotFoundError(EpguidesAPIException):
    """
    Raised when a requested episode does not exist.

    Maps to HTTP 404 Not Found.
    """

    def __init__(self, show_id: str, message: str = "Episode not found") -> None:
        self.show_id = show_id
        super().__init__(f"{message} for show: {show_id}")
