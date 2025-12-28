"""
API response models for consistent response structure.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper with metadata."""

    items: list[T] = Field(..., description="List of items for the current page")
    total: int = Field(..., description="Total number of items available")
    page: int = Field(..., description="Current page number (1-indexed)")
    limit: int = Field(..., description="Number of items per page")
    has_next: bool = Field(..., description="Whether there are more pages available")
    has_previous: bool = Field(..., description="Whether there are previous pages available")
