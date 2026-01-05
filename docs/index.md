# Epguides API

<p align="center">
  <strong>A high-performance REST API and MCP server for accessing TV show metadata and episode lists.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11-blue.svg" alt="Python 3.11"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.128-green.svg" alt="FastAPI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://github.com/frecar/epguides-api"><img src="https://img.shields.io/github/stars/frecar/epguides-api?style=social" alt="GitHub Stars"></a>
</p>

---

!!! success "Public API Available"
    The API is live and free to use at **[epguides.frecar.no](https://epguides.frecar.no)**

## Quick Links

| Resource | Description |
|----------|-------------|
| :material-api: [Public API](https://epguides.frecar.no) | Production API endpoint |
| :material-file-document: [Swagger UI](https://epguides.frecar.no/docs) | Interactive API explorer |
| :material-robot: [MCP Endpoint](https://epguides.frecar.no/mcp) | MCP server for AI assistants |
| :material-github: [GitHub](https://github.com/frecar/epguides-api) | Source code & issues |

---

## ✨ Features

<div class="grid" markdown>

:material-television:{ .lg .middle } **Complete TV Database**

:   Access metadata for thousands of TV shows including air dates, networks, and episode counts.

:material-magnify:{ .lg .middle } **Smart Search**

:   Search by title with optional AI-powered natural language queries.

:material-calendar:{ .lg .middle } **Episode Tracking**

:   Get next/latest episodes, filter by season, year, or title.

:material-robot:{ .lg .middle } **MCP Server**

:   JSON-RPC interface for seamless AI assistant integration.

:material-lightning-bolt:{ .lg .middle } **Smart Caching**

:   7-day cache for ongoing shows, 1-year for finished shows.

:material-text:{ .lg .middle } **Episode Summaries**

:   Plot descriptions via TVMaze integration for AI-powered search.

</div>

---

## 🚀 Quick Start

Try the API right now:

=== "curl"

    ```bash
    # Get show details
    curl "https://epguides.frecar.no/shows/BreakingBad"
    
    # Search shows
    curl "https://epguides.frecar.no/shows/search?query=breaking"
    
    # Get episodes
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes"
    
    # Filter by season
    curl "https://epguides.frecar.no/shows/BreakingBad/episodes?season=5"
    ```

=== "Python"

    ```python
    import httpx

    async with httpx.AsyncClient() as client:
        # Get show details
        response = await client.get(
            "https://epguides.frecar.no/shows/BreakingBad"
        )
        show = response.json()
        print(f"Found: {show['title']} ({show['total_episodes']} episodes)")
        
        # Get episodes
        response = await client.get(show['api_episodes_url'])
        episodes = response.json()
    ```

=== "JavaScript"

    ```javascript
    // Get show details
    const response = await fetch(
      "https://epguides.frecar.no/shows/BreakingBad"
    );
    const show = await response.json();
    console.log(`Found: ${show.title} (${show.total_episodes} episodes)`);
    
    // Get episodes
    const episodesResponse = await fetch(show.api_episodes_url);
    const episodes = await episodesResponse.json();
    ```

---

## 📊 Data Sources

This API aggregates data from multiple trusted sources:

| Source | Data Provided | 
|--------|---------------|
| [epguides.com](http://epguides.com) | Show catalog, episode lists, air dates |
| [TVMaze API](https://api.tvmaze.com) | Episode summaries, plot descriptions |
| [IMDB](https://imdb.com) | IMDB IDs for cross-referencing |

---

## 🏗️ Architecture

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

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](getting-started.md) | Installation and local setup |
| [REST API](rest-api.md) | Complete endpoint reference |
| [MCP Server](mcp-server.md) | AI assistant integration |
| [Configuration](configuration.md) | Environment variables & caching |
| [Development](development.md) | Contributing & testing |

---

<p align="center">
  <a href="https://github.com/frecar/epguides-api">:material-github: View on GitHub</a> · 
  <a href="https://epguides.frecar.no/docs">:material-api: Try the API</a> · 
  <a href="getting-started.md">:material-rocket-launch: Get Started</a>
</p>
