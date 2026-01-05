# REST API

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/shows/` | List all shows (paginated) |
| `GET` | `/shows/search?query={query}` | Search shows by title |
| `GET` | `/shows/{epguides_key}` | Get show metadata |
| `GET` | `/shows/{epguides_key}?include=episodes` | Get show + episodes |
| `GET` | `/shows/{epguides_key}/episodes` | Get episodes with filtering |
| `GET` | `/shows/{epguides_key}/episodes/next` | Get next unreleased episode |
| `GET` | `/shows/{epguides_key}/episodes/latest` | Get latest released episode |
| `GET` | `/health` | Health check |
| `GET` | `/health/llm` | LLM configuration status |
| `POST` | `/mcp` | MCP JSON-RPC endpoint |
| `GET` | `/mcp/health` | MCP server health check |

## Examples

### Search Shows

```bash
curl "https://epguides.frecar.no/shows/search?query=breaking"
```

### Get Show Details

```bash
curl "https://epguides.frecar.no/shows/BreakingBad"
```

### Get Episodes

```bash
# All episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes"

# Filter by season
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=2"

# Filter by season and episode
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=2&episode=5"

# Filter by year
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?year=2008"

# Search in titles
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?title_search=pilot"
```

### Natural Language Queries

When LLM is configured, you can use natural language to filter episodes:

```bash
# Find finale episodes
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?nlq=finale+episodes"

# Combine with structured filters
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5&nlq=most+intense"
```

### Cache Control

```bash
# Force fresh data (bypass cache)
curl "https://epguides.frecar.no/shows/BreakingBad/episodes?refresh=true"
```

## Response Format

### Show Schema

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

### Episode Schema

```json
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
```

## Notes

- **`end_date` field**: May be `null` if the show's end date is not available. Use the individual show endpoint for derived values.
- **`summary` field**: Episode summaries from TVMaze. Enables AI-powered search.
- **`imdb_id` field**: IMDB ID for cross-referencing with other services.

