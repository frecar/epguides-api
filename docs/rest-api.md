# REST API Reference

The Epguides API provides a RESTful interface to access TV show and episode data.

!!! tip "Public API"
    Base URL: `https://epguides.frecar.no`

## Endpoints Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/shows/` | List all shows (paginated) |
| `GET` | `/shows/search` | Search shows by title |
| `GET` | `/shows/{key}` | Get show metadata |
| `GET` | `/shows/{key}/episodes` | Get episodes with filtering |
| `GET` | `/shows/{key}/episodes/next` | Get next unreleased episode |
| `GET` | `/shows/{key}/episodes/latest` | Get latest released episode |
| `GET` | `/health` | Health check |
| `GET` | `/health/llm` | LLM configuration status |
| `POST` | `/mcp` | MCP JSON-RPC endpoint |

---

## Shows

### List Shows

```http
GET /shows/
```

Returns a paginated list of all TV shows.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Page number |
| `page_size` | integer | 50 | Items per page (max 100) |

**Example:**

```bash
curl "https://epguides.frecar.no/shows/?page=1&page_size=20"
```

---

### Search Shows

```http
GET /shows/search
```

Search for shows by title.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query (show title) |

**Example:**

```bash
curl "https://epguides.frecar.no/shows/search?query=breaking"
```

---

### Get Show

```http
GET /shows/{epguides_key}
```

Get detailed metadata for a specific show.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `epguides_key` | string | Show identifier (e.g., `BreakingBad`) |

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include` | string | - | Set to `episodes` to include episode list |
| `refresh` | boolean | false | Bypass cache and fetch fresh data |

**Examples:**

```bash
# Get show metadata only
curl "https://epguides.frecar.no/shows/BreakingBad"

# Get show with episodes
curl "https://epguides.frecar.no/shows/BreakingBad?include=episodes"

# Force fresh data
curl "https://epguides.frecar.no/shows/BreakingBad?refresh=true"
```

**Response:**

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

## Episodes

### Get Episodes

```http
GET /shows/{epguides_key}/episodes
```

Get all episodes for a show with optional filtering.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `season` | integer | Filter by season number |
| `episode` | integer | Filter by episode number (requires `season`) |
| `year` | integer | Filter by release year |
| `title_search` | string | Search in episode titles |
| `nlq` | string | Natural language query (requires LLM) |
| `refresh` | boolean | Bypass cache and fetch fresh data |

**Examples:**

=== "Basic"

    ```bash
    # All episodes
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes"
    ```

=== "By Season"

    ```bash
    # Season 2 only
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=2"
    
    # Specific episode
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=2&episode=5"
    ```

=== "By Year"

    ```bash
    # Episodes from 2008
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?year=2008"
    ```

=== "Title Search"

    ```bash
    # Search titles
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?title_search=pilot"
    ```

=== "Natural Language"

    ```bash
    # Find finales (requires LLM)
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"
    
    # Combine with structured filters
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5&nlq=most+intense"
    ```

**Response:**

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

### Get Next Episode

```http
GET /shows/{epguides_key}/episodes/next
```

Get the next unreleased episode for a show.

!!! info "Smart Caching"
    This endpoint automatically refreshes if the cached "next" episode date has passed.

**Example:**

```bash
curl "https://epguides.frecar.no/shows/Severance/episodes/next"
```

**Response (200):**

```json
{
  "number": 11,
  "season": 2,
  "title": "TBA",
  "release_date": "2025-02-15",
  "is_released": false
}
```

**Response (404):** Show has finished airing or no upcoming episodes.

---

### Get Latest Episode

```http
GET /shows/{epguides_key}/episodes/latest
```

Get the most recently aired episode.

**Example:**

```bash
curl "https://epguides.frecar.no/shows/BreakingBad/episodes/latest"
```

---

## Natural Language Queries

When LLM is configured, use the `nlq` parameter for AI-powered filtering.

### How It Works

1. Your query is sent to an OpenAI-compatible LLM
2. The LLM analyzes episode titles, summaries, and metadata
3. Matching episodes are returned based on semantic understanding

### Examples

```bash
# Find finale episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"

# Find episodes with major events
curl "https://epguides.frecar.no/shows/GameOfThrones/episodes?nlq=episodes+where+main+characters+die"

# Combine with structured filters (apply season filter first, then NLQ)
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5&nlq=most+intense"
```

### Check LLM Status

```bash
curl "https://epguides.frecar.no/health/llm"
```

### Graceful Degradation

- **LLM not configured** → `nlq` parameter is silently ignored
- **LLM fails** → Falls back to returning all episodes (no error)
- Structured filters always work regardless of LLM status

---

## Response Notes

### `end_date` Field

The `end_date` field may be `null` if not available in the master data. Use the individual show endpoint to get derived values from episode data.

### `summary` Field

Episode summaries are fetched from TVMaze and enable AI-powered search through episode content.

### `imdb_id` Field

When available, useful for cross-referencing with IMDB and other services.

---

## Health Endpoints

### Health Check

```http
GET /health
```

```json
{
  "status": "healthy",
  "service": "epguides-api",
  "version": "123"
}
```

### LLM Health

```http
GET /health/llm
```

```json
{
  "enabled": true,
  "configured": true,
  "api_url": "https://api.openai.com/v1"
}
```
