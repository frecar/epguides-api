# :material-api: REST API Reference

Complete reference for all REST API endpoints.

!!! tip "Base URL"
    **Public:** `https://epguides.frecar.no`  
    **Local:** `http://localhost:3000`

---

## :material-format-list-bulleted: Endpoints Overview

| Method | Endpoint | Description |
|:------:|----------|-------------|
| :material-arrow-down-bold-circle:{ .get } | `/shows/` | List all shows (paginated) |
| :material-arrow-down-bold-circle:{ .get } | `/shows/search` | Search shows by title |
| :material-arrow-down-bold-circle:{ .get } | `/shows/{key}` | Get show metadata |
| :material-arrow-down-bold-circle:{ .get } | `/shows/{key}/episodes` | Get episodes with filtering |
| :material-arrow-down-bold-circle:{ .get } | `/shows/{key}/episodes/next` | Get next unreleased episode |
| :material-arrow-down-bold-circle:{ .get } | `/shows/{key}/episodes/latest` | Get latest released episode |
| :material-arrow-down-bold-circle:{ .get } | `/health` | Health check |
| :material-arrow-down-bold-circle:{ .get } | `/health/llm` | LLM status |
| :material-arrow-up-bold-circle:{ .post } | `/mcp` | MCP JSON-RPC endpoint |

---

## :material-television: Shows

### :material-format-list-bulleted: List Shows

```http
GET /shows/
```

Returns a paginated list of all TV shows.

!!! example "Parameters"
    | Parameter | Type | Default | Description |
    |-----------|------|---------|-------------|
    | `page` | integer | 1 | Page number |
    | `page_size` | integer | 50 | Items per page (max 100) |

```bash
curl "https://epguides.frecar.no/shows/?page=1&page_size=20"
```

---

### :material-magnify: Search Shows

```http
GET /shows/search
```

Search for shows by title.

!!! example "Parameters"
    | Parameter | Type | Required | Description |
    |-----------|------|:--------:|-------------|
    | `query` | string | ✅ | Search query (show title) |

```bash
curl "https://epguides.frecar.no/shows/search?query=breaking"
```

---

### :material-information: Get Show

```http
GET /shows/{epguides_key}
```

Get detailed metadata for a specific show.

!!! example "Parameters"
    | Parameter | Type | Description |
    |-----------|------|-------------|
    | `epguides_key` | path | Show identifier (e.g., `BreakingBad`) |
    | `include` | query | Set to `episodes` to include episode list |
    | `refresh` | query | Set to `true` to bypass cache |

=== ":material-television: Show Only"

    ```bash
    curl "https://epguides.frecar.no/shows/BreakingBad"
    ```

=== ":material-playlist-play: With Episodes"

    ```bash
    curl "https://epguides.frecar.no/shows/BreakingBad?include=episodes"
    ```

=== ":material-refresh: Force Refresh"

    ```bash
    curl "https://epguides.frecar.no/shows/BreakingBad?refresh=true"
    ```

??? success "Response"
    ```json
    {
      "epguides_key": "BreakingBad",
      "title": "Breaking Bad",
      "imdb_id": "tt0903747",
      "network": "AMC",
      "run_time_min": 60,
      "start_date": "2008-01-20",
      "end_date": "2013-09-29",
      "country": "US",
      "total_episodes": 63,
      "external_epguides_url": "http://www.epguides.com/BreakingBad",
      "external_imdb_url": "https://www.imdb.com/title/tt0903747",
      "api_self_url": "https://epguides.frecar.no/shows/BreakingBad",
      "api_episodes_url": "https://epguides.frecar.no/shows/BreakingBad/episodes"
    }
    ```

---

## :material-playlist-play: Episodes

### :material-format-list-numbered: Get Episodes

```http
GET /shows/{epguides_key}/episodes
```

Get all episodes with optional filtering.

!!! example "Filter Parameters"
    | Parameter | Type | Description |
    |-----------|------|-------------|
    | `season` | integer | Filter by season number |
    | `episode` | integer | Filter by episode (requires `season`) |
    | `year` | integer | Filter by release year |
    | `title_search` | string | Search in episode titles |
    | `nlq` | string | Natural language query (requires LLM) |
    | `refresh` | boolean | Bypass cache |

=== ":material-playlist-play: All Episodes"

    ```bash
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes"
    ```

=== ":material-filter: By Season"

    ```bash
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=2"
    ```

=== ":material-target: Specific Episode"

    ```bash
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=2&episode=5"
    ```

=== ":material-calendar: By Year"

    ```bash
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?year=2008"
    ```

=== ":material-text-search: Title Search"

    ```bash
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?title_search=pilot"
    ```

=== ":material-robot: Natural Language"

    ```bash
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"
    ```

??? success "Response"
    ```json
    [
      {
        "number": 1,
        "season": 1,
        "title": "Pilot",
        "release_date": "2008-01-20",
        "is_released": true,
        "run_time_min": 60,
        "episode_number": 1,
        "summary": "A high school chemistry teacher..."
      }
    ]
    ```

---

### :material-skip-next: Get Next Episode

```http
GET /shows/{epguides_key}/episodes/next
```

Get the next unreleased episode for a show.

!!! info "Smart Caching"
    This endpoint automatically refreshes if the cached "next" episode date has passed.

```bash
curl "https://epguides.frecar.no/shows/Severance/episodes/next"
```

??? success "Response (200)"
    ```json
    {
      "number": 11,
      "season": 2,
      "title": "TBA",
      "release_date": "2025-02-15",
      "is_released": false
    }
    ```

??? warning "Response (404)"
    Show has finished airing or no upcoming episodes.

---

### :material-skip-previous: Get Latest Episode

```http
GET /shows/{epguides_key}/episodes/latest
```

Get the most recently aired episode.

```bash
curl "https://epguides.frecar.no/shows/BreakingBad/episodes/latest"
```

---

## :material-robot: Natural Language Queries

!!! abstract "AI-Powered Filtering"
    When LLM is configured, use the `nlq` parameter for intelligent episode filtering.

### :material-head-cog: How It Works

1. :material-send: Your query is sent to an OpenAI-compatible LLM
2. :material-brain: The LLM analyzes episode titles, summaries, and metadata
3. :material-filter-check: Matching episodes are returned based on semantic understanding

### :material-code-tags: Examples

```bash
# 🏁 Find finale episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"

# ⚔️ Find episodes with major events
curl "https://epguides.frecar.no/shows/GameOfThrones/episodes?nlq=battle+episodes"

# 🎯 Combine with structured filters
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5&nlq=most+intense"
```

### :material-heart-pulse: Check LLM Status

```bash
curl "https://epguides.frecar.no/health/llm"
```

### :material-shield-check: Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| LLM not configured | `nlq` parameter silently ignored |
| LLM fails | Falls back to returning all episodes |
| Structured filters | Always work regardless of LLM |

---

## :material-note-text: Response Notes

!!! info "`end_date` Field"
    May be `null` if not available. Use individual show endpoint for derived values.

!!! info "`summary` Field"
    Episode summaries from TVMaze enable AI-powered search.

!!! info "`imdb_id` Field"
    Useful for cross-referencing with IMDB and other services.

---

## :material-heart-pulse: Health Endpoints

### :material-check-circle: Health Check

```bash
curl "https://epguides.frecar.no/health"
```

```json
{
  "status": "healthy",
  "service": "epguides-api",
  "version": "123"
}
```

### :material-robot-outline: LLM Health

```bash
curl "https://epguides.frecar.no/health/llm"
```

```json
{
  "enabled": true,
  "configured": true,
  "api_url": "https://api.openai.com/v1"
}
```
