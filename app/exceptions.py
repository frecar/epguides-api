"""
Custom exceptions for the Epguides API.

Provides specific exception types for better error handling and user feedback.
"""


class EpguidesAPIException(Exception):
    """Base exception for all Epguides API errors."""

    pass


class ExternalServiceError(EpguidesAPIException):
    """Raised when external services (epguides.com, Redis) fail."""

    pass
