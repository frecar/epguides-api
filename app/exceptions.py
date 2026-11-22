"""
Typed errors for the Epguides API.

Each error carries a stable machine-readable ``code``, the HTTP status it maps
to, a message naming the offending show, season, episode or parameter, and a
``hint`` describing the next request to make.
"""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from http import HTTPStatus

type ErrorContextValue = str | int | list[int] | None

SHOW_KEY_EXAMPLE = "BreakingBad"
IMDB_ID_EXAMPLE = "tt0903747"
SHOW_SEARCH_HINT = (
    f"Find the epguides key with GET /shows/search?query=<title>, then use it as in /shows/{SHOW_KEY_EXAMPLE}."
)


class ErrorCode(StrEnum):
    SHOW_NOT_FOUND = "show_not_found"
    SEASON_NOT_FOUND = "season_not_found"
    NO_EPISODES = "no_episodes"
    NO_RELEASED_EPISODE = "no_released_episode"
    NO_UPCOMING_EPISODE = "no_upcoming_episode"
    SHOW_FINISHED = "show_finished"
    INVALID_IMDB_ID = "invalid_imdb_id"
    IMDB_ID_NOT_FOUND = "imdb_id_not_found"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    VALIDATION_ERROR = "validation_error"
    ROUTE_NOT_FOUND = "route_not_found"
    INTERNAL_ERROR = "internal_error"


class UpstreamSource(StrEnum):
    EPGUIDES = "epguides.com"
    TVMAZE = "TVMaze"


class EpguidesAPIException(Exception):
    """Base error; unhandled instances surface as a generic HTTP 500."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    status_code: HTTPStatus = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, hint: str | None = None, **context: ErrorContextValue) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.context: dict[str, ErrorContextValue] = {k: v for k, v in context.items() if v is not None}

    @property
    def is_client_visible(self) -> bool:
        return self.status_code != HTTPStatus.INTERNAL_SERVER_ERROR

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"detail": self.message, "code": self.code.value}
        if self.hint:
            payload["hint"] = self.hint
        if self.context:
            payload["context"] = self.context
        return payload


class ExternalServiceError(EpguidesAPIException):
    """An upstream data source (epguides.com, TVMaze) or Redis could not serve the request."""

    code = ErrorCode.UPSTREAM_UNAVAILABLE
    status_code = HTTPStatus.SERVICE_UNAVAILABLE

    def __init__(
        self,
        message: str,
        *,
        source: UpstreamSource | None = None,
        hint: str | None = "Retry in a few minutes; GET /health/ready reports upstream freshness.",
        **context: ErrorContextValue,
    ) -> None:
        super().__init__(message, hint=hint, upstream_source=source.value if source else None, **context)
        self.source = source


class ShowCatalogUnavailableError(ExternalServiceError):
    def __init__(self, epguides_key: str) -> None:
        super().__init__(
            f"External service temporarily unavailable: the {UpstreamSource.EPGUIDES} show catalogue could not be "
            f"loaded, so show {epguides_key!r} cannot be looked up.",
            source=UpstreamSource.EPGUIDES,
            epguides_key=epguides_key,
        )


class ShowNotFoundError(EpguidesAPIException):
    code = ErrorCode.SHOW_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, epguides_key: str) -> None:
        super().__init__(
            f"Show not found: {epguides_key!r}. Expected an epguides key such as {SHOW_KEY_EXAMPLE!r} "
            "(case-insensitive, no spaces).",
            hint=SHOW_SEARCH_HINT,
            epguides_key=epguides_key,
        )


class SeasonNotFoundError(EpguidesAPIException):
    code = ErrorCode.SEASON_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, epguides_key: str, season: int, available_seasons: Iterable[int]) -> None:
        seasons = sorted(set(available_seasons))
        listed = ", ".join(str(s) for s in seasons) if seasons else "none"
        super().__init__(
            f"Season {season} not found for show {epguides_key!r}. Available seasons: {listed}.",
            hint=f"List seasons with GET /shows/{epguides_key}/seasons.",
            epguides_key=epguides_key,
            season=season,
            available_seasons=seasons,
        )


class NoEpisodesError(EpguidesAPIException):
    code = ErrorCode.NO_EPISODES
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, epguides_key: str) -> None:
        super().__init__(
            f"No episodes found for show {epguides_key!r}: the show exists but its episode list is empty "
            "or could not be loaded from upstream.",
            hint=f"Retry with GET /shows/{epguides_key}/episodes?refresh=true to re-fetch from upstream.",
            epguides_key=epguides_key,
        )


class NoReleasedEpisodeError(EpguidesAPIException):
    code = ErrorCode.NO_RELEASED_EPISODE
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, epguides_key: str) -> None:
        super().__init__(
            f"No released episodes found for show {epguides_key!r}: every listed episode airs in the future.",
            hint=f"Use GET /shows/{epguides_key}/episodes/next for the first air date.",
            epguides_key=epguides_key,
        )


class ShowFinishedError(EpguidesAPIException):
    code = ErrorCode.SHOW_FINISHED
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, epguides_key: str, end_date: date) -> None:
        super().__init__(
            f"Show has finished airing: {epguides_key!r} ended on {end_date.isoformat()}, so it has no next episode.",
            hint=f"Use GET /shows/{epguides_key}/episodes/latest for the final episode.",
            epguides_key=epguides_key,
            end_date=end_date.isoformat(),
        )


class NoUpcomingEpisodeError(EpguidesAPIException):
    code = ErrorCode.NO_UPCOMING_EPISODE
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, epguides_key: str) -> None:
        super().__init__(
            f"No unreleased episodes found for show {epguides_key!r}: no upcoming episode with a title "
            "has been announced yet.",
            hint=f"Use GET /shows/{epguides_key}/episodes/latest for the most recent episode.",
            epguides_key=epguides_key,
        )


class InvalidImdbIdError(EpguidesAPIException):
    code = ErrorCode.INVALID_IMDB_ID
    status_code = HTTPStatus.BAD_REQUEST

    def __init__(self, imdb_id: str) -> None:
        super().__init__(
            f"Invalid IMDB ID format: {imdb_id!r} (expected 'tt' followed by digits, for example {IMDB_ID_EXAMPLE!r}).",
            hint=f"Use the ID from the IMDB title URL, as in /shows/by-imdb/{IMDB_ID_EXAMPLE}.",
            imdb_id=imdb_id,
        )


class ImdbIdNotFoundError(EpguidesAPIException):
    code = ErrorCode.IMDB_ID_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, imdb_id: str) -> None:
        super().__init__(
            f"No show found for IMDB ID: {imdb_id}. TVMaze has no record of it, the show is not in the epguides "
            "catalogue, or several catalogue shows match and none can be chosen safely.",
            hint=SHOW_SEARCH_HINT,
            imdb_id=imdb_id,
        )


class InvalidParameterError(EpguidesAPIException):
    code = ErrorCode.VALIDATION_ERROR
    status_code = HTTPStatus.UNPROCESSABLE_CONTENT

    def __init__(self, parameter: str, value: object, expected: str) -> None:
        super().__init__(
            f"Invalid query parameter {parameter}={value!r}: {expected}.",
            parameter=parameter,
        )
        self.parameter = parameter
        self.value = value
        self.expected = expected

    def to_payload(self) -> dict[str, object]:
        payload = super().to_payload()
        payload["errors"] = [
            {"loc": ["query", self.parameter], "msg": self.expected, "type": "value_error", "input": self.value}
        ]
        return payload
