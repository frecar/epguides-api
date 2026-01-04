"""
Generic API response models.

Provides reusable response wrappers for consistent API structure.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Paginated response wrapper with navigation metadata.

    All list endpoints that support pagination return this structure.
    Page numbers are 1-indexed for user-friendliness.
    """

    items: list[T] = Field(
        ...,
        description="Items for the current page",
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total number of items across all pages",
    )
    page: int = Field(
        ...,
        ge=1,
        description="Current page number (1-indexed)",
    )
    limit: int = Field(
        ...,
        ge=1,
        description="Maximum items per page",
    )
    has_next: bool = Field(
        ...,
        description="Whether more pages are available",
    )
    has_previous: bool = Field(
        ...,
        description="Whether previous pages exist",
    )
