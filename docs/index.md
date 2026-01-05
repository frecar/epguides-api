# Epguides API

A high-performance REST API and MCP server for accessing TV show metadata and episode lists.

## Quick Links

| Resource | Description |
|----------|-------------|
| [Public API](https://epguides.frecar.no) | Production API endpoint |
| [Swagger UI](https://epguides.frecar.no/docs) | Interactive API explorer |
| [MCP Endpoint](https://epguides.frecar.no/mcp) | MCP server for AI assistants |
| [GitHub](https://github.com/frecar/epguides-api) | Source code |

## Features

- 📺 **Complete TV Database** - Access metadata for thousands of TV shows including air dates, networks, and episode counts
- 🔍 **Smart Search** - Search by title with optional AI-powered natural language queries
- 📅 **Episode Tracking** - Get next/latest episodes, filter by season, year, or title
- 🤖 **MCP Server** - JSON-RPC interface for seamless AI assistant integration
- ⚡ **Smart Caching** - 7-day cache for ongoing shows, 1-year for finished shows
- 📝 **Episode Summaries** - Plot descriptions via TVMaze integration

---

## Quick Start

=== "curl"

    ```bash
    # Get show details
    curl "https://epguides.frecar.no/shows/BreakingBad"
    
    # Search shows
    curl "https://epguides.frecar.no/shows/search?query=breaking"
    
    # Get episodes
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes"
    ```

=== "Python"

    ```python
    import httpx

    async with httpx.AsyncClient() as client:
        # Get show details
        response = await client.get("https://epguides.frecar.no/shows/BreakingBad")
        show = response.json()
        
        # Get episodes
        response = await client.get(f"{show['api_episodes_url']}")
        episodes = response.json()
    ```

=== "JavaScript"

    ```javascript
    // Get show details
    const response = await fetch("https://epguides.frecar.no/shows/BreakingBad");
    const show = await response.json();
    
    // Get episodes
    const episodesResponse = await fetch(show.api_episodes_url);
    const episodes = await episodesResponse.json();
    ```

---

## Data Sources

This API aggregates data from multiple sources:

| Source | Data Provided | Used For |
|--------|---------------|----------|
| [epguides.com](http://epguides.com) | Show catalog, episode lists, air dates | Core show and episode data |
| [TVMaze API](https://api.tvmaze.com) | Episode summaries, plot descriptions | AI-powered search, enhanced episode info |
| [IMDB](https://imdb.com) | IMDB IDs | Cross-referencing with IMDB |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Epguides API                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐  │
│   │  REST API   │     │ MCP Server  │     │   Health    │  │
│   │  /shows/*   │     │    /mcp     │     │   /health   │  │
│   └──────┬──────┘     └──────┬──────┘     └─────────────┘  │
│          │                   │                              │
│          └─────────┬─────────┘                              │
│                    │                                        │
│          ┌─────────▼─────────┐                              │
│          │  Service Layer    │                              │
│          │  (show_service)   │                              │
│          └─────────┬─────────┘                              │
│                    │                                        │
│   ┌────────────────┼────────────────┐                       │
│   │                │                │                       │
│   ▼                ▼                ▼                       │
│ ┌─────┐      ┌──────────┐    ┌───────────┐                 │
│ │Redis│      │ epguides │    │  TVMaze   │                 │
│ │Cache│      │   .com   │    │    API    │                 │
│ └─────┘      └──────────┘    └───────────┘                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](getting-started.md) | Installation and setup |
| [REST API](rest-api.md) | Complete endpoint reference |
| [MCP Server](mcp-server.md) | AI assistant integration |
| [Configuration](configuration.md) | Environment variables and caching |
| [Development](development.md) | Contributing and testing |
