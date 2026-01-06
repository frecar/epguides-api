"""
Pydantic schemas for TV show and episode data.

These schemas define the structure of API responses and ensure
proper validation and serialization of data.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.config import settings
from app.core.constants import EPGUIDES_BASE_URL

# =============================================================================
# Episode Schema
# =============================================================================


class EpisodeSchema(BaseModel):
    """
    Single episode data.

    Contains all metadata for one episode of a TV show.
    """

    number: int = Field(..., ge=1, description="Episode number within the season")
    season: int = Field(..., ge=0, description="Season number (0 for specials)")
    title: str = Field(..., min_length=1, description="Episode title")
    release_date: date = Field(..., description="Original air date")
    is_released: bool = Field(..., description="Whether the episode has aired")
    run_time_min: int | None = Field(None, ge=1, description="Runtime in minutes")
    episode_number: int | None = Field(None, ge=1, description="Absolute episode number (1-indexed)")
    summary: str | None = Field(None, description="Episode summary/description")
    poster_url: str | None = Field(None, description="Season poster URL (falls back to show poster)")


# =============================================================================
# Show Schemas
# =============================================================================


class ShowListSchema(BaseModel):
    """
    Simplified show schema for list/search endpoints.

    Contains only essential fields for browsing. Use the individual
    show endpoint for complete metadata including IMDB ID and runtime.
    """

    epguides_key: str = Field(..., description="Unique epguides identifier")
    title: str = Field(..., description="Show title")

    # Basic metadata
    network: str | None = Field(None, description="TV network or streaming service")
    country: str | None = Field(None, description="Country of origin")
    start_date: date | None = Field(None, description="First episode air date")
    end_date: date | None = Field(None, description="Last episode air date (if ended)")

    @computed_field
    def external_epguides_url(self) -> str:
        """URL to the show's page on epguides.com."""
        return f"{EPGUIDES_BASE_URL}/{self.epguides_key}"

    @computed_field
    def api_self_url(self) -> str:
        """API endpoint URL for full show details."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}"

    model_config = ConfigDict(populate_by_name=True)


class ShowSchema(BaseModel):
    """
    Complete show metadata.

    Returned by individual show endpoints with full details.
    """

    # Required fields
    epguides_key: str = Field(..., description="Unique epguides identifier")
    title: str = Field(..., description="Show title")

    # Optional metadata
    imdb_id: str | None = Field(None, description="IMDB ID (format: tt1234567)")
    network: str | None = Field(None, description="TV network or streaming service")
    run_time_min: int | None = Field(None, ge=1, description="Average episode runtime in minutes")
    start_date: date | None = Field(None, description="First episode air date")
    end_date: date | None = Field(None, description="Last episode air date (if ended)")
    country: str | None = Field(None, description="Country of origin")
    total_episodes: int | None = Field(None, ge=0, description="Total episode count")
    poster_url: str | None = Field(None, description="Show poster image URL from TVMaze")

    # Computed URL fields
    @computed_field
    def external_epguides_url(self) -> str:
        """URL to the show's page on epguides.com."""
        return f"{EPGUIDES_BASE_URL}/{self.epguides_key}"

    @computed_field
    def external_imdb_url(self) -> str | None:
        """URL to the show's IMDB page (if IMDB ID available)."""
        if self.imdb_id:
            return f"https://www.imdb.com/title/{self.imdb_id}"
        return None

    @computed_field
    def api_self_url(self) -> str:
        """API endpoint URL for this show."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}"

    @computed_field
    def api_episodes_url(self) -> str:
        """API endpoint URL for this show's episodes."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}/episodes"

    @computed_field
    def api_next_episode_url(self) -> str:
        """API endpoint URL for the next unreleased episode."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}/episodes/next"

    @computed_field
    def api_latest_episode_url(self) -> str:
        """API endpoint URL for the latest released episode."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}/episodes/latest"

    model_config = ConfigDict(populate_by_name=True)


class ShowDetailsSchema(ShowSchema):
    """
    Show with embedded episode list.

    Returned when ?include=episodes is requested.
    """

    episodes: list[EpisodeSchema] = Field(..., description="All episodes for the show")


# =============================================================================
# Factory Functions
# =============================================================================


def create_show_schema(
    epguides_key: str,
    title: str,
    *,
    imdb_id: str | None = None,
    network: str | None = None,
    run_time_min: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    country: str | None = None,
    total_episodes: int | None = None,
    poster_url: str | None = None,
) -> ShowSchema:
    """
    Create a ShowSchema with explicit optional fields.

    This factory function ensures type safety and makes it clear
    which fields are optional.

    Args:
        epguides_key: Unique show identifier.
        title: Show title.
        imdb_id: IMDB ID (optional).
        network: Network name (optional).
        run_time_min: Episode runtime in minutes (optional).
        start_date: First air date (optional).
        end_date: Last air date (optional).
        country: Country of origin (optional).
        total_episodes: Episode count (optional).
        poster_url: Show poster image URL (optional).

    Returns:
        Configured ShowSchema instance.
    """
    return ShowSchema(
        epguides_key=epguides_key,
        title=title,
        imdb_id=imdb_id,
        network=network,
        run_time_min=run_time_min,
        start_date=start_date,
        end_date=end_date,
        country=country,
        total_episodes=total_episodes,
        poster_url=poster_url,
    )
