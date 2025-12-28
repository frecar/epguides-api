from datetime import date

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.config import settings
from app.core.constants import EPGUIDES_BASE_URL


class EpisodeSchema(BaseModel):
    number: int = Field(..., description="Episode number within the season")
    season: int = Field(..., description="Season number")
    title: str = Field(..., description="Title of the episode")
    release_date: date = Field(..., description="Release date of the episode")
    is_released: bool = Field(..., description="Whether the episode has been released")
    run_time_min: int | None = Field(None, description="Episode runtime in minutes (from show metadata)")
    episode_number: int | None = Field(None, description="Episode number across all seasons (1-indexed)")


class ShowSchema(BaseModel):
    # Required fields
    epguides_key: str = Field(..., description="The epguides identifier/key for the show")
    title: str = Field(..., description="Full title of the show")

    # Computed fields (always present)
    @computed_field
    def external_epguides_url(self) -> str:
        """External epguides.com URL for this show."""
        return f"{EPGUIDES_BASE_URL}/{self.epguides_key}"

    @computed_field
    def external_imdb_url(self) -> str | None:
        """External IMDB URL for this show (if IMDB ID is available)."""
        if self.imdb_id:
            return f"https://www.imdb.com/title/{self.imdb_id}"
        return None

    @computed_field
    def api_self_url(self) -> str:
        """This API's endpoint URL for this show."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}"

    @computed_field
    def api_episodes_url(self) -> str:
        """This API's endpoint URL for this show's episodes."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}/episodes"

    @computed_field
    def api_next_episode_url(self) -> str:
        """This API's endpoint URL for the next unreleased episode."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}/episodes/next"

    @computed_field
    def api_latest_episode_url(self) -> str:
        """This API's endpoint URL for the latest released episode."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}/episodes/latest"

    # Optional metadata
    imdb_id: str | None = Field(None, description="IMDB ID of the show")
    network: str | None = Field(None, description="TV Network or Streaming Service")
    run_time_min: int | None = Field(None, description="Average run time of episodes in minutes")
    start_date: date | None = Field(None, description="Show start date")
    end_date: date | None = Field(None, description="Show end date")
    country: str | None = Field(None, description="Country of origin")
    total_episodes: int | None = Field(None, description="Total number of episodes")

    model_config = ConfigDict(populate_by_name=True)


class ShowListSchema(BaseModel):
    """
    Simplified show schema for list endpoints.

    Contains only essential information for browsing shows.
    Detailed metadata is available on individual show endpoints.
    """

    # Required fields
    epguides_key: str = Field(..., description="The epguides identifier/key for the show")
    title: str = Field(..., description="Full title of the show")

    # Computed fields (always present)
    @computed_field
    def external_epguides_url(self) -> str:
        """Generate epguides.com URL from the key."""
        return f"{EPGUIDES_BASE_URL}/{self.epguides_key}"

    @computed_field
    def api_self_url(self) -> str:
        """API endpoint URL for this show."""
        base_url = settings.API_BASE_URL.rstrip("/")
        return f"{base_url}/shows/{self.epguides_key}"

    # Basic metadata only
    network: str | None = Field(None, description="TV Network or Streaming Service")
    country: str | None = Field(None, description="Country of origin")
    start_date: date | None = Field(None, description="Show start date")
    end_date: date | None = Field(None, description="Show end date")

    model_config = ConfigDict(populate_by_name=True)


class ShowDetailsSchema(ShowSchema):
    episodes: list[EpisodeSchema] = Field(..., description="List of all episodes for the show")


def create_show_schema(
    epguides_key: str,
    title: str,
    imdb_id: str | None = None,
    network: str | None = None,
    run_time_min: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    country: str | None = None,
    total_episodes: int | None = None,
) -> ShowSchema:
    """
    Helper function to create ShowSchema with all optional fields explicitly set.

    This ensures type checker satisfaction and makes it clear which fields are optional.
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
    )
