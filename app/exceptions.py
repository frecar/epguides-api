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
